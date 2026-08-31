"""Tests for the Orchestrator -- the agent a patient actually talks to.

The sub-agent suites proved that each assistant does its own job. This
one is about the layer above, and four properties carry it.

*It cannot do anything itself.* Its whole tool surface is the two
Agent-as-Tool wrappers. No `backend/tools/` function is reachable from
it, so there is no path by which the front desk books an appointment or
writes an escalation without an assistant in between
(`architecture.md` -> Invariants #2 and #3). That is asserted by name,
not by a count.

*It is the one thing that remembers.* A sub-agent is rebuilt per call and
keeps nothing; this agent accumulates `messages` across turns. The pair
of assertions is the division of labour: the patient's thread of talk in
one place, and the multi-turn dance a booking takes out of it.

*Routing really reaches the clinic's data.* The last section drives whole
calls with one scripted model standing in for all three agents -- patient
turn in, the Orchestrator calls an assistant, the assistant calls the
tool layer against fake tables, and an answer comes back out. Two of them
end in a row written to DynamoDB. Nothing here reaches Bedrock.

*A clinic is never chosen by a model.* `start_call` is the only entry
point, it validates before the greeting, and the clinic it read is what
reaches the tables two agent layers down.

One `ScriptedModel` serves the whole tree, because `build_orchestrator`
threads one model into both sub-agents -- so its script is the turns of
all three agents interleaved in the order they actually run, and a
routing change shows up as a script that no longer fits.

Every fixture, fake and scripted model is imported from the suite that
already owns it, so nothing can drift.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from strands.handlers import null_callback_handler

from agents.orchestrator import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    build_orchestrator,
    orchestrator_tools,
    start_call,
)
from agents.results import INTERNAL_FAILURE_MESSAGE
from agents.session import ClinicSession
from tests.test_appointments import NAME, NINE, NINE_FIFTEEN, PHONE, booked
from tests.test_booking import FakePatientsTable
from tests.test_escalation_agent import REASON
from tests.test_escalations import FakeEscalationsTable
from tests.test_faq import DENTAL_KB_ENV, FakeBedrockAgentRuntimeClient
from tests.test_scheduling import (
    COSMETIC_ID,
    DENTAL_ID,
    FakeClinicsTable,
    cosmetic_clinic,
    dental_clinic,
)
from tests.test_scheduling_agent import (
    TOOL_NAMES as SCHEDULING_TOOL_NAMES,
    WEDNESDAY,
    ScriptedModel,
    WritableAppointmentStore,
)
from tools import appointments, booking, escalations, faq, patients, scheduling
from tools.errors import ConfigurationError, NotFoundError, ValidationError
from tools.schema import AppointmentAttrs, EscalationAttrs, EscalationSource

ASSISTANTS = ["scheduling_assistant", "faq_assistant", "escalation_assistant"]

NOW = "2026-06-30T09:00:00Z"


@pytest.fixture(autouse=True)
def clean_faq_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run each test against an unconfigured Knowledge Base, whatever the
    shell has -- the same isolation `test_faq.py` gives `query_faq`
    itself."""
    monkeypatch.delenv(DENTAL_KB_ENV, raising=False)
    faq._bedrock_agent_runtime_client.cache_clear()


@pytest.fixture
def faq_kb(monkeypatch: pytest.MonkeyPatch):
    """Point `tools/faq.py` at a fake Bedrock client and give the dental
    clinic a Knowledge Base id -- separate from `tables()` because it is
    a different tool module, reached only through `faq_assistant`."""

    def install(*passages: str) -> FakeBedrockAgentRuntimeClient:
        fake = FakeBedrockAgentRuntimeClient(*passages)
        monkeypatch.setattr(faq, "_bedrock_agent_runtime_client", lambda: fake)
        monkeypatch.setenv(DENTAL_KB_ENV, "kb-dental-123")
        return fake

    return install


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch):
    """Point every table any agent in the tree can reach at a fake.

    All five tool modules, because the Orchestrator's reach is the union
    of its sub-agents' -- and a call that got through to a real table is
    exactly what this suite would otherwise fail to notice.
    """

    def install(
        *,
        appointment_items: list[dict[str, Any]] | None = None,
        patient_items: list[dict[str, Any]] | None = None,
        clinics: FakeClinicsTable | None = None,
    ) -> tuple[
        FakeClinicsTable,
        WritableAppointmentStore,
        FakePatientsTable,
        FakeEscalationsTable,
    ]:
        clinics = clinics or FakeClinicsTable(dental_clinic(), cosmetic_clinic())
        store = WritableAppointmentStore(*(appointment_items or []))
        patients_fake = FakePatientsTable(*(patient_items or []))
        escalations_fake = FakeEscalationsTable()
        monkeypatch.setattr(scheduling, "clinics_table", lambda: clinics)
        monkeypatch.setattr(scheduling, "appointments_table", lambda: store)
        monkeypatch.setattr(booking, "appointments_table", lambda: store)
        monkeypatch.setattr(appointments, "appointments_table", lambda: store)
        monkeypatch.setattr(patients, "patients_table", lambda: patients_fake)
        monkeypatch.setattr(escalations, "escalations_table", lambda: escalations_fake)
        for module in (appointments, booking, patients, escalations):
            monkeypatch.setattr(module, "utc_now_iso", lambda: NOW)
        return clinics, store, patients_fake, escalations_fake

    return install


def dental_session() -> ClinicSession:
    return ClinicSession(clinic_id=DENTAL_ID, clinic=dental_clinic())


def cosmetic_session() -> ClinicSession:
    return ClinicSession(clinic_id=COSMETIC_ID, clinic=cosmetic_clinic())


def tool_named(session: ClinicSession, name: str):
    return next(item for item in orchestrator_tools(session) if item.tool_name == name)


def one_checkup() -> list[dict[str, Any]]:
    """Dana has a single 09:00 check-up coming up at the dental clinic."""
    return [booked("apt_one", NINE, NINE_FIFTEEN)]


def prompt_text() -> str:
    """The system prompt as one lowercase line, for phrase assertions."""
    return " ".join(ORCHESTRATOR_SYSTEM_PROMPT.lower().split())


def system_prompts(model: ScriptedModel) -> list[str]:
    """Which agent made each request, in order, by its opening line."""
    return [request["system_prompt"] for request in model.requests]


# --------------------------------------------------------------------------
# The surface: two assistants, and nothing of its own
# --------------------------------------------------------------------------


def test_the_front_desk_holds_exactly_the_two_assistants() -> None:
    """Agent-as-Tool at the top of the tree. Anything else added here is
    a rule leaving `backend/tools/` for an agent definition."""
    assert [item.tool_name for item in orchestrator_tools(dental_session())] == (
        ASSISTANTS
    )
    assert build_orchestrator(dental_session()).tool_names == ASSISTANTS


@pytest.mark.parametrize(
    "name",
    [
        *SCHEDULING_TOOL_NAMES,
        "create_escalation",
        "find_upcoming_appointments",
        "query_faq",
    ],
)
def test_no_tool_layer_function_is_reachable_from_the_front_desk(name: str) -> None:
    """Named individually, so wiring one up fails a test that says why.
    The Orchestrator asks for a booking; it never writes one
    (`architecture.md` -> Invariants #3)."""
    assert name not in build_orchestrator(dental_session()).tool_names


@pytest.mark.parametrize("name", ASSISTANTS)
def test_an_assistant_takes_words_and_nothing_else(name: str) -> None:
    """The Orchestrator's job is to say what is wanted, not to fill in a
    booking form: one free-text argument is the whole boundary."""
    assert list(
        tool_named(dental_session(), name).tool_spec["inputSchema"]["json"][
            "properties"
        ]
    ) == ["request"]


@pytest.mark.parametrize("name", ASSISTANTS)
def test_the_model_is_not_offered_a_clinic(name: str) -> None:
    """Same shape argument as every other tool in this package: the
    clinic is closed over, so it is absent from the schema the model sees
    (`architecture.md` -> Invariants #1)."""
    properties = tool_named(dental_session(), name).tool_spec["inputSchema"]["json"][
        "properties"
    ]
    assert not [key for key in properties if "clinic" in key.lower()]


@pytest.mark.parametrize("name", ASSISTANTS)
def test_every_assistant_describes_itself_to_the_model(name: str) -> None:
    """`code-standards.md`: the docstring is what the model sees, and
    routing is the one decision it is being asked to make from it."""
    spec = tool_named(dental_session(), name).tool_spec
    assert len(spec["description"]) > 200
    assert all(
        field.get("description")
        for field in spec["inputSchema"]["json"]["properties"].values()
    )


# --------------------------------------------------------------------------
# What the front desk is told, and forbidden
# --------------------------------------------------------------------------


def test_the_system_prompt_carries_this_clinics_context() -> None:
    agent = build_orchestrator(dental_session())
    assert dental_session().describe() in agent.system_prompt
    assert "Bright Smile Dental" in agent.system_prompt


def test_the_other_clinic_is_nowhere_in_the_prompt() -> None:
    """One session, one clinic, one prompt -- there is no second clinic
    in it for a prompt-injected "use the other one" to name."""
    assert "Lumiere" not in build_orchestrator(dental_session()).system_prompt
    assert "Bright Smile" not in build_orchestrator(cosmetic_session()).system_prompt


def test_the_prompt_forbids_answering_from_its_own_knowledge() -> None:
    """The failure this agent is most likely to have: a fluent model
    inventing an opening time or a price because it sounds helpful."""
    text = prompt_text()
    assert (
        "anything you tell the patient about them must have come back from an"
        " assistant in this conversation" in text
    )
    assert "never invent a price, an opening time" in text


def test_the_prompt_forbids_confirming_a_booking_that_was_not_made() -> None:
    assert (
        "never tell a patient an appointment is booked, moved or cancelled unless"
        " the scheduling assistant has said it was done" in prompt_text()
    )


def test_the_prompt_says_what_is_not_an_escalation() -> None:
    """Without this the queue fills with taken slots and mistyped names,
    and the cards that need a person are lost among them."""
    text = prompt_text()
    assert "something the patient can settle themselves is not an escalation" in text
    assert "a time that has been taken" in text


def test_the_prompt_keeps_the_escalation_promise_honest() -> None:
    """The same override the Escalation sub-agent carries, restated at
    this layer because the Orchestrator is what speaks to the patient."""
    text = prompt_text()
    assert "do not promise a callback, ask the patient to ring the clinic" in text
    assert "do not say when" in text


def test_the_prompt_asks_it_to_greet_the_patient() -> None:
    """`project-overview.md` -> Core User Flow step 2. Who speaks first
    is the voice layer's question; that it greets at all is this one's."""
    assert "greeting the patient with the clinic's name" in prompt_text()


def test_the_prompt_says_an_assistant_cannot_hear_the_patient() -> None:
    """Each sub-agent is built fresh and sees only the `request` string,
    so a name collected here and not passed on is a name it asks for
    again -- out loud, to a patient who already gave it."""
    assert "an assistant cannot hear the patient" in prompt_text()


def test_the_front_desk_does_not_print_to_stdout() -> None:
    """Its answer is the patient's, but rendering it belongs to the
    interface layer -- and in AgentCore stdout is CloudWatch."""
    assert build_orchestrator(dental_session()).callback_handler is (
        null_callback_handler
    )


# --------------------------------------------------------------------------
# Opening a call
# --------------------------------------------------------------------------


def test_start_call_builds_a_front_desk_for_the_clinic_it_read(tables) -> None:
    clinics, _, _, _ = tables()
    agent = start_call(DENTAL_ID)
    assert agent.tool_names == ASSISTANTS
    assert "Bright Smile Dental" in agent.system_prompt
    assert clinics.requested == [{"clinic_id": DENTAL_ID}]


def test_a_new_call_holds_no_conversation(tables) -> None:
    tables()
    assert start_call(DENTAL_ID).messages == []


@pytest.mark.parametrize("clinic_id", ["", "   "])
def test_a_blank_clinic_id_fails_before_the_greeting(clinic_id: str, tables) -> None:
    """The clinic comes from the frontend, and a session that got here
    without one is a bug in the bridge, not a question for the patient."""
    tables()
    with pytest.raises(ValidationError):
        start_call(clinic_id)


def test_an_unknown_clinic_fails_before_the_greeting(tables) -> None:
    tables()
    with pytest.raises(NotFoundError):
        start_call("clinic-nowhere")


def test_a_broken_clinic_fails_before_the_greeting(tables) -> None:
    """`start_call` runs outside the `results.call` translation, because
    there is no model to tell yet. A bridge that opened a call against an
    unusable clinic would greet a patient it cannot serve."""
    tables(clinics=FakeClinicsTable(dental_clinic() | {"timezone": "Mars/Olympus"}))
    with pytest.raises(ConfigurationError):
        start_call(DENTAL_ID)


# --------------------------------------------------------------------------
# A whole call, end to end
# --------------------------------------------------------------------------


def test_a_booking_request_travels_the_whole_tree_to_dynamodb(tables) -> None:
    """Patient turn in; the Orchestrator routes to the scheduling
    assistant; that agent calls the tool layer; a row lands in the table;
    an answer comes back out. Three agents, no Bedrock."""
    _, store, patients_fake, _ = tables()
    model = ScriptedModel(
        # The front desk, routing.
        (
            "tool",
            (
                "scheduling_assistant",
                {
                    "request": (
                        f"{NAME} on {PHONE} wants a check-up at 9am on {WEDNESDAY}."
                    )
                },
            ),
        ),
        # The scheduling assistant, booking it and answering.
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
        ("text", "Booked, nine o'clock on Wednesday."),
        # The front desk again, reading it back to the patient.
        ("text", "That is booked for nine o'clock on Wednesday. See you then."),
    )
    answer = build_orchestrator(dental_session(), model)(
        "Nine on Wednesday for a check-up, please."
    )

    assert str(answer).strip() == (
        "That is booked for nine o'clock on Wednesday. See you then."
    )
    assert len(store.puts) == 1
    assert store.puts[0]["Item"][AppointmentAttrs.CLINIC_ID] == DENTAL_ID
    assert len(patients_fake.puts) == 1
    assert model.requests[0]["tool_names"] == ASSISTANTS


def test_the_assistants_answer_is_what_the_front_desk_reads(tables) -> None:
    """The sub-agent's spoken sentence is what comes back as the tool
    result -- not its own tool calls, and not a JSON payload for the
    Orchestrator to read out by mistake."""
    tables(appointment_items=one_checkup())
    model = ScriptedModel(
        (
            "tool",
            ("scheduling_assistant", {"request": "check-up on Wednesday, any time"}),
        ),
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "checkup"})),
        ("text", "Quarter past nine or half past are free on Wednesday."),
        ("text", "We have quarter past nine or half past. Which suits you?"),
    )
    agent = build_orchestrator(dental_session(), model)
    agent("when are you free on Wednesday?")

    result = ScriptedModel.tool_result(agent.messages)
    assert result["status"] == "success"
    assert result["content"][0]["text"] == (
        "Quarter past nine or half past are free on Wednesday."
    )


def test_a_price_question_reaches_the_faq_assistant_not_staff(tables, faq_kb) -> None:
    """The route the FAQ sub-agent adds: a published fact now comes back
    as an answer, not a card in the escalation queue."""
    _, _, _, escalations_fake = tables()
    fake = faq_kb("A cleaning costs £60 and takes about half an hour.")
    model = ScriptedModel(
        ("tool", ("faq_assistant", {"request": "How much is a cleaning?"})),
        ("tool", ("query_faq", {"question": "How much is a cleaning?"})),
        ("text", "A cleaning is £60."),
        ("text", "A cleaning costs £60."),
    )
    answer = build_orchestrator(dental_session(), model)("How much is a cleaning?")

    assert "£60" in str(answer)
    assert fake.calls[0]["knowledgeBaseId"] == "kb-dental-123"
    assert escalations_fake.puts == []


def test_a_faq_miss_that_still_needs_an_answer_is_escalated(tables, faq_kb) -> None:
    """What `faq_assistant` cannot answer is not silently dropped: the
    front desk still has to decide whether the patient needs a human,
    exactly as it does for anything else an assistant hands back."""
    _, _, _, escalations_fake = tables()
    faq_kb()
    model = ScriptedModel(
        ("tool", ("faq_assistant", {"request": "Do you offer valet parking?"})),
        ("tool", ("query_faq", {"question": "Do you offer valet parking?"})),
        ("text", "I do not have that information."),
        ("tool", ("escalation_assistant", {"request": "Wants to know about valet parking."})),
        ("tool", ("create_escalation", {"reason": "Wants to know about valet parking."})),
        ("text", "Recorded for staff."),
        ("text", "I don't have that, but a member of staff will follow up."),
    )
    answer = build_orchestrator(dental_session(), model)("Do you offer valet parking?")

    assert "member of staff" in str(answer)
    assert len(escalations_fake.puts) == 1


def test_a_refund_question_reaches_the_escalation_queue(tables) -> None:
    """The route `architecture.md` -> Invariants #6 names, driven from
    the top: nothing the tool layer encodes can answer this, so it
    becomes a card for a human rather than an improvised answer."""
    _, _, _, escalations_fake = tables()
    model = ScriptedModel(
        ("tool", ("escalation_assistant", {"request": REASON})),
        ("tool", ("create_escalation", {"reason": REASON})),
        ("text", "Recorded for the practice manager, who will call back."),
        ("text", "I have passed that to a member of staff, who will follow up."),
    )
    answer = build_orchestrator(dental_session(), model)(
        "I was charged twice for my cleaning and I want it refunded."
    )

    assert "member of staff" in str(answer)
    assert len(escalations_fake.puts) == 1
    item = escalations_fake.puts[0]["Item"]
    assert item[EscalationAttrs.CLINIC_ID] == DENTAL_ID
    assert item[EscalationAttrs.SOURCE] == EscalationSource.VOICE.value


def test_a_refund_question_books_nothing(tables) -> None:
    """The other half of routing: the assistant that was not called did
    not run, so the diary is untouched by a billing question."""
    _, store, _, _ = tables()
    model = ScriptedModel(
        ("tool", ("escalation_assistant", {"request": REASON})),
        ("tool", ("create_escalation", {"reason": REASON})),
        ("text", "Recorded for staff."),
        ("text", "A member of staff will follow up."),
    )
    build_orchestrator(dental_session(), model)("I want a refund.")
    assert store.puts == []


def test_the_front_desk_remembers_the_call_across_turns(tables) -> None:
    """The division of labour: this agent holds the conversation. A
    patient who gave their name in turn one is not asked for it again in
    turn three."""
    tables()
    model = ScriptedModel(
        ("text", "Hello, Bright Smile Dental. What can I do for you?"),
        ("text", "Which day suits you?"),
        ("text", "And your phone number?"),
    )
    agent = build_orchestrator(dental_session(), model)
    agent("hello")
    agent("I would like a check-up")
    agent("I am Dana Whitfield")

    assert [len(request["messages"]) for request in model.requests] == [1, 3, 5]
    assert "Dana Whitfield" in json.dumps(model.requests[-1]["messages"])


def test_a_sub_agent_starts_each_call_with_nothing(tables) -> None:
    """The other half of the same property. The front desk asks the
    scheduling assistant twice in one turn; the assistant sees one
    message each time, so nothing accumulates in it over a long call."""
    tables()
    model = ScriptedModel(
        ("tool", ("scheduling_assistant", {"request": "anything on Monday?"})),
        ("text", "Nothing on Monday."),
        ("tool", ("scheduling_assistant", {"request": "anything on Tuesday?"})),
        ("text", "Ten o'clock on Tuesday."),
        ("text", "Monday is full, but Tuesday at ten is free."),
    )
    build_orchestrator(dental_session(), model)("Monday or Tuesday?")

    sub_agent_turns = [
        len(request["messages"])
        for request in model.requests
        if request["system_prompt"].startswith("You are the scheduling assistant")
    ]
    assert sub_agent_turns == [1, 1]


def test_one_model_choice_runs_the_whole_tree(tables) -> None:
    """`build_orchestrator` threads its `model` down into both
    sub-agents, so a session cannot end up half on one model and half on
    another -- the open question about which text model to reason with
    has one answer per call, in one place."""
    tables()
    model = ScriptedModel(
        ("tool", ("scheduling_assistant", {"request": "anything on Wednesday?"})),
        ("text", "Nine or half past nine."),
        ("text", "Nine or half past nine are free."),
    )
    build_orchestrator(dental_session(), model)("when are you free?")

    prompts = system_prompts(model)
    assert len(prompts) == 3
    assert prompts[0].startswith("You are the front desk")
    assert prompts[1].startswith("You are the scheduling assistant")
    assert prompts[2].startswith("You are the front desk")


def test_a_call_for_the_other_clinic_reaches_only_that_clinic(tables) -> None:
    """Two callers, one process, the full three-agent tree: the clinic
    the session was opened for is the one that reaches DynamoDB two
    layers down, and nothing in between could have changed it."""
    clinics, _, _, _ = tables()
    model = ScriptedModel(
        ("tool", ("scheduling_assistant", {"request": "a consult on Wednesday"})),
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "consult"})),
        ("text", "Ten o'clock or eleven."),
        ("text", "We have ten o'clock or eleven on Wednesday."),
    )
    build_orchestrator(cosmetic_session(), model)("a consult, please")

    assert {entry["clinic_id"] for entry in clinics.requested} == {COSMETIC_ID}
    assert "Lumiere Aesthetics" in model.requests[0]["system_prompt"]


def test_a_broken_clinic_config_never_reaches_the_patient(tables) -> None:
    """The `ConfigurationError` translation, driven from the top: what
    comes back is the fixed internal-failure message, with no attribute
    path in it for a speech model to read out."""
    tables(clinics=FakeClinicsTable(dental_clinic() | {"slot_minutes": 0}))
    model = ScriptedModel(
        ("tool", ("scheduling_assistant", {"request": "Wednesday?"})),
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "checkup"})),
        ("text", "I am not able to check the diary right now."),
        ("text", "I cannot check the diary just now. A member of staff will help."),
    )
    build_orchestrator(dental_session(), model)("are you free on Wednesday?")

    # The third request is the sub-agent reading its own tool result back.
    handed_to_the_sub_agent = json.dumps(model.requests[2]["messages"])
    assert INTERNAL_FAILURE_MESSAGE in handed_to_the_sub_agent
    assert "slot_minutes" not in handed_to_the_sub_agent
