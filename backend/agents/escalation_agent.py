"""The Escalation sub-agent: the handover to a human.

Agent-as-Tool (`architecture.md` -> Stack), the same shape as
`scheduling_agent.py`: a Strands `Agent` over `tools/escalations.py`,
wrapped as one `@tool` the Orchestrator calls. It is the route
`architecture.md` -> Invariants #6 names -- anything outside the rules
`backend/tools/` encodes goes through here instead of being improvised by
the model -- and, like every sub-agent, it is never reachable from the
frontend (Invariants #2).

**One tool, deliberately.** `tools/escalations.py` also has
`list_open_escalations`, `get_escalation` and `resolve_escalation`, and
none of them belongs here. Those are *staff* reads: they answer "what is
outstanding at this clinic?" and "who has dealt with it?", questions a
patient on the phone has no business asking. They are the dashboard's,
behind Cognito (`architecture.md` -> Invariants #5). A patient-facing
agent that could read the queue could read another caller's complaint out
loud.

**No business logic lives here.** The wrapper supplies the session's
`clinic_id` and the `source`, hands `reason` and the optional
back-references to `backend/tools/`, and translates a refusal
(`architecture.md` -> Invariants #3). It also does not decide *whether*
to escalate: the Orchestrator makes that call and invokes this agent, so
by the time anything here runs the decision is already taken.

**`source` is not a parameter the model sees**, for the reason `actor` is
not one on `reschedule_appointment`: it records which path raised the
escalation, and the two paths each know their own. This module is the
live voice session, so it passes `voice`; the background Lambda will call
the same function with `background`.

**A failed escalation must not be reported as a successful one.** This is
the one place `results.INTERNAL_FAILURE_MESSAGE` reads oddly -- it tells
the model to say a member of staff will follow up, which is true when a
*booking* tool breaks and false here, because the thing that records the
follow-up is the thing that just failed. The system prompt below
overrides it for this agent, rather than the shared message being made
vaguer for every other one.

Everything is built per session rather than at import, as in
`scheduling_agent.py`: the tool is bound to one clinic, and a
module-level agent would be the process-level shared state
`code-standards.md` forbids.
"""

from __future__ import annotations

from typing import Any

from strands import Agent, tool
from strands.models.model import Model
from strands.tools.decorator import DecoratedFunctionTool

from tools import escalations
from tools.schema import EscalationSource

from .results import call
from .session import ClinicSession

ESCALATION_SYSTEM_PROMPT = """You are the escalation assistant for a single clinic.
You are called by the clinic's front-desk agent, which is talking to a patient by
voice. Answer it in one or two short sentences of plain spoken English -- what you
recorded, or what you still need from it. It reads your answer out.

{clinic}

What you handle: writing down that a member of staff has to deal with something,
so it reaches the clinic's queue and a person picks it up. That is your whole job.
You do not answer the question that caused the escalation -- not prices, not
treatments, not clinical advice, not billing, not the clinic's policies -- and you
do not book, move or cancel anything. The agent that called you has already
decided this needs a human; your part is to write it down well.

How to work:

- Call create_escalation once, and once only, for one thing needing a human. It
  has no undo and no duplicate check, so a second call puts a second card in the
  clinic's queue for the same problem. Once it has returned successfully you are
  done: say so and stop.
- The reason is read by a member of clinic staff and by nothing else, and it is
  all they get. Write what the patient asked for, what stopped it, and anything
  they said that the person calling them back will need. Plain sentences. Not an
  error code, and not "patient needs help".
- Put the patient's name and phone number in the reason when you have been given
  them -- that is how staff reach them. Never invent either, and never write a
  number you were not told.
- Pass patient_id or appointment_id only when a tool in this conversation
  returned that exact id. Never build one, and never guess one from a name, a
  service or a time: a wrong id sends staff to the wrong record. Leaving them out
  is normal and costs nothing.
- Tell the patient that a member of staff will follow up. Never tell them the
  thing they asked for has been done, approved, refunded or agreed -- nothing was
  decided, it was written down for a person to decide.
- Do not promise when. You do not know the clinic's callback times, and "within
  the hour" is a promise the clinic never made.
- If create_escalation does not succeed, nothing was recorded. Do not say a
  member of staff will follow up. Say plainly that you could not record it, and
  report that back to the agent that called you so it can tell the patient to
  ring the clinic."""


def escalation_tools(session: ClinicSession) -> list[DecoratedFunctionTool]:
    """The one escalation tool a patient-facing agent may hold, bound to a clinic.

    Args:
        session: The clinic this conversation is pinned to. Its
            `clinic_id` is closed over by the tool below and is not
            visible to the model.

    Returns:
        `create_escalation`, and nothing else -- the reads in
        `tools/escalations.py` are staff-only (see the module docstring).
    """
    clinic_id = session.clinic_id

    @tool(name="create_escalation")
    def create_escalation(
        reason: str,
        patient_id: str | None = None,
        appointment_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a member of clinic staff has to deal with something.

        This puts one item in the clinic's escalation queue, which staff
        work through on their dashboard. It decides nothing and changes
        no appointment: it is a note asking a human to act.

        There is no undo and no duplicate check. Calling this twice about
        one problem puts two cards in the queue and two people work the
        same case, so call it once and stop.

        Args:
            reason: What needs a human, in plain sentences. A member of
                staff reads this and nothing else, so write what the
                patient asked for, what stopped it, and how to reach
                them -- their name and phone number if you were given
                them. Never write a number you were not told.
            patient_id: Optional. The patient this is about, only if a
                tool in this conversation returned that exact id. It is
                stored as given and never checked, so a guessed id sends
                staff to the wrong record. Leave it out otherwise.
            appointment_id: Optional. The appointment this is about, on
                the same terms -- an id a tool returned here, never one
                you built from a service, a name or a time.

        Returns:
            The stored escalation: `escalation_id`, `status` (`open`),
            `reason`, `created_at`, and any back-reference you passed.
            The id is the clinic's reference, not the patient's -- do not
            read it out. Once this returns, tell the patient a member of
            staff will follow up, and nothing beyond that.
        """
        return call(
            "create_escalation",
            escalations.create_escalation,
            clinic_id=clinic_id,
            reason=reason,
            patient_id=patient_id,
            appointment_id=appointment_id,
            # Not the model's to choose: it records which path raised
            # this. The background Lambda calls the same function with
            # `background`.
            source=EscalationSource.VOICE,
        )

    return [create_escalation]


def build_escalation_agent(
    session: ClinicSession, model: Model | str | None = None
) -> Agent:
    """Construct the Escalation sub-agent for one clinic.

    Args:
        session: The clinic this conversation is pinned to.
        model: Which model to run on. `None` leaves the Strands default,
            for the reason `build_scheduling_agent` records: the text
            model the sub-agents reason with is an open question, not one
            to settle inside an agent module.

    Returns:
        An `Agent` holding `create_escalation` and a system prompt
        carrying this clinic's name, local date and services.
    """
    return Agent(
        name="escalation_agent",
        description="Records that a member of clinic staff must deal with something.",
        model=model,
        system_prompt=ESCALATION_SYSTEM_PROMPT.format(clinic=session.describe()),
        tools=escalation_tools(session),
        # As in `scheduling_agent.py`: a sub-agent's output is a return
        # value for the Orchestrator, and in AgentCore stdout is the log.
        callback_handler=None,
    )


def escalation_agent_tool(
    session: ClinicSession, model: Model | str | None = None
) -> DecoratedFunctionTool:
    """Wrap the Escalation sub-agent as one tool for the Orchestrator.

    The Agent-as-Tool boundary. The Orchestrator sees a tool that takes
    the situation in words; the writing of a reason a human can act on
    happens behind it.

    A fresh sub-agent is built per call rather than held across the
    session, as in `scheduling_agent.py` -- it is given the whole
    situation each time and keeps no conversation of its own, so nothing
    accumulates in its context over a long call.

    Args:
        session: The clinic this conversation is pinned to.
        model: Passed to `build_escalation_agent`.

    Returns:
        A Strands tool named `escalation_assistant`.
    """

    @tool(name="escalation_assistant")
    def escalation_assistant(request: str) -> str:
        """Hand something to the clinic's staff, when you cannot deal with it.

        Use this for anything your tools do not cover and you must not
        answer yourself: prices and quotes, refunds and billing,
        complaints, clinical or treatment questions, preparation
        instructions, insurance, and anything the clinic's own rules
        decide. Use it too when another assistant hands something back as
        not its own.

        It records the request for a member of staff and returns. It does
        not answer the question, promise anything, or change an
        appointment -- so do not call it hoping for the answer, and do
        not tell the patient afterwards that their request has been
        granted.

        Do not use it for something the patient can settle themselves: a
        time that has been taken, a name that does not match the number,
        or a day the clinic is closed are things to ask them about, not
        things to put in front of staff.

        Args:
            request: What needs a human and why, in plain words, plus
                what you already know from the conversation -- the
                patient's name and phone number, what they asked for,
                what was tried, and any appointment or patient id a tool
                gave you. Staff see only what you pass on; it cannot hear
                the patient itself.

        Returns:
            A short answer to read to the patient -- normally that a
            member of staff will follow up. If it says it could not
            record the escalation, nothing was written down: do not
            promise a callback, tell the patient to ring the clinic
            directly.
        """
        # Stripped for the reason `scheduling_assistant` strips: an
        # `AgentResult` renders with a trailing newline, and this string
        # is read out loud rather than printed.
        return str(build_escalation_agent(session, model)(request)).strip()

    return escalation_assistant
