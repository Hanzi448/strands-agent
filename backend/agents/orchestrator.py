"""The Orchestrator: the agent the patient actually talks to.

`project-overview.md` -> Core User Flow gives it three jobs -- greet the
patient, work out what they want, and route it to the sub-agent that can
do it. `architecture.md` -> Invariants #2 gives it the fourth by
implication: it is the *only* agent the outside world reaches, and the
Scheduling and Escalation agents exist for it alone.

**It holds no `backend/tools/` function.** Its entire tool surface is the
two Agent-as-Tool wrappers, each of which takes a request in words. So
there is no path by which the front desk writes to DynamoDB itself: a
booking is something it asks for and is told about, which is what keeps
the appointment rules in one place (Invariants #3) and keeps this module
about routing rather than about diaries.

**It is the only agent in this package that remembers anything.** A
sub-agent is built fresh for every call and keeps no conversation
(`scheduling_agent.py`), because the conversation is here: this `Agent`
is constructed once per session and accumulates `messages` across turns.
That is the whole division of labour -- the patient's thread of talk
lives in one place, and the multi-turn dance a booking takes does not
fill it.

**What it must not do is say things.** Prices, opening times, treatment
and preparation advice, policies: it has none of them, and it is told so
in as many words. `session.describe()` gives it the clinic's name,
today's local date and the services on offer -- enough to ask "which
treatment?" and no more. Anything else it tells a patient has to have
come back from an assistant in the same conversation.

Until the FAQ sub-agent lands with the Knowledge Base, a question about
prices or preparation has exactly one route: a member of staff, via
`escalation_assistant`. That is the correct answer today and a lossy one
-- the KB unit is what turns those into answers rather than callbacks.

Everything is per session, as in the sub-agent modules: the tools are
bound to one clinic, and a module-level agent would be the process-level
shared state `code-standards.md` forbids -- here it would also be one
patient's conversation handed to the next caller.
"""

from __future__ import annotations

from strands import Agent
from strands.models.model import Model
from strands.tools.decorator import DecoratedFunctionTool

from .escalation_agent import escalation_agent_tool
from .scheduling_agent import scheduling_agent_tool
from .session import ClinicSession

ORCHESTRATOR_SYSTEM_PROMPT = """You are the front desk of a single clinic, talking
to a patient on the telephone. Everything you say is read out loud to them, so
speak in short plain sentences, one or two at a time. Never read out an id, a
reference number or a timestamp.

{clinic}

You have two assistants and no other way of doing anything. You do not know this
clinic's diary, its prices, its treatments or its policies. Anything you tell the
patient about them must have come back from an assistant in this conversation.

- scheduling_assistant: the appointment diary -- when the clinic is free,
  booking, moving and cancelling.
- escalation_assistant: writing something down for a member of clinic staff to
  deal with, for anything neither you nor the scheduling assistant can settle.

How to work:

- Open the call by greeting the patient with the clinic's name and asking what
  you can do for them. Find out what they actually want before calling anything.
- Work out what an assistant will need before you call it, and ask for it in as
  few questions as you can: which service, which day, and -- to book, move or
  cancel -- the patient's name and phone number. An assistant cannot hear the
  patient, so anything you were told and did not pass on is lost.
- Pass on everything relevant in your own words. The assistant sees only the
  request you send it, not the conversation.
- Call one assistant at a time, and only once you have something to send it.
  Never call both about the same thing.
- Read the assistant's answer back to the patient in your own words. Do not add
  a time, a price, a service or a promise it did not give you.
- Never tell a patient an appointment is booked, moved or cancelled unless the
  scheduling assistant has said it was done.
- If the scheduling assistant hands something back as not its own, or refuses
  for a reason the patient cannot do anything about, that is yours to decide:
  either ask the patient the question that unblocks it, or send it to the
  escalation assistant.
- Send it to a member of staff when the patient asks about prices, treatments,
  clinical or preparation advice, billing, insurance, a refund or a complaint;
  when they are upset or ask to speak to a person; or when something in the
  system has failed and the patient cannot do anything about it. Once for each
  thing -- a second call puts a second card in the clinic's queue.
- Something the patient can settle themselves is not an escalation. A time that
  has been taken, a name that does not match the phone number, a day the clinic
  is closed: ask them about it, do not put it in front of staff.
- Never invent a price, an opening time, a treatment, a clinical answer or a
  policy, and never guess in order to be helpful. If an assistant has not given
  it to you, you do not have it, and saying so is the right answer.
- When staff have been told, say a member of staff will follow up, and do not
  say when -- you do not know the clinic's callback times. If the escalation
  assistant says it could not record it, nothing was written down: do not
  promise a callback, ask the patient to ring the clinic directly.
- Before the call ends, confirm what was actually done, in the patient's own
  terms -- the service, the day and the local time."""


def orchestrator_tools(
    session: ClinicSession, model: Model | str | None = None
) -> list[DecoratedFunctionTool]:
    """The two sub-agents, as the only tools the front desk holds.

    Deliberately not a place where a `backend/tools/` function could be
    added "just for a quick lookup": the Orchestrator's surface is words
    in, words out, and everything that touches the clinic's data does so
    behind one of these two.

    Args:
        session: The clinic this conversation is pinned to. Closed over
            by both sub-agents, so no tool here has a `clinic_id`
            parameter and the model is never offered a clinic
            (`architecture.md` -> Invariants #1).
        model: Passed down to both sub-agents, so one session runs on one
            model throughout.

    Returns:
        `scheduling_assistant` and `escalation_assistant`, in the order a
        call uses them.
    """
    return [
        scheduling_agent_tool(session, model),
        escalation_agent_tool(session, model),
    ]


def build_orchestrator(
    session: ClinicSession, model: Model | str | None = None
) -> Agent:
    """Construct the patient-facing agent for one clinic.

    Call this once per session and keep the returned agent: it is where
    the conversation lives. Building a second one mid-call would lose
    everything the patient has already said.

    Args:
        session: The clinic this conversation is pinned to.
        model: Which model to run on, for this agent and both sub-agents.
            `None` leaves the Strands default, which is still an open
            question rather than a decision -- `architecture.md` -> Stack
            names Nova Sonic for the voice layer and says nothing about
            the text model behind it. One parameter threads through all
            three agents, so that when it is settled there is one place
            to settle it.

    Returns:
        An `Agent` holding `scheduling_assistant` and
        `escalation_assistant`, and a system prompt carrying this
        clinic's name, local date and services.
    """
    return Agent(
        name="orchestrator",
        description="Answers a patient call for one clinic and routes it.",
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT.format(clinic=session.describe()),
        tools=orchestrator_tools(session, model),
        # Unlike the sub-agents, this one's output *is* the patient's
        # answer -- but rendering it belongs to the interface layer, not
        # to this module. The text CLI prints the return value and the
        # voice layer streams audio. Strands' default handler would
        # instead print every token and tool call to stdout, which in
        # AgentCore is the log, so a whole call including the patient's
        # name and phone number would land in CloudWatch.
        callback_handler=None,
    )


def start_call(clinic_id: str, model: Model | str | None = None) -> Agent:
    """Open a patient call: read the clinic, then build its front desk.

    The single entry point for anything driving a conversation -- the
    local text interface, and later the voice bridge -- so that no caller
    constructs a `ClinicSession` by hand and skips the checks
    `ClinicSession.start` runs. A clinic that does not exist, or whose
    stored timezone this process cannot resolve, fails here rather than
    inside the patient's first booking.

    Args:
        clinic_id: The clinic selected when the session started. It comes
            from the frontend (`architecture.md` -> Auth and Access
            Model) and is the last point at which a clinic is chosen:
            nothing in the conversation can change it.
        model: Passed to `build_orchestrator`.

    Returns:
        A fresh `Agent` for this call, holding no conversation yet.

    Raises:
        ValidationError: If `clinic_id` is missing or malformed.
        NotFoundError: If no clinic exists with that id.
        ConfigurationError: If the clinic's stored config is unusable.
    """
    return build_orchestrator(ClinicSession.start(clinic_id), model)
