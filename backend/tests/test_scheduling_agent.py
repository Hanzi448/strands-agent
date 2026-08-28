"""Tests for the Scheduling sub-agent and the tools it is built from.

Three properties carry the weight.

*The model is never offered a clinic.* Every assertion about tenancy here
is about the tool *schema* rather than about a guard: `clinic_id` is not
a parameter of anything the model can see, so a model cannot pass the
wrong one and a prompt-injected "use the other clinic" has nothing to
bind to (`architecture.md` -> Invariants #1). The same session's
`clinic_id` is then asserted to be what actually reached DynamoDB.

*The wrappers decide nothing.* Each one is checked against the tool-layer
function called directly with the same arguments, so a rule that started
to drift into the agent layer shows up as a disagreement between the two
(`architecture.md` -> Invariants #3).

*Agent-as-Tool really is wired up.* The last section drives the whole
path with a scripted model -- a tool call goes in, the tool layer runs
against fake tables, and the sub-agent's answer comes back as the string
the Orchestrator will read. Nothing here reaches Bedrock.

The clinic fixtures and table fakes are the ones the tool suites use,
imported rather than restated so the suites cannot drift apart.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterable
from pathlib import Path
from typing import Any

import pytest
from strands.handlers import null_callback_handler
from strands.models.model import Model

from agents.results import INTERNAL_FAILURE_MESSAGE
from agents.scheduling_agent import (
    SCHEDULING_SYSTEM_PROMPT,
    build_scheduling_agent,
    scheduling_agent_tool,
    scheduling_tools,
)
from agents.session import ClinicSession
from tests.test_appointments import (
    NAME,
    NINE,
    NINE_FIFTEEN,
    NOW,
    PHONE,
    FakeAppointmentStore,
    booked,
    patient,
)
from tests.test_booking import FakePatientsTable
from tests.test_scheduling import (
    COSMETIC_ID,
    DENTAL_ID,
    FakeClinicsTable,
    cosmetic_clinic,
    dental_clinic,
)
from tools import appointments, booking, patients, scheduling
from tools.schema import AppointmentAttrs, RescheduleActor

# 2026-07-01 is a Wednesday in British Summer Time, so the dental clinic's
# 09:00 local is 08:00Z -- the offset is visible in the assertions rather
# than accidentally an identity.
WEDNESDAY = "2026-07-01"
TEN = "2026-07-01T09:00:00Z"

TOOL_NAMES = [
    "check_availability",
    "book_appointment",
    "reschedule_appointment",
    "cancel_appointment",
]


class WritableAppointmentStore(FakeAppointmentStore):
    """The change suite's store, plus the `put_item` a booking needs.

    One store for all four tools, because they share one table: a
    booking made through the agent has to be visible to the availability
    check that runs next.
    """

    def __init__(self, *items: dict[str, Any]) -> None:
        super().__init__(*items)
        self.puts: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        self.items.append(dict(kwargs["Item"]))
        return {}


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch):
    """Point every table the scheduling tools reach at a fake.

    All four tool-layer modules are patched, because the agent layer owns
    no query of its own -- which is the property being protected.
    """

    def install(
        *,
        appointment_items: list[dict[str, Any]] | None = None,
        patient_items: list[dict[str, Any]] | None = None,
        clinics: FakeClinicsTable | None = None,
    ) -> tuple[FakeClinicsTable, WritableAppointmentStore, FakePatientsTable]:
        clinics = clinics or FakeClinicsTable(dental_clinic(), cosmetic_clinic())
        store = WritableAppointmentStore(*(appointment_items or []))
        patients_fake = FakePatientsTable(*(patient_items or []))
        monkeypatch.setattr(scheduling, "clinics_table", lambda: clinics)
        monkeypatch.setattr(scheduling, "appointments_table", lambda: store)
        monkeypatch.setattr(booking, "appointments_table", lambda: store)
        monkeypatch.setattr(appointments, "appointments_table", lambda: store)
        monkeypatch.setattr(patients, "patients_table", lambda: patients_fake)
        # "Upcoming" is relative to now, and a suite whose fixtures fell
        # into the past would stop testing anything.
        monkeypatch.setattr(appointments, "utc_now_iso", lambda: NOW)
        monkeypatch.setattr(booking, "utc_now_iso", lambda: NOW)
        monkeypatch.setattr(patients, "utc_now_iso", lambda: NOW)
        return clinics, store, patients_fake

    return install


def dental_session() -> ClinicSession:
    return ClinicSession(clinic_id=DENTAL_ID, clinic=dental_clinic())


def cosmetic_session() -> ClinicSession:
    return ClinicSession(clinic_id=COSMETIC_ID, clinic=cosmetic_clinic())


def tool_named(session: ClinicSession, name: str):
    return next(item for item in scheduling_tools(session) if item.tool_name == name)


def schema(session: ClinicSession, name: str) -> dict[str, Any]:
    return tool_named(session, name).tool_spec["inputSchema"]["json"]


def one_checkup() -> list[dict[str, Any]]:
    """Dana has a single 09:00 check-up coming up at the dental clinic."""
    return [booked("apt_one", NINE, NINE_FIFTEEN)]


# --------------------------------------------------------------------------
# The tenant boundary, enforced by shape
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_no_tool_offers_the_model_a_clinic(name: str) -> None:
    """The whole tenancy argument for this layer: a model cannot pass a
    clinic it was never shown, so there is no guard here to forget."""
    properties = schema(dental_session(), name)["properties"]
    assert "clinic_id" not in properties
    assert not [key for key in properties if "clinic" in key.lower()]


def test_the_four_tools_are_all_that_is_exposed() -> None:
    """Anything else the tool layer can do -- raising an escalation, for
    one -- belongs to another sub-agent, not to this one."""
    assert [item.tool_name for item in scheduling_tools(dental_session())] == TOOL_NAMES


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_every_tool_describes_itself_to_the_model(name: str) -> None:
    """`code-standards.md`: the docstring is what the model sees, and a
    tool with an undescribed argument is one it will guess at."""
    spec = tool_named(dental_session(), name).tool_spec
    assert len(spec["description"]) > 200
    assert all(
        field.get("description")
        for field in spec["inputSchema"]["json"]["properties"].values()
    )


def test_the_session_clinic_is_what_reaches_dynamodb(tables) -> None:
    clinics, _, _ = tables()
    tool_named(dental_session(), "check_availability")(
        date=WEDNESDAY, service="checkup"
    )
    assert clinics.requested == [{"clinic_id": DENTAL_ID}]


def test_a_second_session_cannot_reach_the_first_clinic(tables) -> None:
    """Two callers, two clinics, one process. The tools are values bound
    to a session, not module state (`code-standards.md` -> Python)."""
    clinics, _, _ = tables()
    dental_check = tool_named(dental_session(), "check_availability")
    cosmetic_check = tool_named(cosmetic_session(), "check_availability")

    cosmetic_check(date=WEDNESDAY, service="consult")
    dental_check(date=WEDNESDAY, service="checkup")

    assert clinics.requested == [{"clinic_id": COSMETIC_ID}, {"clinic_id": DENTAL_ID}]


def test_a_clinic_the_model_invents_is_not_an_argument(tables) -> None:
    """Passing `clinic_id` is a `TypeError`, not a silently honoured
    override -- the failure mode this design exists to make impossible."""
    tables()
    with pytest.raises(TypeError):
        tool_named(dental_session(), "check_availability")(
            clinic_id=COSMETIC_ID, date=WEDNESDAY, service="checkup"
        )


def test_the_tool_layer_still_does_not_know_strands_exists() -> None:
    """`architecture.md` -> System Boundaries: `backend/tools/` stays
    callable from a Lambda, a seed script or a test with no agent runtime
    present. This package is the first thing that could break that, by
    tempting a `@tool` decorator one module too far down.
    """
    offenders = [
        module.name
        for module in Path(scheduling.__file__).parent.glob("*.py")
        if re.search(
            r"^\s*(from|import)\s+(strands|bedrock_agentcore)([.\s]|$)",
            module.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    ]
    assert offenders == []


# --------------------------------------------------------------------------
# The wrappers decide nothing
# --------------------------------------------------------------------------


def test_availability_matches_the_tool_layer_called_directly(tables) -> None:
    tables(appointment_items=one_checkup())
    through_agent = tool_named(dental_session(), "check_availability")(
        date=WEDNESDAY, service="checkup", days=3
    )
    direct = scheduling.check_availability(
        clinic_id=DENTAL_ID, date=WEDNESDAY, service="checkup", days=3
    )
    assert through_agent == direct
    assert through_agent["slots"]


def test_a_result_survives_the_json_dump_strands_gives_the_model(tables) -> None:
    """Strands serialises a tool's return value with `json.dumps` and
    falls back to `repr` when that fails -- which would hand a speech
    model `Decimal('15')` to read out."""
    tables(appointment_items=one_checkup())
    result = tool_named(dental_session(), "check_availability")(
        date=WEDNESDAY, service="cleaning"
    )
    assert "Decimal" not in json.dumps(result)


def test_the_two_clinics_answer_the_same_question_differently(tables) -> None:
    """The multi-tenant claim, through the agent surface."""
    tables()
    dental = tool_named(dental_session(), "check_availability")(
        date=WEDNESDAY, service="checkup"
    )
    cosmetic = tool_named(cosmetic_session(), "check_availability")(
        date=WEDNESDAY, service="consult"
    )
    assert dental["slots"][0]["local_start"] == "09:00"
    assert cosmetic["slots"][0]["local_start"] == "10:00"
    assert dental["service"]["duration_minutes"] == 15
    assert cosmetic["service"]["duration_minutes"] == 60


def test_booking_through_the_agent_writes_one_appointment(tables) -> None:
    _, store, patients_fake = tables()
    result = tool_named(dental_session(), "book_appointment")(
        starts_at="2026-07-01T08:00:00Z",
        service="checkup",
        patient_name=NAME,
        patient_phone="555 123 4567",
        notes="Front tooth is sensitive",
    )
    assert result["status"] == "scheduled"
    assert result["local_start"] == "09:00"
    assert len(store.puts) == 1
    assert store.puts[0]["Item"][AppointmentAttrs.CLINIC_ID] == DENTAL_ID
    assert len(patients_fake.puts) == 1


def test_rescheduling_through_the_agent_moves_the_appointment(tables) -> None:
    _, store, _ = tables(
        appointment_items=one_checkup(), patient_items=[patient()]
    )
    result = tool_named(dental_session(), "reschedule_appointment")(
        patient_phone=PHONE,
        patient_name=NAME,
        new_starts_at=TEN,
        reason="Patient asked to move it",
    )
    assert result["previous"]["local_start"] == "09:00"
    assert result["local_start"] == "10:00"
    assert store.stored("apt_one")[AppointmentAttrs.STARTS_AT] == TEN


def test_cancelling_through_the_agent_frees_the_slot(tables) -> None:
    _, store, _ = tables(
        appointment_items=one_checkup(), patient_items=[patient()]
    )
    result = tool_named(dental_session(), "cancel_appointment")(
        patient_phone=PHONE, patient_name=NAME, reason="No longer needed"
    )
    assert result["status"] == "cancelled"
    assert store.stored("apt_one")[AppointmentAttrs.STATUS] == "cancelled"


@pytest.mark.parametrize("name", ["reschedule_appointment", "cancel_appointment"])
def test_the_model_cannot_claim_a_change_was_made_by_staff(name: str, tables) -> None:
    """`actor` is what the dashboard reads to show which moves the agent
    made unprompted, so it is not a value the model gets to choose."""
    _, store, _ = tables(
        appointment_items=one_checkup(), patient_items=[patient()]
    )
    assert "actor" not in schema(dental_session(), name)["properties"]

    extra = {"new_starts_at": TEN} if name == "reschedule_appointment" else {}
    tool_named(dental_session(), name)(
        patient_phone=PHONE, patient_name=NAME, **extra
    )
    entry = store.stored("apt_one")[AppointmentAttrs.RESCHEDULE_HISTORY][-1]
    assert entry["actor"] == RescheduleActor.AGENT.value


# --------------------------------------------------------------------------
# What a refusal looks like to the model
# --------------------------------------------------------------------------


def test_an_unknown_service_comes_back_as_an_error_naming_the_real_ones(
    tables,
) -> None:
    """A validation failure the patient can answer: the tool layer's
    message lists what the clinic does offer, so it is passed through."""
    tables()
    result = tool_named(dental_session(), "check_availability")(
        date=WEDNESDAY, service="teeth whitening"
    )
    assert result["status"] == "error"
    assert "Check-up" in result["content"][0]["text"]


def test_a_taken_slot_comes_back_as_an_error_naming_alternatives(tables) -> None:
    """The case that decides whether a patient is offered another time or
    told to start over."""
    tables(appointment_items=one_checkup())
    result = tool_named(dental_session(), "book_appointment")(
        starts_at=NINE,
        service="checkup",
        patient_name="Kit Rowe",
        patient_phone="555 999 0000",
    )
    assert result["status"] == "error"
    assert "09:15" in result["content"][0]["text"]


def test_a_caller_with_nothing_booked_gets_a_refusal_not_a_crash(tables) -> None:
    tables()
    result = tool_named(dental_session(), "cancel_appointment")(
        patient_phone=PHONE, patient_name=NAME
    )
    assert result["status"] == "error"


def test_a_broken_clinic_config_never_reaches_the_patient(tables) -> None:
    """A `ConfigurationError` quotes internal attribute paths. The model
    is told to stop and hand over instead."""
    broken = dental_clinic() | {"slot_minutes": 0}
    tables(clinics=FakeClinicsTable(broken))
    result = tool_named(dental_session(), "check_availability")(
        date=WEDNESDAY, service="checkup"
    )
    assert result == {
        "status": "error",
        "content": [{"text": INTERNAL_FAILURE_MESSAGE}],
    }
    assert "slot_minutes" not in result["content"][0]["text"]


# --------------------------------------------------------------------------
# The agent itself
# --------------------------------------------------------------------------


def test_the_agent_holds_exactly_the_four_tools() -> None:
    assert sorted(build_scheduling_agent(dental_session()).tool_names) == sorted(
        TOOL_NAMES
    )


def test_the_system_prompt_carries_this_clinics_context() -> None:
    agent = build_scheduling_agent(dental_session())
    assert dental_session().describe() in agent.system_prompt
    assert "Bright Smile Dental" in agent.system_prompt


def test_the_prompt_forbids_the_two_things_that_break_a_voice_call() -> None:
    """Quoting a time that was never checked, and reading a UTC timestamp
    out loud to a patient in London."""
    prompt = " ".join(SCHEDULING_SYSTEM_PROMPT.lower().split())
    assert "never say a time is free unless check_availability returned it" in prompt
    assert "never say a starts_at value out loud" in prompt


def test_the_sub_agent_does_not_print_to_stdout() -> None:
    """Its answer is a return value for the Orchestrator; in AgentCore
    stdout is the log, not the patient's ear."""
    assert build_scheduling_agent(dental_session()).callback_handler is (
        null_callback_handler
    )


# --------------------------------------------------------------------------
# Agent-as-Tool, end to end
# --------------------------------------------------------------------------


class ScriptedModel(Model):
    """A model that plays a fixed script, so the loop can run offline.

    Each turn is either `("tool", (name, args))` or `("text", answer)`.
    Emits the Bedrock-shaped stream events Strands parses, so the event
    loop, the tool executor and the decorator all run for real -- the
    only thing replaced is the model's judgement.
    """

    def __init__(self, *turns: tuple[str, Any]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def update_config(self, **_: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {}

    def structured_output(self, *_: Any, **__: Any) -> Any:
        raise NotImplementedError

    async def stream(
        self,
        messages: Any,
        tool_specs: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[dict[str, Any]]:
        self.requests.append(
            {
                "messages": messages,
                "system_prompt": system_prompt,
                "tool_names": [spec["name"] for spec in (tool_specs or [])],
                "tool_specs": tool_specs or [],
            }
        )
        kind, payload = self.turns.pop(0)
        yield {"messageStart": {"role": "assistant"}}
        if kind == "text":
            yield {"contentBlockDelta": {"delta": {"text": payload}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            return
        name, arguments = payload
        yield {
            "contentBlockStart": {
                "start": {"toolUse": {"toolUseId": "call-1", "name": name}}
            }
        }
        yield {
            "contentBlockDelta": {
                "delta": {"toolUse": {"input": json.dumps(arguments)}}
            }
        }
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}

    @staticmethod
    def tool_result(agent_messages: list[dict[str, Any]]) -> dict[str, Any]:
        """The most recent tool result in a finished conversation."""
        for message in reversed(agent_messages):
            for block in message.get("content", []):
                if "toolResult" in block:
                    return block["toolResult"]
        raise AssertionError("no tool result in the conversation")


def test_the_orchestrator_sees_one_tool_taking_words() -> None:
    """Agent-as-Tool: the Orchestrator gets a scheduling assistant, not
    four appointment tools and the rules for sequencing them."""
    wrapper = scheduling_agent_tool(dental_session())
    assert wrapper.tool_name == "scheduling_assistant"
    assert list(wrapper.tool_spec["inputSchema"]["json"]["properties"]) == ["request"]


def test_a_request_runs_the_tool_and_comes_back_as_words(tables) -> None:
    """The whole path: request in, `check_availability` against the fake
    tables, spoken answer out."""
    tables(appointment_items=one_checkup())
    model = ScriptedModel(
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "checkup"})),
        ("text", "We have 9:15 or 10 o'clock on Wednesday."),
    )
    answer = scheduling_agent_tool(dental_session(), model)(
        request="Dana wants a check-up on Wednesday the 1st of July."
    )
    assert answer == "We have 9:15 or 10 o'clock on Wednesday."
    assert model.requests[0]["tool_names"] == TOOL_NAMES
    assert "Bright Smile Dental" in model.requests[0]["system_prompt"]


def test_the_sub_agent_is_handed_local_times_to_speak(tables) -> None:
    """`local_start` is in the tool result the model reads; the 09:00
    slot is gone because it is booked, and 08:00Z is not quoted as 8am."""
    tables(appointment_items=one_checkup())
    model = ScriptedModel(
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "checkup"})),
        ("text", "Quarter past nine is free."),
    )
    agent = build_scheduling_agent(dental_session(), model)
    agent("when is the clinic free")
    result = ScriptedModel.tool_result(agent.messages)
    payload = json.loads(result["content"][0]["text"])
    assert result["status"] == "success"
    assert [slot["local_start"] for slot in payload["slots"]][:2] == ["09:15", "09:30"]


def test_a_booking_made_through_the_sub_agent_reaches_the_table(tables) -> None:
    _, store, _ = tables()
    model = ScriptedModel(
        (
            "tool",
            (
                "book_appointment",
                {
                    "starts_at": "2026-07-01T08:00:00Z",
                    "service": "checkup",
                    "patient_name": NAME,
                    "patient_phone": PHONE,
                },
            ),
        ),
        ("text", "Booked for nine o'clock on Wednesday."),
    )
    answer = scheduling_agent_tool(dental_session(), model)(request="book it")
    assert answer == "Booked for nine o'clock on Wednesday."
    assert len(store.puts) == 1
    assert store.puts[0]["Item"][AppointmentAttrs.CLINIC_ID] == DENTAL_ID


def test_a_refusal_reaches_the_model_as_a_failure(tables) -> None:
    """Not as a success carrying an error message, which is what a model
    reads out to the patient as though it were the answer."""
    tables()
    model = ScriptedModel(
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "whitening"})),
        ("text", "We do not offer that."),
    )
    agent = build_scheduling_agent(dental_session(), model)
    agent("do you do whitening")
    result = ScriptedModel.tool_result(agent.messages)
    assert result["status"] == "error"
    assert "Check-up" in result["content"][0]["text"]


def test_each_call_gets_a_fresh_sub_agent(tables) -> None:
    """Nothing accumulates in its context over a long call: the
    Orchestrator holds the conversation, this does not."""
    tables()
    model = ScriptedModel(("text", "one"), ("text", "two"))
    wrapper = scheduling_agent_tool(dental_session(), model)
    wrapper(request="first")
    wrapper(request="second")
    first, second = model.requests
    assert len(first["messages"]) == len(second["messages"]) == 1
    assert second["messages"][0]["content"][0]["text"] == "second"


def test_a_session_for_the_other_clinic_is_a_different_assistant(tables) -> None:
    """One process, two callers: the tool the Orchestrator holds carries
    its own clinic, so there is no ambient one to get wrong."""
    clinics, _, _ = tables()
    model = ScriptedModel(
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "consult"})),
        ("text", "Ten o'clock or half past."),
    )
    scheduling_agent_tool(cosmetic_session(), model)(request="anything on Wednesday?")
    assert clinics.requested == [{"clinic_id": COSMETIC_ID}]
    assert "Lumiere Aesthetics" in model.requests[0]["system_prompt"]
