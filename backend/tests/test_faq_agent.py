"""Tests for the FAQ sub-agent and the one tool it is built from.

The Scheduling and Escalation suites' shared properties hold here too --
the model is never offered a clinic, the wrapper decides nothing, and
Agent-as-Tool runs end to end against a fake Bedrock client -- so they are
asserted in the same shape rather than restated in a new one.

Two properties are this agent's own.

*It answers, and it does not decide to escalate.* `tools/faq.py` returns
`found: False` as an ordinary answer, not a failure, and whose call it is
to raise that to a member of staff belongs to the Orchestrator
(`architecture.md` -> Invariants #2 and #6) -- this agent holds no
`create_escalation` tool and its prompt says so.

*It is told to answer only from what it retrieved.* A model that reasons
from its own knowledge of dentistry or cosmetics is exactly the failure
`scheduling_agent`'s "never reason about opening hours yourself" rule
guards against one layer over -- pinned here as a phrase in the prompt.

The clinic fixtures are the tool suites', the fake Bedrock client is
`test_faq.py`'s, and the `ScriptedModel` is the Scheduling suite's,
imported rather than restated so nothing drifts apart.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from strands.handlers import null_callback_handler

from agents.faq_agent import (
    FAQ_SYSTEM_PROMPT,
    build_faq_agent,
    faq_agent_tool,
    faq_tools,
)
from agents.results import INTERNAL_FAILURE_MESSAGE
from agents.session import ClinicSession
from tests.test_faq import COSMETIC_KB_ENV, DENTAL_KB_ENV, FakeBedrockAgentRuntimeClient
from tests.test_scheduling import (
    COSMETIC_ID,
    DENTAL_ID,
    cosmetic_clinic,
    dental_clinic,
)
from tests.test_scheduling_agent import ScriptedModel
from tools import faq
from tools.errors import ConfigurationError

QUESTION = "How much does a cleaning cost, and do I need to do anything beforehand?"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run each test against an unconfigured process, whatever the shell has."""
    monkeypatch.delenv(DENTAL_KB_ENV, raising=False)
    monkeypatch.delenv(COSMETIC_KB_ENV, raising=False)
    faq._bedrock_agent_runtime_client.cache_clear()


@pytest.fixture
def kb(monkeypatch: pytest.MonkeyPatch):
    """Point `tools/faq.py` at a fake Bedrock client and give the dental
    clinic a Knowledge Base id.

    Only the Bedrock client is patched: this agent reaches one tool
    module, and a test that had to stub more would mean it had grown a
    read it should not have.
    """

    def install(*passages: str) -> FakeBedrockAgentRuntimeClient:
        fake = FakeBedrockAgentRuntimeClient(*passages)
        monkeypatch.setattr(faq, "_bedrock_agent_runtime_client", lambda: fake)
        monkeypatch.setenv(DENTAL_KB_ENV, "kb-dental-123")
        return fake

    return install


def dental_session() -> ClinicSession:
    return ClinicSession(clinic_id=DENTAL_ID, clinic=dental_clinic())


def cosmetic_session() -> ClinicSession:
    return ClinicSession(clinic_id=COSMETIC_ID, clinic=cosmetic_clinic())


def tool_named(session: ClinicSession, name: str):
    return next(item for item in faq_tools(session) if item.tool_name == name)


def schema(session: ClinicSession, name: str) -> dict[str, Any]:
    return tool_named(session, name).tool_spec["inputSchema"]["json"]


# --------------------------------------------------------------------------
# The surface: one read, and nothing that decides to escalate
# --------------------------------------------------------------------------


def test_the_agent_can_query_the_kb_and_do_nothing_else() -> None:
    assert [item.tool_name for item in faq_tools(dental_session())] == ["query_faq"]


def test_it_holds_no_escalation_tool() -> None:
    """It never decides to raise something to staff -- that call belongs
    to the Orchestrator (`architecture.md` -> Invariants #2 and #6)."""
    assert "create_escalation" not in {
        item.tool_name for item in faq_tools(dental_session())
    }


def test_the_model_is_not_offered_a_clinic() -> None:
    properties = schema(dental_session(), "query_faq")["properties"]
    assert "clinic_id" not in properties
    assert not [key for key in properties if "clinic" in key.lower()]


def test_the_tool_describes_itself_to_the_model() -> None:
    spec = tool_named(dental_session(), "query_faq").tool_spec
    assert len(spec["description"]) > 200
    assert all(
        field.get("description")
        for field in spec["inputSchema"]["json"]["properties"].values()
    )


def test_only_the_question_is_required() -> None:
    assert schema(dental_session(), "query_faq")["required"] == ["question"]


# --------------------------------------------------------------------------
# The wrapper decides nothing
# --------------------------------------------------------------------------


def test_the_wrapper_matches_the_tool_layer_called_directly(kb) -> None:
    """A rule drifting up into the agent layer shows as a disagreement
    between these two (`architecture.md` -> Invariants #3)."""
    kb("A cleaning takes about 30 minutes and costs £60.")
    through_agent = tool_named(dental_session(), "query_faq")(question=QUESTION)
    direct = faq.query_faq(DENTAL_ID, QUESTION)
    assert through_agent == direct


def test_max_results_is_forwarded(kb) -> None:
    fake = kb("A cleaning costs £60.")
    tool_named(dental_session(), "query_faq")(question=QUESTION, max_results=7)
    search_config = fake.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert search_config["numberOfResults"] == 7


def test_a_result_survives_the_json_dump_strands_gives_the_model(kb) -> None:
    kb("A cleaning costs £60.")
    result = tool_named(dental_session(), "query_faq")(question=QUESTION)
    assert "Decimal" not in json.dumps(result)


def test_a_clinic_the_model_invents_is_not_an_argument(kb) -> None:
    kb("A cleaning costs £60.")
    with pytest.raises(TypeError):
        tool_named(dental_session(), "query_faq")(
            clinic_id=COSMETIC_ID, question=QUESTION
        )


def test_two_sessions_in_one_process_query_their_own_clinic(
    kb, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tools are values bound to a session, not module state
    (`code-standards.md` -> Python) -- each session's tool asks for its
    own clinic's Knowledge Base id, on the one shared Bedrock client."""
    fake = kb("Dental: a cleaning costs £60.")
    monkeypatch.setenv(COSMETIC_KB_ENV, "kb-cosmetic-456")

    tool_named(cosmetic_session(), "query_faq")(question="How much is filler?")
    tool_named(dental_session(), "query_faq")(question="How much is a cleaning?")

    assert [call["knowledgeBaseId"] for call in fake.calls] == [
        "kb-cosmetic-456",
        "kb-dental-123",
    ]


# --------------------------------------------------------------------------
# What a refusal looks like to the model
# --------------------------------------------------------------------------


def test_a_blank_question_is_refused_rather_than_queried(kb) -> None:
    fake = kb("A cleaning costs £60.")
    result = tool_named(dental_session(), "query_faq")(question="   ")
    assert result["status"] == "error"
    assert "question" in result["content"][0]["text"]
    assert fake.calls == []


def test_an_unconfigured_clinic_reaches_the_model_as_the_shared_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Knowledge Base id set is a deployment fault, exactly like the
    broken clinic configs the other two sub-agents' suites cover -- not
    the patient's business, and not a "no match" answer."""
    fake = FakeBedrockAgentRuntimeClient("unreachable")
    monkeypatch.setattr(faq, "_bedrock_agent_runtime_client", lambda: fake)
    result = tool_named(dental_session(), "query_faq")(question=QUESTION)
    assert result == {
        "status": "error",
        "content": [{"text": INTERNAL_FAILURE_MESSAGE}],
    }
    assert fake.calls == []


def test_a_failed_retrieval_never_comes_back_as_found(
    kb, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = kb("A cleaning costs £60.")

    def explode(**_: Any) -> dict[str, Any]:
        raise RuntimeError("bedrock unreachable")

    monkeypatch.setattr(fake, "retrieve", explode)
    result = tool_named(dental_session(), "query_faq")(question=QUESTION)
    assert result == {
        "status": "error",
        "content": [{"text": INTERNAL_FAILURE_MESSAGE}],
    }
    assert "bedrock unreachable" not in json.dumps(result)


# --------------------------------------------------------------------------
# The agent itself
# --------------------------------------------------------------------------


def test_the_agent_holds_exactly_the_one_tool() -> None:
    assert build_faq_agent(dental_session()).tool_names == ["query_faq"]


def test_the_system_prompt_carries_this_clinics_context() -> None:
    agent = build_faq_agent(dental_session())
    assert dental_session().describe() in agent.system_prompt
    assert "Bright Smile Dental" in agent.system_prompt


def test_the_prompt_forbids_answering_from_its_own_knowledge() -> None:
    prompt = " ".join(FAQ_SYSTEM_PROMPT.lower().split())
    assert "never use your own general" in prompt


def test_the_prompt_says_no_match_is_answered_plainly() -> None:
    prompt = " ".join(FAQ_SYSTEM_PROMPT.lower().split())
    assert "say plainly that you do not have that information" in prompt


def test_the_prompt_says_it_does_not_decide_to_escalate() -> None:
    prompt = " ".join(FAQ_SYSTEM_PROMPT.lower().split())
    assert "you do not decide whether something needing a person gets escalated" in (
        prompt
    )


def test_the_sub_agent_does_not_print_to_stdout() -> None:
    assert build_faq_agent(dental_session()).callback_handler is null_callback_handler


# --------------------------------------------------------------------------
# Agent-as-Tool, end to end
# --------------------------------------------------------------------------


def test_the_orchestrator_sees_one_tool_taking_words() -> None:
    wrapper = faq_agent_tool(dental_session())
    assert wrapper.tool_name == "faq_assistant"
    assert list(wrapper.tool_spec["inputSchema"]["json"]["properties"]) == ["request"]


def test_a_question_reaches_the_kb_and_comes_back_as_words(kb) -> None:
    """The whole path: question in, `query_faq` against the fake Bedrock
    client, spoken answer out."""
    fake = kb("A cleaning takes about 30 minutes and costs £60.")
    model = ScriptedModel(
        ("tool", ("query_faq", {"question": QUESTION})),
        ("text", "A cleaning is about £60 and takes half an hour."),
    )
    answer = faq_agent_tool(dental_session(), model)(request=QUESTION)

    assert answer == "A cleaning is about £60 and takes half an hour."
    assert model.requests[0]["tool_names"] == ["query_faq"]
    assert "Bright Smile Dental" in model.requests[0]["system_prompt"]
    assert fake.calls[0]["knowledgeBaseId"] == "kb-dental-123"


def test_no_match_is_handed_back_as_words_not_a_failure(kb) -> None:
    kb()
    model = ScriptedModel(
        ("tool", ("query_faq", {"question": "Do you offer valet parking?"})),
        ("text", "I do not have that information, sorry."),
    )
    answer = faq_agent_tool(dental_session(), model)(
        request="Do you offer valet parking?"
    )
    assert "do not have that information" in answer


def test_a_refusal_reaches_the_model_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Knowledge Base id set reaches the sub-agent's model as
    `status: error`, not as an ordinary "nothing found" answer."""
    fake = FakeBedrockAgentRuntimeClient("unreachable")
    monkeypatch.setattr(faq, "_bedrock_agent_runtime_client", lambda: fake)
    model = ScriptedModel(
        ("tool", ("query_faq", {"question": QUESTION})),
        ("text", "I cannot look that up right now."),
    )
    agent = build_faq_agent(dental_session(), model)
    agent(QUESTION)
    assert ScriptedModel.tool_result(agent.messages)["status"] == "error"


def test_each_call_gets_a_fresh_sub_agent(kb) -> None:
    """Nothing accumulates in its context: the Orchestrator holds the
    conversation, this does not."""
    kb("A cleaning costs £60.")
    model = ScriptedModel(("text", "one"), ("text", "two"))
    wrapper = faq_agent_tool(dental_session(), model)
    wrapper(request="first")
    wrapper(request="second")
    first, second = model.requests
    assert len(first["messages"]) == len(second["messages"]) == 1
    assert second["messages"][0]["content"][0]["text"] == "second"


def test_a_session_for_the_other_clinic_queries_its_own_kb(
    kb, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One process, two callers: the tool the Orchestrator holds carries
    its own clinic, so there is no ambient one to get wrong."""
    fake = kb("Cosmetic: filler costs £250.")
    monkeypatch.setenv(COSMETIC_KB_ENV, "kb-cosmetic-456")

    model = ScriptedModel(
        ("tool", ("query_faq", {"question": "How much is filler?"})),
        ("text", "Filler is £250."),
    )
    faq_agent_tool(cosmetic_session(), model)(request="How much is filler?")
    assert fake.calls[0]["knowledgeBaseId"] == "kb-cosmetic-456"
    assert "Lumiere Aesthetics" in model.requests[0]["system_prompt"]


def test_the_three_sub_agents_are_separate_surfaces(kb) -> None:
    """Invariants #2 and #6 together: no tool set overlaps another's, and
    which of the three runs is the Orchestrator's decision, not a model's."""
    from agents.escalation_agent import escalation_tools
    from agents.scheduling_agent import scheduling_tools

    kb("A cleaning costs £60.")
    scheduling = {item.tool_name for item in scheduling_tools(dental_session())}
    escalation = {item.tool_name for item in escalation_tools(dental_session())}
    faq_names = {item.tool_name for item in faq_tools(dental_session())}
    assert faq_names.isdisjoint(scheduling)
    assert faq_names.isdisjoint(escalation)
    assert "query_faq" not in scheduling
    assert "query_faq" not in escalation
