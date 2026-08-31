"""The FAQ sub-agent: prices, treatments, preparation and policy questions.

Agent-as-Tool (`architecture.md` -> Stack), the same shape as
`scheduling_agent.py` and `escalation_agent.py`: a Strands `Agent` over one
`backend/tools/` function, wrapped as a single `@tool` the Orchestrator
calls. It exists to answer the class of question `orchestrator.py`'s own
docstring flagged as lossy until this landed -- price, treatment,
preparation and policy questions, which until now had exactly one route,
`escalation_assistant`, and became a staff callback rather than an answer.

**No business logic lives here.** The wrapper supplies the session's
`clinic_id`, hands `question` and the optional `max_results` to
`tools/faq.py`, and translates a refusal (`architecture.md` ->
Invariants #3). *Which* Knowledge Base is queried is decided by
`clinic_id` alone, never by anything the model chooses.

**It composes an answer; `query_faq` deliberately does not.**
`tools/faq.py` -> module docstring resolved `retrieve` over
`retrieve_and_generate` precisely so that phrasing stays a sub-agent
model's job -- this agent is that job. It is told to answer only from the
passages it was given, never from its own knowledge of dentistry or
cosmetics, for the same reason `scheduling_agent` is told never to reason
about opening hours itself: a fluent model will invent a plausible price
if allowed to, and a plausible wrong price is worse than "I don't know."

**No match is not this agent's decision to escalate.** `query_faq`
returns `found: False` as an ordinary answer, not a failure -- and
whether that becomes a card in the staff queue is the Orchestrator's call
to make (`architecture.md` -> Invariants #2 and #6), the same boundary
`escalation_agent.py` draws around raising escalations at all. This agent
says plainly that it does not have the answer and stops; it holds no
`create_escalation` tool of its own.

Everything is built per session rather than at import, as in the other
two sub-agents: the tool is bound to one clinic, and a module-level agent
would be the process-level shared state `code-standards.md` forbids.
"""

from __future__ import annotations

from typing import Any

from strands import Agent, tool
from strands.models.model import Model
from strands.tools.decorator import DecoratedFunctionTool

from tools import faq

from .results import call
from .session import ClinicSession

FAQ_SYSTEM_PROMPT = """You are the FAQ assistant for a single clinic.
You are called by the clinic's front-desk agent, which is talking to a patient
by voice. Answer it in one or two short sentences of plain spoken English --
the answer, or that you do not have one. It reads your answer out.

{clinic}

What you handle: prices, treatments, preparation instructions, policies and
anything else the clinic has published about itself -- questions that are not
about the appointment diary. You do not check availability, and you do not
book, move or cancel anything; that is the scheduling assistant's job.

How to work:

- Call query_faq with the patient's question, once. It returns passages from
  this clinic's own published information, closest match first -- read them
  and answer in your own words. Do not call it again with the same question
  hoping for a different answer.
- Answer only from the passages you were given. Never use your own general
  knowledge of dentistry, cosmetics, prices or clinics -- a plausible-sounding
  guess is a wrong answer the patient has no way to check.
- If found is false, or the passages do not actually answer what was asked,
  say plainly that you do not have that information. Do not guess, and do not
  soften it into an answer that sounds like one.
- You do not decide whether something needing a person gets escalated -- that
  is the front desk's call. Just say what you found, or that you did not find
  it, and stop.
- Keep the answer short enough to be read aloud once. If the passages cover
  more than the patient asked, answer only the question."""


def faq_tools(session: ClinicSession) -> list[DecoratedFunctionTool]:
    """The one FAQ tool a patient-facing agent may hold, bound to a clinic.

    Args:
        session: The clinic this conversation is pinned to. Its
            `clinic_id` is closed over by the tool below and is not
            visible to the model.

    Returns:
        `query_faq`, and nothing else.
    """
    clinic_id = session.clinic_id

    @tool(name="query_faq")
    def query_faq(question: str, max_results: int | None = None) -> dict[str, Any]:
        """Look up what this clinic has published about a question.

        Use this for anything about prices, treatments, preparation,
        policies or other published information -- not for availability
        or booking, which you have no tool for at all.

        This returns raw passages, not a phrased answer: read them
        yourself and answer the patient in your own words, using only
        what they say.

        Args:
            question: The patient's question, as asked or lightly
                cleaned up.
            max_results: Optional. How many passages to return at most.
                Leave it out unless the question is broad enough that a
                single passage is unlikely to cover it.

        Returns:
            `passages`: the closest-matching text, closest first. `found`:
            whether anything relevant came back -- check this before
            answering rather than inferring it from an empty list. An
            empty result is a normal answer: it means say plainly that
            you do not have that information, not that the call failed.
        """
        return call(
            "query_faq",
            faq.query_faq,
            clinic_id=clinic_id,
            question=question,
            max_results=max_results,
        )

    return [query_faq]


def build_faq_agent(session: ClinicSession, model: Model | str | None = None) -> Agent:
    """Construct the FAQ sub-agent for one clinic.

    Args:
        session: The clinic this conversation is pinned to.
        model: Which model to run on. `None` leaves the Strands default,
            for the reason `build_scheduling_agent` records: the text
            model the sub-agents reason with is an open question, not one
            to settle inside an agent module.

    Returns:
        An `Agent` holding `query_faq` and a system prompt carrying this
        clinic's name, local date and services.
    """
    return Agent(
        name="faq_agent",
        description="Answers prices, treatment, preparation and policy questions for one clinic.",
        model=model,
        system_prompt=FAQ_SYSTEM_PROMPT.format(clinic=session.describe()),
        tools=faq_tools(session),
        # As in the other two sub-agents: a sub-agent's output is a return
        # value for the Orchestrator, and in AgentCore stdout is the log.
        callback_handler=None,
    )


def faq_agent_tool(
    session: ClinicSession, model: Model | str | None = None
) -> DecoratedFunctionTool:
    """Wrap the FAQ sub-agent as one tool for the Orchestrator.

    The Agent-as-Tool boundary. The Orchestrator sees a tool that takes a
    question in words; the retrieval call and the phrasing of what came
    back happen behind it.

    A fresh sub-agent is built per call rather than held across the
    session, as in the other two sub-agents -- it is given the whole
    question each time and keeps no conversation of its own, so nothing
    accumulates in its context over a long call.

    Args:
        session: The clinic this conversation is pinned to.
        model: Passed to `build_faq_agent`.

    Returns:
        A Strands tool named `faq_assistant`.
    """

    @tool(name="faq_assistant")
    def faq_assistant(request: str) -> str:
        """Answer a question about prices, treatments, preparation or policy.

        Use this for anything the clinic has published about itself that
        is not about the appointment diary: what something costs, what a
        treatment involves, how to prepare for one, or what a policy is.
        It knows only what the clinic has published; it does not know the
        diary, so do not send an availability or booking question here.

        Args:
            request: The patient's question, in their own words or
                lightly cleaned up. It cannot hear the patient itself, so
                pass on anything already established in the conversation
                that changes what is being asked.

        Returns:
            A short answer to read to the patient, or a plain statement
            that the clinic's published information does not cover it.
            It never decides whether that needs a member of staff -- if
            the patient still needs a definite answer, that is yours to
            send to escalation_assistant.
        """
        # Stripped for the reason `scheduling_assistant` strips: an
        # `AgentResult` renders with a trailing newline, and this string
        # is read out loud rather than printed.
        return str(build_faq_agent(session, model)(request)).strip()

    return faq_assistant
