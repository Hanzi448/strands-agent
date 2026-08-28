"""Tests for the Escalation sub-agent and the one tool it is built from.

The Scheduling suite's three properties hold here too -- the model is
never offered a clinic, the wrapper decides nothing, and Agent-as-Tool
runs end to end against fake tables -- so they are asserted in the same
shape rather than restated in a new one.

Two properties are this agent's own.

*It can write, and it cannot read.* `tools/escalations.py` has three
staff reads next to `create_escalation`, and a patient-facing agent
holding any of them could read another caller's complaint out loud
(`architecture.md` -> Invariants #5). The surface is asserted to be
exactly one tool, by name, not merely to contain the right one.

*It does not choose who raised it.* `source` is absent from the schema
and `voice` reaches DynamoDB -- the same argument `actor` gets in the
Scheduling suite. The background Lambda is the only thing that writes
`background`, and it calls the tool layer directly.

The clinic fixtures and the `Escalations` fake are the tool suites',
and the `ScriptedModel` is the Scheduling suite's, imported rather than
restated so nothing drifts apart.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from strands.handlers import null_callback_handler

from agents.escalation_agent import (
    ESCALATION_SYSTEM_PROMPT,
    build_escalation_agent,
    escalation_agent_tool,
    escalation_tools,
)
from agents.results import INTERNAL_FAILURE_MESSAGE
from agents.session import ClinicSession
from tests.test_escalations import FakeEscalationsTable
from tests.test_scheduling import (
    COSMETIC_ID,
    DENTAL_ID,
    FakeClinicsTable,
    cosmetic_clinic,
    dental_clinic,
)
from tests.test_scheduling_agent import ScriptedModel
from tools import escalations
from tools.schema import EscalationAttrs, EscalationSource, EscalationStatus

NOW = "2026-07-01T09:00:00Z"

# What a patient actually escalates: a question no tool in this system
# can answer, and none of them is a booking failure.
REASON = (
    "Dana Whitfield (555 123 4567) was charged twice for a cleaning in June"
    " and wants the second charge refunded. Nothing in the diary explains it."
)


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch):
    """Point `escalations_table` at a fake and pin the clock.

    Only the escalations table is patched: this agent reaches one tool
    module, and a test that had to stub more would mean it had grown a
    read it should not have.
    """

    def install(*items: dict[str, Any]) -> FakeEscalationsTable:
        fake = FakeEscalationsTable(*items)
        monkeypatch.setattr(escalations, "escalations_table", lambda: fake)
        monkeypatch.setattr(escalations, "utc_now_iso", lambda: NOW)
        return fake

    return install


def dental_session() -> ClinicSession:
    return ClinicSession(clinic_id=DENTAL_ID, clinic=dental_clinic())


def cosmetic_session() -> ClinicSession:
    return ClinicSession(clinic_id=COSMETIC_ID, clinic=cosmetic_clinic())


def tool_named(session: ClinicSession, name: str):
    return next(item for item in escalation_tools(session) if item.tool_name == name)


def schema(session: ClinicSession, name: str) -> dict[str, Any]:
    return tool_named(session, name).tool_spec["inputSchema"]["json"]


# --------------------------------------------------------------------------
# The surface: one write, and none of the staff reads
# --------------------------------------------------------------------------


def test_the_agent_can_raise_an_escalation_and_do_nothing_else() -> None:
    """The reads in `tools/escalations.py` are the dashboard's. A patient
    on the phone must not be able to reach another caller's complaint."""
    assert [item.tool_name for item in escalation_tools(dental_session())] == [
        "create_escalation"
    ]


@pytest.mark.parametrize(
    "name", ["list_open_escalations", "get_escalation", "resolve_escalation"]
)
def test_no_staff_read_is_wired_into_this_agent(name: str) -> None:
    """Named individually, so adding one back fails a test that says why
    rather than only a count."""
    assert name not in {item.tool_name for item in escalation_tools(dental_session())}


def test_the_model_is_not_offered_a_clinic() -> None:
    """Same argument as every other tool in this package: `clinic_id` is
    closed over, so it is absent from the schema the model is shown
    (`architecture.md` -> Invariants #1)."""
    properties = schema(dental_session(), "create_escalation")["properties"]
    assert "clinic_id" not in properties
    assert not [key for key in properties if "clinic" in key.lower()]


def test_the_model_does_not_choose_who_raised_the_escalation() -> None:
    """`source` records which path wrote the row -- live call or nightly
    scan -- and each path knows its own. Not a model's choice, exactly as
    `actor` is not on `reschedule_appointment`."""
    assert "source" not in schema(dental_session(), "create_escalation")["properties"]


def test_the_tool_describes_itself_to_the_model() -> None:
    """`code-standards.md`: the docstring is what the model sees, and an
    undescribed argument is one it will guess at."""
    spec = tool_named(dental_session(), "create_escalation").tool_spec
    assert len(spec["description"]) > 200
    assert all(
        field.get("description")
        for field in spec["inputSchema"]["json"]["properties"].values()
    )


def test_only_the_reason_is_required() -> None:
    """The back-references are optional on purpose: an escalation raised
    before the caller was identified still has to be recordable."""
    assert schema(dental_session(), "create_escalation")["required"] == ["reason"]


# --------------------------------------------------------------------------
# The wrapper decides nothing
# --------------------------------------------------------------------------


def test_raising_one_writes_the_sessions_clinic_and_the_voice_source(table) -> None:
    fake = table()
    result = tool_named(dental_session(), "create_escalation")(reason=REASON)

    assert len(fake.puts) == 1
    item = fake.puts[0]["Item"]
    assert item[EscalationAttrs.CLINIC_ID] == DENTAL_ID
    assert item[EscalationAttrs.SOURCE] == EscalationSource.VOICE.value
    assert item[EscalationAttrs.STATUS] == EscalationStatus.OPEN.value
    assert item[EscalationAttrs.REASON] == REASON
    assert result == item


def test_the_wrapper_matches_the_tool_layer_called_directly(table) -> None:
    """A rule drifting up into the agent layer shows as a disagreement
    between these two (`architecture.md` -> Invariants #3)."""
    fake = table()
    through_agent = tool_named(dental_session(), "create_escalation")(
        reason=REASON, patient_id="pat_1", appointment_id="apt_1"
    )
    direct = escalations.create_escalation(
        DENTAL_ID, REASON, patient_id="pat_1", appointment_id="apt_1"
    )
    assert {
        key: value
        for key, value in through_agent.items()
        if key != EscalationAttrs.ESCALATION_ID
    } == {
        key: value
        for key, value in direct.items()
        if key != EscalationAttrs.ESCALATION_ID
    }
    # A fresh uuid each time: two calls are two queue items, never one.
    assert (
        through_agent[EscalationAttrs.ESCALATION_ID]
        != direct[EscalationAttrs.ESCALATION_ID]
    )


def test_back_references_are_stored_when_given_and_absent_when_not(table) -> None:
    """Omitted rather than stored as null -- what "not about a particular
    patient" looks like to the dashboard."""
    fake = table()
    create = tool_named(dental_session(), "create_escalation")

    create(reason=REASON)
    create(reason=REASON, patient_id="pat_dana", appointment_id="apt_one")

    bare, referenced = (put["Item"] for put in fake.puts)
    assert EscalationAttrs.PATIENT_ID not in bare
    assert EscalationAttrs.APPOINTMENT_ID not in bare
    assert referenced[EscalationAttrs.PATIENT_ID] == "pat_dana"
    assert referenced[EscalationAttrs.APPOINTMENT_ID] == "apt_one"


def test_a_result_survives_the_json_dump_strands_gives_the_model(table) -> None:
    """Strands serialises a tool result with `json.dumps` and falls back
    to `repr`, which would hand a speech model a `Decimal` to read out."""
    table()
    result = tool_named(dental_session(), "create_escalation")(reason=REASON)
    assert "Decimal" not in json.dumps(result)


def test_a_clinic_the_model_invents_is_not_an_argument(table) -> None:
    """Passing `clinic_id` is a `TypeError`, not a silently honoured
    override."""
    table()
    with pytest.raises(TypeError):
        tool_named(dental_session(), "create_escalation")(
            clinic_id=COSMETIC_ID, reason=REASON
        )


def test_two_sessions_in_one_process_raise_to_their_own_clinics(table) -> None:
    """The tools are values bound to a session, not module state
    (`code-standards.md` -> Python)."""
    fake = table()
    tool_named(cosmetic_session(), "create_escalation")(reason=REASON)
    tool_named(dental_session(), "create_escalation")(reason=REASON)
    assert [put["Item"][EscalationAttrs.CLINIC_ID] for put in fake.puts] == [
        COSMETIC_ID,
        DENTAL_ID,
    ]


# --------------------------------------------------------------------------
# What a refusal looks like to the model
# --------------------------------------------------------------------------


def test_a_blank_reason_is_refused_rather_than_written(table) -> None:
    """An escalation with nothing in it is a card a staff member cannot
    act on, so it is a validation failure the model can answer."""
    fake = table()
    result = tool_named(dental_session(), "create_escalation")(reason="   ")
    assert result["status"] == "error"
    assert "reason" in result["content"][0]["text"]
    assert fake.puts == []


def test_a_failed_write_never_comes_back_as_a_recorded_escalation(
    table, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure that matters most here: if the write did not happen,
    the model must not be told anything was recorded."""
    fake = table()

    def explode(**_: Any) -> dict[str, Any]:
        raise RuntimeError("table unreachable")

    monkeypatch.setattr(fake, "put_item", explode)
    result = tool_named(dental_session(), "create_escalation")(reason=REASON)
    assert result == {
        "status": "error",
        "content": [{"text": INTERNAL_FAILURE_MESSAGE}],
    }
    assert "table unreachable" not in json.dumps(result)


# --------------------------------------------------------------------------
# The agent itself
# --------------------------------------------------------------------------


def test_the_agent_holds_exactly_the_one_tool() -> None:
    assert build_escalation_agent(dental_session()).tool_names == ["create_escalation"]


def test_the_system_prompt_carries_this_clinics_context() -> None:
    agent = build_escalation_agent(dental_session())
    assert dental_session().describe() in agent.system_prompt
    assert "Bright Smile Dental" in agent.system_prompt


def test_the_prompt_forbids_promising_the_thing_was_done() -> None:
    """An escalation is a note asking a human to decide. A patient told
    their refund is approved has been told something untrue."""
    prompt = " ".join(ESCALATION_SYSTEM_PROMPT.lower().split())
    assert "never tell them the thing they asked for has been done" in prompt


def test_the_prompt_forbids_a_second_call_for_one_problem() -> None:
    """`create_escalation` mints a fresh id every time, so a retry is a
    duplicate card and two staff working one case."""
    prompt = " ".join(ESCALATION_SYSTEM_PROMPT.lower().split())
    assert "once, and once only" in prompt


def test_the_prompt_overrides_the_shared_failure_message(table) -> None:
    """`INTERNAL_FAILURE_MESSAGE` tells the model to say staff will follow
    up. True when a booking tool breaks; false here, because the thing
    that records the follow-up is what failed."""
    assert "a member of staff will follow up" in INTERNAL_FAILURE_MESSAGE
    prompt = " ".join(ESCALATION_SYSTEM_PROMPT.lower().split())
    assert (
        "if create_escalation does not succeed, nothing was recorded."
        " do not say a member of staff will follow up." in prompt
    )


def test_the_sub_agent_does_not_print_to_stdout() -> None:
    assert build_escalation_agent(dental_session()).callback_handler is (
        null_callback_handler
    )


# --------------------------------------------------------------------------
# Agent-as-Tool, end to end
# --------------------------------------------------------------------------


def test_the_orchestrator_sees_one_tool_taking_words() -> None:
    wrapper = escalation_agent_tool(dental_session())
    assert wrapper.tool_name == "escalation_assistant"
    assert list(wrapper.tool_spec["inputSchema"]["json"]["properties"]) == ["request"]


def test_a_request_reaches_the_table_and_comes_back_as_words(table) -> None:
    """The whole path: situation in, `create_escalation` against the fake
    table, spoken answer out."""
    fake = table()
    model = ScriptedModel(
        ("tool", ("create_escalation", {"reason": REASON})),
        ("text", "I have passed that to the practice manager, who will call you."),
    )
    answer = escalation_agent_tool(dental_session(), model)(
        request="Dana Whitfield, 555 123 4567, was charged twice and wants a refund."
    )

    assert answer.startswith("I have passed that to the practice manager")
    assert model.requests[0]["tool_names"] == ["create_escalation"]
    assert "Bright Smile Dental" in model.requests[0]["system_prompt"]
    assert len(fake.puts) == 1
    assert fake.puts[0]["Item"][EscalationAttrs.CLINIC_ID] == DENTAL_ID


def test_the_sub_agent_is_handed_an_open_escalation_to_confirm(table) -> None:
    """What the model reads back is an item with `status` open, so it has
    something true to say -- recorded, not resolved."""
    table()
    model = ScriptedModel(
        ("tool", ("create_escalation", {"reason": REASON})),
        ("text", "Recorded for staff."),
    )
    agent = build_escalation_agent(dental_session(), model)
    agent("she wants a refund")
    result = ScriptedModel.tool_result(agent.messages)
    payload = json.loads(result["content"][0]["text"])
    assert result["status"] == "success"
    assert payload[EscalationAttrs.STATUS] == EscalationStatus.OPEN.value
    assert payload[EscalationAttrs.ESCALATION_ID].startswith("esc_")


def test_a_refusal_reaches_the_model_as_a_failure(table) -> None:
    """Not as a success carrying an error message, which is what a model
    reads out to the patient as though the escalation had been filed."""
    fake = table()
    model = ScriptedModel(
        ("tool", ("create_escalation", {"reason": ""})),
        ("text", "I could not record that."),
    )
    agent = build_escalation_agent(dental_session(), model)
    agent("something is wrong")
    assert ScriptedModel.tool_result(agent.messages)["status"] == "error"
    assert fake.puts == []


def test_each_call_gets_a_fresh_sub_agent(table) -> None:
    """Nothing accumulates in its context: the Orchestrator holds the
    conversation, this does not."""
    table()
    model = ScriptedModel(("text", "one"), ("text", "two"))
    wrapper = escalation_agent_tool(dental_session(), model)
    wrapper(request="first")
    wrapper(request="second")
    first, second = model.requests
    assert len(first["messages"]) == len(second["messages"]) == 1
    assert second["messages"][0]["content"][0]["text"] == "second"


def test_a_session_for_the_other_clinic_is_a_different_assistant(table) -> None:
    """One process, two callers: the tool the Orchestrator holds carries
    its own clinic, so there is no ambient one to get wrong."""
    fake = table()
    model = ScriptedModel(
        ("tool", ("create_escalation", {"reason": "Wants a price for filler."})),
        ("text", "A member of staff will call you back."),
    )
    escalation_agent_tool(cosmetic_session(), model)(request="how much is filler?")
    assert fake.puts[0]["Item"][EscalationAttrs.CLINIC_ID] == COSMETIC_ID
    assert "Lumiere Aesthetics" in model.requests[0]["system_prompt"]


def test_the_two_sub_agents_are_separate_surfaces(table) -> None:
    """Invariants #2 and #6 together: the agent that books cannot raise an
    escalation, and the agent that escalates cannot touch the diary. Which
    of the two runs is the Orchestrator's decision, not a model's."""
    from agents.scheduling_agent import scheduling_tools

    table()
    scheduling = {item.tool_name for item in scheduling_tools(dental_session())}
    escalation = {item.tool_name for item in escalation_tools(dental_session())}
    assert scheduling.isdisjoint(escalation)
    assert "create_escalation" not in scheduling
