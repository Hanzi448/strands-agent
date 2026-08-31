"""The Orchestrator: the agent the patient actually talks to.

`project-overview.md` -> Core User Flow gives it three jobs -- greet the
patient, work out what they want, and route it to the sub-agent that can
do it. `architecture.md` -> Invariants #2 gives it the fourth by
implication: it is the *only* agent the outside world reaches, and the
Scheduling, FAQ and Escalation agents exist for it alone.

**It holds no `backend/tools/` function.** Its entire tool surface is the
three Agent-as-Tool wrappers, each of which takes a request in words. So
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

A question about prices, treatments, preparation or policy now has its
own route, `faq_assistant`, over the clinic's own Knowledge Base -- it no
longer becomes a staff callback by default. `escalation_assistant`
remains the route for anything the FAQ assistant could not answer and
the patient still needs settled, and for everything that was never a
published fact to begin with (a refund, a complaint, a clinical
judgement).

Everything is per session, as in the sub-agent modules: the tools are
bound to one clinic, and a module-level agent would be the process-level
shared state `code-standards.md` forbids -- here it would also be one
patient's conversation handed to the next caller.
"""

from __future__ import annotations

from typing import Final

from strands import Agent
from strands.models.model import Model
from strands.tools.decorator import DecoratedFunctionTool

from .escalation_agent import escalation_agent_tool
from .faq_agent import faq_agent_tool
from .scheduling_agent import scheduling_agent_tool
from .session import ClinicSession

# The turn that opens the call. Neither interface's model speaks
# unprompted -- a Strands `Agent` answers only when it is spoken to, and a
# `BidiAgent` holds an open connection in silence until it is sent
# something -- while `project-overview.md` -> Core User Flow has the
# Orchestrator greet the patient. So something has to prompt the first
# turn, and it is the same something for the keyboard and for the
# microphone.
#
# It is a stage direction rather than a greeting of our own, which is what
# keeps the greeting the *model's*: the prompt below tells it to open with
# the clinic's name, and this is what lets it. It lives here, with the
# agent that has to be prompted, so both interfaces run the experiment
# with one string rather than two that drift.
OPENING_TURN: Final[str] = (
    "[The patient has just been connected and is waiting for you to speak.]"
)

# Which model the text agents in a session reason with -- this one where
# the patient is typing, and both sub-agents either way. Still an open
# question in `progress-tracker.md`: `architecture.md` -> Stack names Nova
# Sonic for the voice layer and nothing for the text agents, and unset
# means "whatever Strands defaults to", which is a working default and not
# a decision.
#
# The *value* is chosen by an interface -- `cli.py` and `mic.py` both read
# this and pass it down -- because no agent definition should name a
# model. The name of the variable lives here, with the agents it
# configures, for the same reason `OPENING_TURN` does: two interfaces
# reading two copies of one string is how they drift.
TEXT_MODEL_ENV: Final[str] = "CLINICPILOT_TEXT_MODEL"

ORCHESTRATOR_SYSTEM_PROMPT = """You are the front desk of a single clinic, talking
to a patient on the telephone. Everything you say is read out loud to them, so
speak in short plain sentences, one or two at a time. Never read out an id, a
reference number or a timestamp.

{clinic}

You have three assistants and no other way of doing anything. You do not know
this clinic's diary, its prices, its treatments or its policies. Anything you
tell the patient about them must have come back from an assistant in this
conversation.

- scheduling_assistant: the appointment diary -- when the clinic is free,
  booking, moving and cancelling.
- faq_assistant: prices, treatments, preparation and policy questions -- what
  the clinic has published about itself. Not the diary.
- escalation_assistant: writing something down for a member of clinic staff to
  deal with, for anything none of your other assistants can settle.

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
- Send a question about prices, treatments, preparation or policy to the faq
  assistant first -- it knows what the clinic has published, you do not. Only
  send it to a member of staff instead if the faq assistant says it does not
  have the answer and the patient still needs one settled.
- Send it to a member of staff when the patient asks for clinical judgement,
  billing, insurance, a refund or a complaint; when they are upset or ask to
  speak to a person; when the faq assistant could not answer and the patient
  still needs one; or when something in the system has failed and the patient
  cannot do anything about it. Once for each thing -- a second call puts a
  second card in the clinic's queue.
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
    """The three sub-agents, as the only tools the front desk holds.

    Deliberately not a place where a `backend/tools/` function could be
    added "just for a quick lookup": the Orchestrator's surface is words
    in, words out, and everything that touches the clinic's data does so
    behind one of these three.

    Args:
        session: The clinic this conversation is pinned to. Closed over
            by every sub-agent, so no tool here has a `clinic_id`
            parameter and the model is never offered a clinic
            (`architecture.md` -> Invariants #1).
        model: Passed down to every sub-agent, so one session runs on one
            model throughout.

    Returns:
        `scheduling_assistant`, `faq_assistant` and `escalation_assistant`,
        in the order a call is likely to reach them.
    """
    return [
        scheduling_agent_tool(session, model),
        faq_agent_tool(session, model),
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
        model: Which model to run on, for this agent and all three
            sub-agents. `None` leaves the Strands default, which is still
            an open question rather than a decision -- `architecture.md`
            -> Stack names Nova Sonic for the voice layer and says
            nothing about the text model behind it. One parameter threads
            through all four agents, so that when it is settled there is
            one place to settle it.

    Returns:
        An `Agent` holding `scheduling_assistant`, `faq_assistant` and
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
