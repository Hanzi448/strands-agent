"""The Scheduling sub-agent: the appointment half of the patient call.

Agent-as-Tool (`architecture.md` -> Stack): this module builds a Strands
`Agent` over the four scheduling functions in `backend/tools/` and wraps
*that agent* as a single `@tool` for the Orchestrator to call. The
Orchestrator decides intent; this agent runs the multi-turn dance a
booking actually takes -- check, offer, confirm, write -- without that
dance filling the Orchestrator's context. It is never reachable from the
frontend (`architecture.md` -> Invariants #2).

**No business logic lives here.** Every function below is a thin
model-facing wrapper: it supplies the session's `clinic_id`, hands the
rest to `backend/tools/`, and translates a refusal
(`code-standards.md` -> General, `architecture.md` -> Invariants #3).
Whether a slot can be offered, whether a caller may move an appointment,
and what happens on a conflict are decided in one place, which the
background Lambda calls too.

**`clinic_id` is not a parameter of any tool here.** The wrappers close
over a `ClinicSession`, so the model is never shown a clinic argument and
cannot supply one -- see `session.py`. The tool-layer functions still run
their own `require_clinic_id` first, so the guard
`code-standards.md` -> Python requires holds on both sides of this
boundary.

Everything is built per session rather than at import: the tools are
bound to one clinic, and a module-level agent would be exactly the
process-level shared state `code-standards.md` forbids.
"""

from __future__ import annotations

from typing import Any

from strands import Agent, tool
from strands.models.model import Model
from strands.tools.decorator import DecoratedFunctionTool

from tools import appointments, booking, scheduling

from .results import call
from .session import ClinicSession

SCHEDULING_SYSTEM_PROMPT = """You are the scheduling assistant for a single clinic.
You are called by the clinic's front-desk agent, which is talking to a patient
by voice. Answer it in one or two short sentences of plain spoken English --
what you did, or what you still need from the patient. It reads your answer out.

{clinic}

What you handle: checking when the clinic is free, booking an appointment,
moving one, and cancelling one. Nothing else. Prices, treatments, clinical
advice, preparation instructions, billing, complaints and anything about the
clinic's policies are not yours -- say plainly that you cannot answer it and
hand it back. Do not raise it with staff yourself; the agent that called you
decides that.

How to work:

- Never say a time is free unless check_availability returned it in this
  conversation. Do not reason about opening hours yourself -- the tool already
  accounts for hours, breaks, holidays, how long the service takes and what is
  already booked. If you have not called it, you do not know.
- Say times the way a person says them, from local_start and local_end. Never
  say a starts_at value out loud: it is UTC, and the clinic is not.
- When you book or move an appointment, pass the starts_at value exactly as
  check_availability returned it. Never build one from what the patient said.
- Turn what the patient said into a date yourself, using today's date above,
  and pass it as YYYY-MM-DD. Ask which day they mean if it is genuinely
  ambiguous; do not guess a year.
- Ask which service they want before checking availability. The service sets
  how long the appointment is, so the answer differs per service.
- Offer two or three times, not the whole list.
- Booking needs the patient's name and phone number. Ask for both. Never
  invent a phone number and never book with a name you were not given.
- Moving or cancelling needs their name and number too -- it is what stops one
  member of a household changing another's appointment.
- If a tool tells you the patient has more than one appointment coming up, it
  names them: ask the patient which one, then call the tool again with that
  appointment_id.
- If a tool refuses, its answer says why and often names the alternatives.
  Use it. Do not call the same tool again with the same arguments.
- Confirm what you actually did, once it is done -- the service, the day and
  the local time. Never say an appointment is booked, moved or cancelled
  before the tool that does it has returned successfully."""


def scheduling_tools(session: ClinicSession) -> list[DecoratedFunctionTool]:
    """The four scheduling tools, bound to one clinic.

    Args:
        session: The clinic this conversation is pinned to. Its
            `clinic_id` is closed over by every tool below and is not
            visible to the model.

    Returns:
        `check_availability`, `book_appointment`,
        `reschedule_appointment` and `cancel_appointment`, in the order a
        call uses them.
    """
    clinic_id = session.clinic_id

    @tool(name="check_availability")
    def check_availability(
        date: str, service: str, days: int | None = None
    ) -> dict[str, Any]:
        """List the appointment start times this clinic can offer, from a date on.

        Reads the clinic's opening hours for each day, drops whole-day
        closures, and removes anything that would clash with an existing
        appointment or run past the end of an opening period. A time is
        offered only if the whole appointment fits, so a 60-minute
        treatment is never offered half an hour before a lunch break.

        Call this before booking or moving anything. Nothing is booked or
        changed by it.

        Args:
            date: The first day to check, as YYYY-MM-DD in the clinic's
                own calendar. Work it out from today's date in your
                instructions; do not pass a spoken phrase.
            service: Which service the appointment is for, as the service
                id or the name the clinic uses. Required even to look,
                because it sets how long the appointment is.
            days: How many days from `date` to check, at most 14. Leave it
                out for a single day. Use it only when the patient is
                flexible about the day -- a wide window is a long list.

        Returns:
            `slots`: every time that can be offered across the window,
            earliest first, each with `date`, `local_start` and
            `local_end` to say out loud and `starts_at` to pass back when
            booking. `days_checked` says what happened to each day:
            `is_open` false with a `closure_label` is a one-off closure
            worth naming to the patient, false without one means the
            clinic never opens that weekday, and true with `slot_count` 0
            means it is open but fully booked. Also `service` as the
            clinic defines it, and the clinic's `timezone`.

            An empty `slots` list is an answer, not a failure -- tell the
            patient which of those three it is.
        """
        return call(
            "check_availability",
            scheduling.check_availability,
            clinic_id=clinic_id,
            date=date,
            service=service,
            days=days,
        )

    @tool(name="book_appointment")
    def book_appointment(
        starts_at: str,
        service: str,
        patient_name: str,
        patient_phone: str,
        patient_email: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Book one appointment, registering the caller if they are new.

        The time is checked again before anything is written, because a
        slot quoted earlier in the conversation may have gone since. A
        time that cannot be offered is refused rather than moved to a
        near one -- so never adjust a time yourself to make it fit.

        Args:
            starts_at: The start, copied exactly from a slot
                `check_availability` returned. Not a local time, and not
                one you built from what the patient said.
            service: The service to book, as its id or name. It must be
                the service the availability check was made for.
            patient_name: The caller's name, as they gave it. Ask; never
                assume.
            patient_phone: The caller's phone number, as they said it.
                This is how they are recognised next time they call, so
                ask for it and read it back.
            patient_email: Optional. An address for appointment
                reminders. A caller who has one stored already keeps it.
            notes: Optional. Anything the patient said about the visit
                that staff should see.

        Returns:
            The booked appointment: `appointment_id`, `service`, `date`,
            `local_start` and `local_end` to confirm out loud, and
            `patient` with `is_new`. `is_new` false means this caller
            already had a record -- worth acknowledging rather than
            asking them for details they have given before.

            A refusal names times that are still free that day, so you
            can offer one immediately instead of starting over.
        """
        return call(
            "book_appointment",
            booking.book_appointment,
            clinic_id=clinic_id,
            starts_at=starts_at,
            service=service,
            patient_name=patient_name,
            patient_phone=patient_phone,
            patient_email=patient_email,
            notes=notes,
        )

    @tool(name="reschedule_appointment")
    def reschedule_appointment(
        patient_phone: str,
        patient_name: str,
        new_starts_at: str,
        appointment_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Move one of the caller's appointments to a different time.

        Changes when, not what: the service and its length stay the same.
        A patient who wants a different treatment needs this one
        cancelled and a new one booked.

        Check availability for the new time first. It is re-checked here
        before anything is written, and a time that cannot be offered is
        refused rather than adjusted.

        Args:
            patient_phone: The caller's number, as they said it.
            patient_name: The caller's name. Required as well as the
                number -- it is what stops one member of a household
                moving another's appointment.
            new_starts_at: The new start, copied exactly from a slot
                `check_availability` returned.
            appointment_id: Which appointment to move. Leave it out when
                the caller has only one coming up. If they have several,
                this refuses and names them -- ask which, then call again
                with that id.
            reason: Optional. Why it moved, in the patient's own terms.
                Clinic staff read it in their log of what the agent did,
                so pass what the patient told you.

        Returns:
            The appointment at its new time -- `date`, `local_start`,
            `local_end` -- plus `previous` with the same fields for where
            it was, so you can confirm the move in full.
        """
        return call(
            "reschedule_appointment",
            appointments.reschedule_appointment,
            clinic_id=clinic_id,
            patient_phone=patient_phone,
            patient_name=patient_name,
            new_starts_at=new_starts_at,
            appointment_id=appointment_id,
            reason=reason,
        )

    @tool(name="cancel_appointment")
    def cancel_appointment(
        patient_phone: str,
        patient_name: str,
        appointment_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Cancel one of the caller's upcoming appointments.

        The time is free for someone else the moment this returns. The
        appointment stays in the clinic's records as cancelled history,
        so a patient who changes their mind needs a fresh booking rather
        than this one undone -- do not offer to reinstate it.

        Args:
            patient_phone: The caller's number, as they said it.
            patient_name: The caller's name. Required as well as the
                number -- it is what stops one member of a household
                cancelling another's appointment.
            appointment_id: Which appointment to cancel. Leave it out
                when the caller has only one coming up. If they have
                several, this refuses and names them -- ask which, then
                call again with that id.
            reason: Optional. Why it was cancelled. Staff read it, and a
                cancellation with no reason tells them nothing, so pass
                what the patient said.

        Returns:
            The appointment that was cancelled -- `service`, `date`,
            `local_start` and `local_end` -- so you can read back what
            was called off as confirmation.
        """
        return call(
            "cancel_appointment",
            appointments.cancel_appointment,
            clinic_id=clinic_id,
            patient_phone=patient_phone,
            patient_name=patient_name,
            appointment_id=appointment_id,
            reason=reason,
        )

    return [
        check_availability,
        book_appointment,
        reschedule_appointment,
        cancel_appointment,
    ]


def build_scheduling_agent(
    session: ClinicSession, model: Model | str | None = None
) -> Agent:
    """Construct the Scheduling sub-agent for one clinic.

    Args:
        session: The clinic this conversation is pinned to.
        model: Which model to run on. `None` leaves the Strands default,
            which is deliberate for now -- `architecture.md` -> Stack
            names Nova Sonic for the voice layer and says nothing about
            the text model the sub-agents reason with. Recorded as an
            open question rather than decided here.

    Returns:
        An `Agent` holding the four scheduling tools and a system prompt
        carrying this clinic's name, local date and services.
    """
    return Agent(
        name="scheduling_agent",
        description="Books, moves and cancels appointments for one clinic.",
        model=model,
        system_prompt=SCHEDULING_SYSTEM_PROMPT.format(clinic=session.describe()),
        tools=scheduling_tools(session),
        # Strands' default handler prints every token and tool call to
        # stdout. A sub-agent's output is a return value for the
        # Orchestrator, not something to stream: the patient hears the
        # Orchestrator, and in AgentCore stdout is the log.
        callback_handler=None,
    )


def scheduling_agent_tool(
    session: ClinicSession, model: Model | str | None = None
) -> DecoratedFunctionTool:
    """Wrap the Scheduling sub-agent as one tool for the Orchestrator.

    This is the Agent-as-Tool boundary: the Orchestrator sees a single
    tool that takes a request in words, not the four appointment tools
    and the rules for sequencing them.

    A fresh sub-agent is built per call rather than held across the
    session. It is given the whole request each time and keeps no
    conversation of its own, so nothing accumulates in its context over a
    long call -- the Orchestrator is the one holding the conversation.

    Args:
        session: The clinic this conversation is pinned to.
        model: Passed to `build_scheduling_agent`.

    Returns:
        A Strands tool named `scheduling_assistant`.
    """

    @tool(name="scheduling_assistant")
    def scheduling_assistant(request: str) -> str:
        """Handle anything to do with this clinic's appointment diary.

        Use this for checking when the clinic is free, booking an
        appointment, moving one, or cancelling one. It knows the clinic's
        hours, services and existing bookings; you do not, so do not
        answer those from your own knowledge or quote a time it has not
        given you.

        It cannot answer questions about prices, treatments, preparation,
        policies or billing, and it does not raise anything with staff --
        those are yours to route elsewhere.

        Args:
            request: What the patient wants, in plain words, plus
                anything already established in the conversation that it
                needs -- the patient's name and phone number, which
                service, which day, and which appointment they mean.
                Pass these on; it cannot hear the patient itself and will
                otherwise ask you for them.

        Returns:
            A short answer to read to the patient: what was done, the
            times that can be offered, or what is still needed. If it
            says it cannot handle something, do not press it -- decide
            yourself whether that needs a member of staff.
        """
        # Stripped: an `AgentResult` renders with a trailing newline,
        # and this string is read out loud rather than printed.
        return str(build_scheduling_agent(session, model)(request)).strip()

    return scheduling_assistant
