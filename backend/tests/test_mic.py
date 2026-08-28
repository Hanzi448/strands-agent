"""Tests for the local microphone interface in `agents/mic.py`.

Like `cli.py` this module is an interface and nothing else, so what is
worth pinning is not the loop but the ways it could quietly ruin a call
that a person -- and Bedrock's meter -- is sitting in.

*It runs on a machine with no sound card.* PyAudio and PortAudio are a
development dependency of this one entry point, not of the deployed voice
path, so the module must import and the whole call must be drivable
without them. Every test here does exactly that, which is also the
assertion: `build_audio_io` is the only thing that touches a device.

*The agent still speaks first, and only once.* The greeting is sent from
an IO channel, because `BidiAgent.run` gives no other hook between "the
connection is open" and "the patient is being listened to". A channel
that yielded twice would greet a patient mid-sentence.

*The silence is measured, not guessed.* The open question this interface
exists to settle is what a model-composed greeting costs in dead air.
The timer is asserted here -- what starts it, what stops it, and that the
second audio frame of an answer does not restart it.

*What is printed is what was heard.* A developer with a headset can hear
the call but not see what the model made of it, so the monitor's lines
are the only record of which assistant was called and what was
transcribed. Nothing it prints is ever sent to the model.

The last section drives whole calls through the real `BidiAgent.run`
against a scripted speech model, so the channel wiring -- greeting in,
patient in, transcript out -- is proved rather than described. Nothing
here opens a Bedrock connection or a microphone.
"""

from __future__ import annotations

import asyncio
import io
import sys
from typing import Any

import pytest
from strands.experimental.bidi import (
    BidiAudioStreamEvent,
    BidiConnectionCloseEvent,
    BidiConnectionRestartEvent,
    BidiConnectionStartEvent,
    BidiErrorEvent,
    BidiInterruptionEvent,
    BidiOutputEvent,
    BidiTextInputEvent,
    BidiTranscriptStreamEvent,
    BidiUsageEvent,
    ToolResultEvent,
    ToolUseStreamEvent,
)
from strands.experimental.bidi.types.io import BidiInput, BidiOutput

from agents.mic import (
    AGENT_PREFIX,
    EXIT_START_FAILED,
    GREETING_LABEL,
    PATIENT_PREFIX,
    REPLY_LABEL,
    CallMonitor,
    Options,
    Silence,
    main,
    parse_args,
    run_call,
)
from agents.orchestrator import OPENING_TURN, TEXT_MODEL_ENV
from agents.voice import (
    DEFAULT_VOICE_REGION,
    VOICE_ID_ENV,
    VOICE_MODEL_ENV,
    VOICE_REGION_ENV,
    build_voice_agent,
)
from tests.test_orchestrator import dental_session, tables  # noqa: F401
from tests.test_scheduling import DENTAL_ID
from tests.test_voice import CALL_TIMEOUT_SECONDS, ScriptedBidiModel

DENTAL = DENTAL_ID

ENV_VARS = [TEXT_MODEL_ENV, VOICE_MODEL_ENV, VOICE_REGION_ENV, VOICE_ID_ENV]


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every variable this interface reads, for every test.

    A developer's own `$CLINICPILOT_VOICE_REGION` would otherwise decide
    what the default tests assert -- and pass on their machine only.
    """
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------
# Fakes: a microphone that hears what a test says, speakers that keep it
# --------------------------------------------------------------------------


class FakeMicrophone(BidiInput):
    """A microphone that says a fixed script and then stays silent.

    It sends *text* where a real one sends audio, because what a test
    needs to assert is that the channel reached the model at all -- and a
    scripted speech model has no ear to hear PCM with. The contract
    exercised is the same one `BidiAudioIO.input()` satisfies.

    After the script runs out it blocks, exactly as a real microphone in
    a quiet room does not return.
    """

    def __init__(self, *turns: str) -> None:
        self.turns = list(turns)
        self.started = False
        self.stopped = False
        self._finished = asyncio.Event()

    async def start(self, agent: Any) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True
        self._finished.set()

    async def __call__(self) -> BidiTextInputEvent:
        if self.turns:
            return BidiTextInputEvent(self.turns.pop(0), role="user")
        await self._finished.wait()
        raise asyncio.CancelledError


class FakeSpeakers(BidiOutput):
    """Speakers that keep everything they were asked to play."""

    def __init__(self) -> None:
        self.events: list[BidiOutputEvent] = []
        self.started = False
        self.stopped = False

    async def start(self, agent: Any) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def __call__(self, event: BidiOutputEvent) -> None:
        self.events.append(event)


class FakeAudioIO:
    """Stands where `BidiAudioIO` will, on a machine with no sound card.

    Satisfies `mic.AudioChannels`, which is the whole reason that protocol
    exists: the device is the one thing in this interface a test cannot
    have, so it is the one thing behind a seam.
    """

    def __init__(self, *turns: str) -> None:
        self.microphone = FakeMicrophone(*turns)
        self.speakers = FakeSpeakers()

    def input(self) -> BidiInput:
        return self.microphone

    def output(self) -> BidiOutput:
        return self.speakers


class HangingUpBidiModel(ScriptedBidiModel):
    """A scripted speech model that closes the connection when it is done.

    `BidiAgent.run` returns when the model closes, which over a real call
    is the deployed hang-up nobody has specified yet (an open question in
    `progress-tracker.md`) and here is simply how a test ends without
    cancelling a task group mid-flight.
    """

    def __init__(self, *turns: tuple[str, Any]) -> None:
        super().__init__(*turns)
        self._hung_up = False

    async def _respond(self) -> None:
        await super()._respond()
        if self.turns or self._hung_up:
            return
        self._hung_up = True
        assert self._queue is not None, "start was not called"
        await self._queue.put(
            BidiConnectionCloseEvent(connection_id="test", reason="user_request")
        )


def drive(
    audio: FakeAudioIO,
    *turns: tuple[str, Any],
    greeting: bool = True,
    verbose: bool = False,
) -> tuple[HangingUpBidiModel, str]:
    """Run one whole call over `run_call` and return the model and output."""
    model = HangingUpBidiModel(*turns)
    agent = build_voice_agent(dental_session(), voice_model=model)
    writer = io.StringIO()
    asyncio.run(
        asyncio.wait_for(
            run_call(
                agent,
                audio=audio,
                writer=writer,
                greeting=greeting,
                verbose=verbose,
            ),
            CALL_TIMEOUT_SECONDS,
        )
    )
    return model, writer.getvalue()


def transcript(text: str, role: str = "assistant") -> BidiTranscriptStreamEvent:
    """One final transcript line, as the model sends them."""
    return BidiTranscriptStreamEvent(
        delta={"text": text}, text=text, role=role, is_final=True
    )


def audio_frame() -> BidiAudioStreamEvent:
    """One frame of the agent's speech. The content is never read."""
    return BidiAudioStreamEvent(
        audio="", format="pcm", sample_rate=16000, channels=1
    )


def monitor(*, verbose: bool = False) -> tuple[CallMonitor, Silence, io.StringIO]:
    """A monitor, the timer it shares, and where it prints."""
    silence = Silence()
    writer = io.StringIO()
    return CallMonitor(silence, writer, verbose=verbose), silence, writer


def watch(events: list[BidiOutputEvent], *, verbose: bool = False) -> str:
    """Show a monitor a list of events and return everything it printed."""
    call_monitor, _, writer = monitor(verbose=verbose)

    async def show() -> None:
        for event in events:
            await call_monitor(event)

    asyncio.run(show())
    return writer.getvalue()


# --------------------------------------------------------------------------
# No sound card required
# --------------------------------------------------------------------------


def test_the_module_is_importable_without_pyaudio() -> None:
    """The deployed voice path has no microphone and the test suite has no
    PortAudio, so the device import happens in `build_audio_io` and
    nowhere else. Importing this module must not pull it in."""
    assert "agents.mic" in sys.modules
    assert "pyaudio" not in sys.modules


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------


def test_a_clinic_is_chosen_before_the_call_not_during_it() -> None:
    """The operator stands in for the browser: the clinic arrives from
    outside the conversation, as `architecture.md` -> Auth and Access
    Model requires, and no misheard sentence can change it."""
    assert parse_args([DENTAL]) == Options(
        clinic_id=DENTAL,
        text_model=None,
        voice_model=None,
        voice=None,
        region=DEFAULT_VOICE_REGION,
        greeting=True,
        verbose=False,
    )


def test_a_call_with_no_clinic_is_refused() -> None:
    """There is no default clinic, and guessing one would book a real
    appointment in the wrong diary."""
    with pytest.raises(SystemExit):
        parse_args([])


def test_the_stream_defaults_to_the_region_the_project_confirmed() -> None:
    """`architecture.md` -> Stack: `us-east-1`. Left to the ambient AWS
    profile this would silently become a region Nova Sonic is not in."""
    assert parse_args([DENTAL]).region == DEFAULT_VOICE_REGION


def test_the_environment_supplies_every_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same variables the CDK will set, so choosing a model or a voice
    is a deployment change rather than a code change."""
    monkeypatch.setenv(TEXT_MODEL_ENV, "text-model")
    monkeypatch.setenv(VOICE_MODEL_ENV, "amazon.nova-sonic-v1:0")
    monkeypatch.setenv(VOICE_REGION_ENV, "us-west-2")
    monkeypatch.setenv(VOICE_ID_ENV, "tiffany")
    options = parse_args([DENTAL])
    assert options.text_model == "text-model"
    assert options.voice_model == "amazon.nova-sonic-v1:0"
    assert options.region == "us-west-2"
    assert options.voice == "tiffany"


def test_a_blank_environment_variable_is_not_a_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exported-but-empty variable is how a shell profile sets nothing.
    Passing it through would ask Bedrock for the model named ''."""
    for name in ENV_VARS:
        monkeypatch.setenv(name, "   ")
    options = parse_args([DENTAL])
    assert options.text_model is None
    assert options.voice_model is None
    assert options.voice is None
    assert options.region == DEFAULT_VOICE_REGION


def test_the_command_line_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator is more specific than the shell they started in."""
    monkeypatch.setenv(VOICE_REGION_ENV, "us-west-2")
    monkeypatch.setenv(TEXT_MODEL_ENV, "text-model")
    options = parse_args([DENTAL, "--region", "eu-north-1", "--model", "other"])
    assert options.region == "eu-north-1"
    assert options.text_model == "other"


def test_the_two_models_are_two_settings() -> None:
    """Nova Sonic runs the conversation; the sub-agents are ordinary text
    agents. One flag setting both would hand a speech connection to an
    agent that wants a request-response one (`voice.py`)."""
    options = parse_args([DENTAL, "--model", "text", "--voice-model", "speech"])
    assert options.text_model == "text"
    assert options.voice_model == "speech"


def test_the_other_arm_of_the_greeting_experiment_is_available() -> None:
    """`--no-greeting` is the arm where the operator speaks first and the
    agent never greets anyone -- the comparison the open question about
    who greets the patient needs."""
    assert parse_args([DENTAL, "--no-greeting"]).greeting is False


# --------------------------------------------------------------------------
# The silence the patient sits in
# --------------------------------------------------------------------------


def test_an_unmarked_silence_times_nothing() -> None:
    """Audio the patient did not wait for -- the second frame of an
    answer, or anything before the call has asked a question -- is not a
    latency measurement."""
    assert Silence().take() is None


def test_a_marked_silence_is_read_once() -> None:
    """Reading clears it, so an answer's first audio frame is timed and
    the thousand frames behind it are not."""
    silence = Silence()
    silence.mark(GREETING_LABEL)
    timed = silence.take()
    assert timed is not None and timed[0] == GREETING_LABEL
    assert silence.take() is None


def test_the_newest_silence_is_the_one_that_counts() -> None:
    """A patient who says something else before the agent answers is
    waiting for a reply to *that*, not to the turn before it."""
    silence = Silence()
    silence.mark(GREETING_LABEL)
    silence.mark(REPLY_LABEL)
    timed = silence.take()
    assert timed is not None and timed[0] == REPLY_LABEL


def test_the_wait_for_a_reply_is_timed_from_what_the_patient_said() -> None:
    """The number this interface exists to produce: transcript in, first
    audio frame out, and the seconds between them printed."""
    printed = watch([transcript("Wednesday at nine", role="user"), audio_frame()])
    assert f"{REPLY_LABEL}: first audio after" in printed


def test_only_the_first_frame_of_an_answer_is_timed() -> None:
    """A line per audio frame would be thousands of lines a call, and
    every one after the first measures nothing."""
    printed = watch(
        [transcript("Wednesday at nine", role="user"), audio_frame(), audio_frame()]
    )
    assert printed.count("first audio after") == 1


# --------------------------------------------------------------------------
# What the monitor shows
# --------------------------------------------------------------------------


def test_both_sides_of_the_call_are_printed_and_told_apart() -> None:
    """The only record of what the model *heard*. A misheard phone number
    is invisible otherwise, and this is the layer that has to show it."""
    printed = watch(
        [
            transcript("I need a check-up", role="user"),
            transcript("Of course. Which day?", role="assistant"),
        ]
    )
    assert f"{PATIENT_PREFIX}I need a check-up" in printed
    assert f"{AGENT_PREFIX}Of course. Which day?" in printed


def test_a_half_heard_phrase_is_not_printed_as_what_was_said() -> None:
    """Interim transcripts are revised as the patient keeps talking.
    Printed by default they would read as a stream of misquotes."""
    interim = BidiTranscriptStreamEvent(
        delta={"text": "check"}, text="check", role="user", is_final=False
    )
    assert "check" not in watch([interim])
    assert "check" in watch([interim], verbose=True)


def test_the_assistant_a_call_was_routed_to_is_named_once() -> None:
    """Which assistant, and when -- the thing a developer cannot hear.
    Once per call, because the arguments arrive in a stream of fragments
    and each one is another event."""
    tool_use = {"toolUseId": "call-1", "name": "scheduling_assistant", "input": {}}
    printed = watch(
        [
            ToolUseStreamEvent(delta={"toolUse": tool_use}, current_tool_use=tool_use),
            ToolUseStreamEvent(delta={"toolUse": tool_use}, current_tool_use=tool_use),
        ]
    )
    assert printed.count("scheduling_assistant") == 1


def test_an_assistants_answer_is_reported_with_how_long_it_took() -> None:
    """A booking is seconds of silence in the middle of a call, and
    whether those seconds were the assistant or the speech model is the
    first question anyone asks about latency."""
    tool_use = {"toolUseId": "call-1", "name": "scheduling_assistant", "input": {}}
    result: dict[str, Any] = {
        "toolUseId": "call-1",
        "status": "success",
        "content": [{"text": "Booked for nine o'clock."}],
    }
    events: list[BidiOutputEvent] = [
        ToolUseStreamEvent(delta={"toolUse": tool_use}, current_tool_use=tool_use),
        ToolResultEvent(result),
    ]
    printed = watch(events)
    assert "scheduling_assistant success in" in printed
    assert "Booked for nine o'clock." not in printed
    assert "Booked for nine o'clock." in watch(events, verbose=True)


def test_a_connection_that_reopens_itself_is_visible() -> None:
    """Nova Sonic caps a connection at eight minutes and the loop restarts
    it silently. Silent is right for the patient and wrong for whoever is
    watching a demo."""
    printed = watch([BidiConnectionRestartEvent(Exception("timeout"))])
    assert "restarted" in printed


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (BidiConnectionStartEvent("c-1", "amazon.nova-2-sonic-v1:0"), "connected"),
        (BidiConnectionCloseEvent("c-1", "user_request"), "closed"),
        (BidiInterruptionEvent("user_speech"), "interrupted"),
        (BidiErrorEvent(RuntimeError("stream failed")), "stream failed"),
    ],
)
def test_the_shape_of_the_call_is_printed(
    event: BidiOutputEvent, expected: str
) -> None:
    """Connected, interrupted, restarted, closed, broken. The known
    failure mode of this stack is a connection that hangs saying nothing,
    so a line for each of these is what tells the operator where it
    stopped."""
    assert expected in watch([event])


def test_token_usage_is_not_in_the_way_of_the_conversation() -> None:
    """Real per-call cost, but a line of arithmetic between every two
    sentences of a call someone is trying to read."""
    usage = BidiUsageEvent(input_tokens=10, output_tokens=20, total_tokens=30)
    assert "tokens" not in watch([usage])
    assert "10 in, 20 out" in watch([usage], verbose=True)


# --------------------------------------------------------------------------
# A whole call over the real `BidiAgent.run`
# --------------------------------------------------------------------------


def test_the_agent_is_prompted_to_speak_first(tables) -> None:  # noqa: F811
    """`project-overview.md` -> Core User Flow has the Orchestrator greet
    the patient, and a `BidiAgent` holds an open connection in silence
    until something is sent. So the microphone opens a call the same way
    the keyboard does -- with the stage direction, not a greeting of the
    interface's own composing."""
    tables()
    audio = FakeAudioIO()
    model, printed = drive(audio, ("say", "Bright Smile Dental, how can I help?"))
    assert model.text_sent == [OPENING_TURN]
    assert f"{AGENT_PREFIX}Bright Smile Dental, how can I help?" in printed


def test_the_greeting_is_sent_once_and_the_channel_then_says_nothing(
    tables,  # noqa: F811
) -> None:
    """The greeting rides in on an input channel `run` reads in a loop. A
    channel that yielded twice would talk over the patient's first
    sentence with a second stage direction."""
    tables()
    audio = FakeAudioIO("I would like an appointment")
    model, _ = drive(
        audio,
        ("say", "Bright Smile Dental, how can I help?"),
        ("say", "Of course. Which day?"),
    )
    assert model.text_sent == [OPENING_TURN, "I would like an appointment"]


def test_the_other_arm_greets_nobody(tables) -> None:  # noqa: F811
    """`--no-greeting`: the operator speaks first and the agent never
    opens the call. The comparison the open question needs, and proof the
    stage direction is not sent from anywhere else."""
    tables()
    audio = FakeAudioIO("hello?")
    model, _ = drive(audio, ("say", "Bright Smile Dental."), greeting=False)
    assert model.text_sent == ["hello?"]


def test_what_the_patient_says_reaches_the_model(tables) -> None:  # noqa: F811
    """The microphone channel is wired to the connection, not to a
    console. Everything else in this interface is downstream of it."""
    tables()
    audio = FakeAudioIO("Wednesday at nine, please")
    model, _ = drive(
        audio,
        ("say", "Bright Smile Dental, how can I help?"),
        ("say", "Wednesday at nine it is."),
    )
    assert "Wednesday at nine, please" in model.text_sent


def test_the_agent_is_played_and_watched_at_the_same_time(
    tables,  # noqa: F811
) -> None:
    """The monitor sits *beside* the speakers, not instead of them: a call
    that printed a transcript but played no audio is a call the patient
    cannot hear."""
    tables()
    audio = FakeAudioIO()
    _, printed = drive(audio, ("say", "Bright Smile Dental."))
    assert audio.speakers.events
    assert AGENT_PREFIX in printed


def test_the_devices_are_started_and_stopped_with_the_call(
    tables,  # noqa: F811
) -> None:
    """A microphone left open after a call is a microphone left listening.
    `run` closes both channels in its own `finally`; this asserts they are
    channels it recognises as such."""
    tables()
    audio = FakeAudioIO()
    drive(audio, ("say", "Bright Smile Dental."))
    assert audio.microphone.started and audio.microphone.stopped
    assert audio.speakers.started and audio.speakers.stopped


def test_the_call_is_watched_from_the_moment_it_closes(
    tables,  # noqa: F811
) -> None:
    """A closed connection is the one thing the operator must not have to
    guess at: over a real call it means the meter has stopped."""
    tables()
    _, printed = drive(FakeAudioIO(), ("say", "Bright Smile Dental."))
    assert "closed (user_request)" in printed


# --------------------------------------------------------------------------
# A call that cannot be opened says why
# --------------------------------------------------------------------------


def test_an_unknown_clinic_is_reported_before_the_microphone_opens(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`start_voice_call` reads the clinic row, so a seeding or credential
    fault surfaces while there is still a caller to report it to rather
    than a patient listening to silence."""
    tables()
    monkeypatch.setattr("agents.mic.build_audio_io", FakeAudioIO)
    monkeypatch.setattr(
        "agents.mic.build_nova_sonic_model", lambda **_: ScriptedBidiModel()
    )
    assert main(["clinic-nope"]) == EXIT_START_FAILED
    assert "clinic-nope" in capsys.readouterr().err


def test_a_machine_with_no_audio_support_is_told_how_to_get_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """PortAudio is a system library and PyAudio fails to import without
    it. The one dependency this entry point adds is also the one thing an
    operator cannot guess at from an ImportError traceback."""

    def no_audio() -> Any:
        raise ImportError("No module named 'pyaudio'")

    monkeypatch.setattr("agents.mic.build_audio_io", no_audio)
    assert main([DENTAL]) == EXIT_START_FAILED
    assert "bidi-pyaudio" in capsys.readouterr().err
