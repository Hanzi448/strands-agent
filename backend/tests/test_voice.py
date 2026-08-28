"""Tests for the voice layer -- the Orchestrator with a microphone.

`agents/voice.py` is wiring, so what is worth pinning is not much code
but four ways the wiring could be wrong in a way nobody notices until a
patient is on the line.

*The surface does not widen when it starts speaking.* A `BidiAgent` is
built from a different class and a different loop, so the invariant that
the front desk holds exactly two assistants and no `backend/tools/`
function has to be asserted again here rather than inherited from the
text Orchestrator's suite (`architecture.md` -> Invariants #2 and #3).

*The routing rules are one text, not two.* The voice prompt is asserted
to *begin* with the Orchestrator's own prompt, character for character.
A voice layer that paraphrased the routing rules would be a second copy
free to drift from the one `orchestrator.py` holds, and only the typed
interface would ever show the difference.

*The speech model and the text model stay apart.* Nova Sonic runs the
conversation; the two sub-agents are ordinary text agents. The end-to-end
tests drive both at once -- a scripted speech model above, a scripted
text model below -- so wiring the Sonic model down into
`orchestrator_tools` would fail here rather than at the first booking.

*A spoken turn reaches DynamoDB.* The last section runs whole calls
through the real `BidiAgent` loop and the real tool executor against fake
tables: a tool use event goes in, a row comes out. Nothing here opens a
Bedrock connection -- `ScriptedBidiModel` stands where Nova Sonic will.

Every fixture, fake and scripted text model is imported from the suite
that already owns it, so nothing can drift.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from strands.experimental.bidi import (
    BidiResponseCompleteEvent,
    BidiTextInputEvent,
    BidiTranscriptStreamEvent,
    ToolResultEvent,
    ToolUseStreamEvent,
)

from agents.orchestrator import OPENING_TURN, ORCHESTRATOR_SYSTEM_PROMPT
from agents.voice import (
    DEFAULT_VOICE_REGION,
    VOICE_ID_ENV,
    VOICE_MODEL_ENV,
    VOICE_PROMPT_SUFFIX,
    VOICE_REGION_ENV,
    build_nova_sonic_model,
    build_voice_agent,
    greet,
    start_voice_call,
    voice_system_prompt,
)
from tests.test_appointments import NAME, NINE, NINE_FIFTEEN, PHONE, booked
from tests.test_orchestrator import (
    ASSISTANTS,
    cosmetic_session,
    dental_session,
    tables,  # noqa: F401
)
from tests.test_scheduling import DENTAL_ID, FakeClinicsTable, dental_clinic
from tests.test_scheduling_agent import (
    TOOL_NAMES as SCHEDULING_TOOL_NAMES,
    ScriptedModel,
    WEDNESDAY,
)
from tools.errors import ConfigurationError, NotFoundError, ValidationError
from tools.schema import AppointmentAttrs

# Long enough that a slow machine is not a failure, short enough that a
# script which no longer fits the wiring fails instead of hanging the
# suite -- the drive loop below waits on a queue nothing will ever fill.
CALL_TIMEOUT_SECONDS = 10.0

VOICE_ENV_VARS = [VOICE_MODEL_ENV, VOICE_REGION_ENV, VOICE_ID_ENV]


class ScriptedBidiModel:
    """Stands where Nova Sonic will: plays a fixed script, opens nothing.

    Satisfies the `BidiModel` protocol, so the real `BidiAgent`, its
    event loop and the real tool executor all run -- the only thing
    replaced is the speech connection and the model's judgement.

    A turn is either `("tool", (name, args))` or `("say", text)`. The
    script advances on every *input*: a turn from the patient, and a tool
    result coming back, each release the next scripted response. That is
    the same sequencing Nova Sonic has, so a script written here is the
    order events really arrive in.

    Each response ends with a `BidiResponseCompleteEvent`, which is what
    the drive loop below stops on -- a marker for the test, and the event
    the real model sends at the same point.
    """

    def __init__(self, *turns: tuple[str, Any]) -> None:
        self.turns = list(turns)
        self.config: dict[str, Any] = {"audio": {"output_rate": 16000, "channels": 1}}
        self.started: dict[str, Any] | None = None
        self.stopped = False
        self.sent: list[Any] = []
        self._queue: asyncio.Queue | None = None
        self._responses = 0

    async def start(
        self,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        messages: Any = None,
        **kwargs: Any,
    ) -> None:
        # Built here rather than in `__init__`: an `asyncio.Queue` belongs
        # to the loop that first awaits it, and these tests own the loop.
        self._queue = asyncio.Queue()
        self.started = {
            "system_prompt": system_prompt,
            "tool_names": [spec["name"] for spec in (tools or [])],
            "messages": list(messages or []),
        }

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, content: Any) -> None:
        self.sent.append(content)
        await self._respond()

    async def receive(self) -> AsyncIterator[Any]:
        assert self._queue is not None, "start was not called"
        while True:
            yield await self._queue.get()

    @property
    def text_sent(self) -> list[str]:
        """What was said to the model, in order, as plain text."""
        return [
            event.text for event in self.sent if isinstance(event, BidiTextInputEvent)
        ]

    @property
    def tool_results(self) -> list[dict[str, Any]]:
        """The tool results handed back to the model, in order."""
        return [
            event.tool_result
            for event in self.sent
            if isinstance(event, ToolResultEvent)
        ]

    async def _respond(self) -> None:
        """Play the next scripted response, if there is one."""
        assert self._queue is not None, "start was not called"
        if not self.turns:
            return
        self._responses += 1
        response_id = f"response-{self._responses}"
        kind, payload = self.turns.pop(0)
        if kind == "say":
            await self._queue.put(
                BidiTranscriptStreamEvent(
                    delta={"text": payload},
                    text=payload,
                    role="assistant",
                    is_final=True,
                )
            )
            await self._queue.put(
                BidiResponseCompleteEvent(response_id, stop_reason="end_turn")
            )
            return
        name, arguments = payload
        tool_use = {
            "toolUseId": f"call-{self._responses}",
            "name": name,
            "input": arguments,
        }
        await self._queue.put(
            ToolUseStreamEvent(delta={"toolUse": tool_use}, current_tool_use=tool_use)
        )


def take_call(agent: Any, turn: str) -> list[Any]:
    """Open a connection, say one thing, and collect until the model stops.

    The real `BidiAgent` loop throughout: `send` reaches the model, the
    tool executor runs whatever it asks for, and the result goes back --
    all of it on a connection to `ScriptedBidiModel` rather than Bedrock.
    """

    async def drive() -> list[Any]:
        await agent.start()
        try:
            await agent.send(turn)
            events = []
            async for event in agent.receive():
                events.append(event)
                if isinstance(event, BidiResponseCompleteEvent):
                    return events
            return events
        finally:
            await agent.stop()

    return asyncio.run(asyncio.wait_for(drive(), CALL_TIMEOUT_SECONDS))


def spoken(events: list[Any]) -> list[str]:
    """What the agent said out loud, from a collected call."""
    return [
        event.text
        for event in events
        if isinstance(event, BidiTranscriptStreamEvent)
        and event.is_final
        and event.role == "assistant"
    ]


def booking_script() -> ScriptedBidiModel:
    """The speech half of one booking: route, then read the answer back."""
    return ScriptedBidiModel(
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
        ("say", "That is booked for nine o'clock on Wednesday."),
    )


def booking_text_script() -> ScriptedModel:
    """The text half: the scheduling assistant booking it and answering."""
    return ScriptedModel(
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
    )


@pytest.fixture(autouse=True)
def _no_ambient_voice_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset the voice environment for every test.

    A developer's own `$CLINICPILOT_VOICE_REGION` would otherwise decide
    what the default tests assert -- and pass on their machine only.
    """
    for name in VOICE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------
# The surface: still two assistants, now that it speaks
# --------------------------------------------------------------------------


def test_the_voice_agent_holds_exactly_the_two_assistants() -> None:
    """A different agent class and a different loop, the same boundary:
    everything that touches the clinic's data is behind an assistant
    (`architecture.md` -> Invariants #2)."""
    agent = build_voice_agent(dental_session(), voice_model=ScriptedBidiModel())
    assert agent.tool_names == ASSISTANTS


@pytest.mark.parametrize(
    "name", [*SCHEDULING_TOOL_NAMES, "create_escalation", "find_upcoming_appointments"]
)
def test_no_tool_layer_function_is_reachable_by_voice(name: str) -> None:
    """Named individually, so wiring one in fails a test that says why.
    Speech does not earn the front desk a write to DynamoDB
    (`architecture.md` -> Invariants #3)."""
    agent = build_voice_agent(dental_session(), voice_model=ScriptedBidiModel())
    assert name not in agent.tool_names


@pytest.mark.parametrize("name", ASSISTANTS)
def test_the_speech_model_is_not_offered_a_clinic(name: str) -> None:
    """The clinic is closed over, so it is absent from the schema the
    speech model sees and no misheard sentence can supply one
    (`architecture.md` -> Invariants #1)."""
    agent = build_voice_agent(dental_session(), voice_model=ScriptedBidiModel())
    properties = agent.tool_registry.get_all_tool_specs()
    spec = next(item for item in properties if item["name"] == name)
    keys = list(spec["inputSchema"]["json"]["properties"])
    assert keys == ["request"]


def test_the_voice_agent_starts_with_no_conversation() -> None:
    """Like its typed counterpart it accumulates one, so it must begin
    empty -- a built agent carrying messages would be a previous
    patient's call handed to the next."""
    agent = build_voice_agent(dental_session(), voice_model=ScriptedBidiModel())
    assert agent.messages == []


# --------------------------------------------------------------------------
# The prompt: one routing text, plus what the microphone adds
# --------------------------------------------------------------------------


def test_the_voice_prompt_begins_with_the_orchestrators_own_prompt() -> None:
    """Character for character. A paraphrase here would be a second copy
    of the routing rules, free to drift from `orchestrator.py`."""
    session = dental_session()
    assert voice_system_prompt(session).startswith(
        ORCHESTRATOR_SYSTEM_PROMPT.format(clinic=session.describe())
    )


def test_the_voice_prompt_adds_only_the_suffix() -> None:
    """Everything after the Orchestrator's prompt is `VOICE_PROMPT_SUFFIX`
    and nothing else -- so the whole of what speech adds is readable in
    one constant."""
    session = dental_session()
    prompt = voice_system_prompt(session)
    routing = ORCHESTRATOR_SYSTEM_PROMPT.format(clinic=session.describe())
    assert prompt == routing + VOICE_PROMPT_SUFFIX


def test_the_suffix_is_about_the_medium_and_not_about_the_clinic() -> None:
    """What it may say is what is only true over a microphone. A price, a
    time or a policy in here would be the front desk answering from its
    prompt instead of from an assistant."""
    suffix = " ".join(VOICE_PROMPT_SUFFIX.lower().split())
    assert "read a name and a phone number back" in suffix
    assert "speak over you" in suffix
    assert "ask for it again" in suffix


def test_the_prompt_names_the_clinic_the_call_was_opened_for() -> None:
    """Two clinics, two prompts. The same process serving both is the
    multi-tenancy claim, and the prompt is where it first shows."""
    dental = voice_system_prompt(dental_session())
    cosmetic = voice_system_prompt(cosmetic_session())
    assert dental != cosmetic
    assert dental_session().clinic_name in dental
    assert cosmetic_session().clinic_name not in dental


# --------------------------------------------------------------------------
# Which speech model, and where it is opened
# --------------------------------------------------------------------------


def test_the_stream_opens_in_the_region_the_project_confirmed() -> None:
    """`architecture.md` -> Stack: `us-east-1`. Left to the ambient AWS
    profile this would silently become a region Nova Sonic is not in."""
    assert build_nova_sonic_model().region == DEFAULT_VOICE_REGION


def test_the_environment_chooses_the_model_the_region_and_the_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """So a model or voice change is a deployment change, not a code
    change -- these are the variables the CDK will set."""
    monkeypatch.setenv(VOICE_MODEL_ENV, "amazon.nova-sonic-v1:0")
    monkeypatch.setenv(VOICE_REGION_ENV, "us-west-2")
    monkeypatch.setenv(VOICE_ID_ENV, "tiffany")
    model = build_nova_sonic_model()
    assert model.model_id == "amazon.nova-sonic-v1:0"
    assert model.region == "us-west-2"
    assert model.config["audio"]["voice"] == "tiffany"


def test_a_blank_environment_variable_is_not_a_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exported-but-empty variable is how a shell profile sets nothing.
    Passing it through would ask Bedrock for the model named ''."""
    for name in VOICE_ENV_VARS:
        monkeypatch.setenv(name, "   ")
    model = build_nova_sonic_model()
    assert model.model_id
    assert model.region == DEFAULT_VOICE_REGION
    assert model.config["audio"]["voice"]


def test_an_argument_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller is more specific than the shell it was started in."""
    monkeypatch.setenv(VOICE_REGION_ENV, "us-west-2")
    assert build_nova_sonic_model(region="eu-north-1").region == "eu-north-1"


# --------------------------------------------------------------------------
# Opening a call: the clinic is checked before the microphone
# --------------------------------------------------------------------------


def test_a_voice_call_reads_its_clinic_before_anything_is_connected(
    tables,  # noqa: F811
) -> None:
    """`start_voice_call` is the one entry point, so the clinic it read is
    the clinic the prompt names two agent layers down."""
    tables()
    agent = start_voice_call(DENTAL_ID, voice_model=ScriptedBidiModel())
    assert dental_session().clinic_name in (agent.system_prompt or "")
    assert agent.tool_names == ASSISTANTS


@pytest.mark.parametrize(
    ("clinic_id", "error"),
    [("", ValidationError), ("clinic-nope", NotFoundError)],
)
def test_a_voice_call_cannot_be_opened_for_a_clinic_it_cannot_serve(
    tables,  # noqa: F811
    clinic_id: str,
    error: type[Exception],
) -> None:
    """It fails here rather than three turns into a booking -- and while
    there is still a caller to report it to, not a patient."""
    tables()
    with pytest.raises(error):
        start_voice_call(clinic_id, voice_model=ScriptedBidiModel())


def test_a_broken_clinic_config_stops_the_call_before_the_greeting(
    tables,  # noqa: F811
) -> None:
    """A seeding fault is found at session start. Anything later would
    greet a patient the process cannot actually serve."""
    tables(clinics=FakeClinicsTable(dental_clinic() | {"timezone": "Mars/Olympus"}))
    with pytest.raises(ConfigurationError):
        start_voice_call(DENTAL_ID, voice_model=ScriptedBidiModel())


# --------------------------------------------------------------------------
# Who speaks first
# --------------------------------------------------------------------------


def test_the_call_is_opened_with_a_stage_direction_not_a_greeting(
    tables,  # noqa: F811
) -> None:
    """A `BidiAgent` holds an open connection in silence, and
    `project-overview.md` has the Orchestrator greet the patient. So
    something must prompt the first turn -- and what it sends is a stage
    direction, leaving the words the patient hears to the model."""
    tables()
    model = ScriptedBidiModel()
    agent = build_voice_agent(dental_session(), voice_model=model)

    async def drive() -> None:
        await agent.start()
        try:
            await greet(agent)
        finally:
            await agent.stop()

    asyncio.run(asyncio.wait_for(drive(), CALL_TIMEOUT_SECONDS))

    assert model.text_sent == [OPENING_TURN]
    assert dental_session().clinic_name not in OPENING_TURN


# --------------------------------------------------------------------------
# A whole spoken call, end to end
# --------------------------------------------------------------------------


def test_a_spoken_booking_travels_the_whole_tree_to_dynamodb(
    tables,  # noqa: F811
) -> None:
    """A tool use event from the speech model in; the scheduling assistant
    runs on the text model; a row lands in the table; a sentence comes
    back out to be spoken. Two models, three agents, no Bedrock."""
    _, store, patients_fake, _ = tables()
    voice_model = booking_script()
    agent = build_voice_agent(
        dental_session(), voice_model=voice_model, text_model=booking_text_script()
    )

    events = take_call(agent, "Nine on Wednesday for a check-up, please.")

    assert spoken(events) == ["That is booked for nine o'clock on Wednesday."]
    assert len(store.puts) == 1
    assert store.puts[0]["Item"][AppointmentAttrs.CLINIC_ID] == DENTAL_ID
    assert len(patients_fake.puts) == 1


def test_the_speech_model_is_only_ever_shown_the_two_assistants(
    tables,  # noqa: F811
) -> None:
    """What Nova Sonic is told it can do, at the moment the connection
    opens. The four scheduling tools are the *sub-agent's*, and a speech
    model holding them could book without one."""
    tables()
    voice_model = booking_script()
    agent = build_voice_agent(
        dental_session(), voice_model=voice_model, text_model=booking_text_script()
    )

    take_call(agent, "Nine on Wednesday for a check-up, please.")

    assert voice_model.started is not None
    assert voice_model.started["tool_names"] == ASSISTANTS
    assert voice_model.started["system_prompt"] == voice_system_prompt(dental_session())


def test_the_sub_agents_run_on_the_text_model_not_the_speech_model(
    tables,  # noqa: F811
) -> None:
    """The two are different kinds of model, and this is the assertion
    that keeps them apart: the scheduling assistant's request went to the
    text model, holding the tools only it has."""
    tables()
    text_model = booking_text_script()
    agent = build_voice_agent(
        dental_session(), voice_model=booking_script(), text_model=text_model
    )

    take_call(agent, "Nine on Wednesday for a check-up, please.")

    assert len(text_model.requests) == 2
    assert text_model.requests[0]["tool_names"] == SCHEDULING_TOOL_NAMES


def test_the_assistants_answer_is_what_the_speech_model_reads_out(
    tables,  # noqa: F811
) -> None:
    """The sub-agent's spoken sentence is what comes back as the tool
    result -- not its own tool calls, and not a JSON payload for a speech
    model to read out loud by mistake."""
    tables(appointment_items=[booked("apt_one", NINE, NINE_FIFTEEN)])
    voice_model = ScriptedBidiModel(
        (
            "tool",
            ("scheduling_assistant", {"request": "check-up on Wednesday, any time"}),
        ),
        ("say", "We have quarter past nine or half past. Which suits you?"),
    )
    text_model = ScriptedModel(
        ("tool", ("check_availability", {"date": WEDNESDAY, "service": "checkup"})),
        ("text", "Quarter past nine or half past are free on Wednesday."),
    )
    agent = build_voice_agent(
        dental_session(), voice_model=voice_model, text_model=text_model
    )

    take_call(agent, "when are you free on Wednesday?")

    assert len(voice_model.tool_results) == 1
    result = voice_model.tool_results[0]
    assert result["status"] == "success"
    assert result["content"][0]["text"] == (
        "Quarter past nine or half past are free on Wednesday."
    )


def test_the_spoken_call_accumulates_in_the_agent(tables) -> None:  # noqa: F811
    """Like the typed Orchestrator, the voice agent is where the
    conversation lives: the turn, the tool use, its result and the answer
    are all in one place for the next turn to be answered against."""
    tables()
    agent = build_voice_agent(
        dental_session(),
        voice_model=booking_script(),
        text_model=booking_text_script(),
    )

    take_call(agent, "Nine on Wednesday for a check-up, please.")

    rendered = str(agent.messages)
    assert "Nine on Wednesday for a check-up, please." in rendered
    assert "scheduling_assistant" in rendered
    assert "That is booked for nine o'clock on Wednesday." in rendered
