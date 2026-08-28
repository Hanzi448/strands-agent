"""The local microphone interface: one headset, one call, no browser.

The voice counterpart of `cli.py`, and the first thing in this repo that
opens a Bedrock connection. Everything under `start_voice_call` has been
driven by a scripted speech model against fake tables; nothing has yet
put the Orchestrator's prompt in front of Nova Sonic with a person
talking over it. That is what this module is for -- speaking to the front
desk is the only way to find out what the system prompt sounds like when
it is *heard* rather than read, and how long a patient waits in silence
before it says anything.

It is an *interface*, and holds nothing else: it builds the agent from
`voice.py`, hands `BidiAgent.run` a microphone and a pair of speakers,
and prints what goes past. There is no clinic logic here, no tool call
and no prompt text -- a rule that lived in this file would be a rule the
deployed WebSocket entrypoint does not get (`code-standards.md` ->
General, one concern per layer). It is a development entry point, not a
deployed one, exactly as `cli.py` is.

**What it measures.** The open question this interface exists to settle
is the *cost* of letting the model compose its own greeting: the patient
hears nothing between the connection opening and the first audio frame.
So the monitor times it, and times every reply the same way -- from the
patient's last final transcript to the first audio of the answer. Those
lines are the point of this module, not decoration.

**The greeting is sent from an IO channel, because that is the only hook
`run` gives.** `BidiAgent.run` owns the connection: it starts the agent,
then starts each channel, then begins pumping. `voice.Greeting.start` is
therefore the one place a first turn can be sent after the connection is
open and before the patient is listened to. It is `voice.py`'s, not this
module's -- shared with the AgentCore entrypoint so both send the same
stage direction rather than two that could drift. This module's own
addition is the timing callback, not the channel itself.

**How a call ends.** Ctrl-C, and nothing else. Nova Sonic caps a
connection at eight minutes and `BidiAgentLoop` silently restarts it, so
a session nobody ends runs until this process does -- and a patient
saying "goodbye" is an ordinary turn, exactly as it is over the keyboard.
What a *deployed* call should do about that is an open question in
`progress-tracker.md`, and deliberately not answered here.

**Use a headset.** Nothing here cancels echo, so over open laptop
speakers the model hears itself, treats it as the patient interrupting,
and stops mid-sentence. Strands can cancel it (`AudioProcessorConfig`,
the `bidi-aec` extra); a headset is one dependency fewer.

Run it from `backend/`, with credentials for `us-east-1` in the shell:

    python -m agents.mic clinic-dental

A first connection that hangs with no "connected" line is the known
failure mode: the experimental Nova Sonic client swallows credential
errors rather than raising them (`progress-tracker.md`). Check the
profile and the region before looking anywhere else.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, TextIO

from strands.experimental.bidi import (
    BidiAgent,
    BidiAudioStreamEvent,
    BidiConnectionCloseEvent,
    BidiConnectionRestartEvent,
    BidiConnectionStartEvent,
    BidiErrorEvent,
    BidiInterruptionEvent,
    BidiOutputEvent,
    BidiTranscriptStreamEvent,
    BidiUsageEvent,
    ToolResultEvent,
    ToolUseStreamEvent,
)
from strands.experimental.bidi.types.io import BidiInput, BidiOutput

from tools.errors import ToolError

from .orchestrator import TEXT_MODEL_ENV
from .voice import (
    DEFAULT_VOICE_REGION,
    VOICE_ID_ENV,
    VOICE_MODEL_ENV,
    VOICE_REGION_ENV,
    Greeting,
    build_nova_sonic_model,
    start_voice_call,
)

if TYPE_CHECKING:  # pragma: no cover - never executed; see `build_audio_io`
    from strands.experimental.bidi.io import BidiAudioIO

logger = logging.getLogger(__name__)

PATIENT_PREFIX: Final[str] = "you> "
AGENT_PREFIX: Final[str] = "clinic> "
NOTE_PREFIX: Final[str] = "   "
ERROR_PREFIX: Final[str] = "!! "

# What a timed silence is called when it is printed. Two labels because
# they answer two different questions: the first is the cost of a
# model-composed greeting -- an open question in `progress-tracker.md` --
# and the second is the ordinary turn latency a patient hears all call.
GREETING_LABEL: Final[str] = "greeting"
REPLY_LABEL: Final[str] = "reply"

# The install hint for the one dependency this module adds. PyAudio needs
# the PortAudio system library underneath it, which is why it is not in
# `requirements.txt` and why a missing one is reported rather than raised.
AUDIO_INSTALL_HINT: Final[str] = (
    "no audio device support: install it with"
    " `pip install 'strands-agents[bidi-pyaudio]'`"
    " (it needs the PortAudio system library)."
)

LOG_FORMAT: Final[str] = "%(levelname)s %(name)s: %(message)s"

EXIT_OK: Final[int] = 0
EXIT_START_FAILED: Final[int] = 1
EXIT_CALL_FAILED: Final[int] = 2


class AudioChannels(Protocol):
    """What `run_call` needs from a source of audio.

    `BidiAudioIO` satisfies it, and so does anything else that can hand
    over one input and one output channel -- which is how a call is
    driven in a test on a machine with no microphone and no PyAudio.
    """

    def input(self) -> BidiInput:
        """The channel the patient's speech is read from."""
        ...

    def output(self) -> BidiOutput:
        """The channel the agent's speech is played to."""
        ...


@dataclass(frozen=True)
class Options:
    """One invocation of the interface.

    Attributes:
        clinic_id: The clinic this call is pinned to. Given on the command
            line because the operator stands in for the browser, which is
            where it comes from in the real system (`architecture.md` ->
            Auth and Access Model). Nothing said into the microphone can
            change it.
        text_model: The model id both sub-agents reason with, or `None` to
            leave the Strands default. Not the model the patient hears --
            see `voice.py` on why the two are separate arguments.
        voice_model: The Nova Sonic model id, or `None` for the library's
            default.
        voice: The Nova Sonic voice id, or `None` for the library's
            default.
        region: Where the bidirectional stream is opened.
        greeting: Whether the agent is prompted to speak first.
        verbose: Whether to log at `INFO` and print interim transcripts,
            the assistants' answers, and token usage.
    """

    clinic_id: str
    text_model: str | None
    voice_model: str | None
    voice: str | None
    region: str
    greeting: bool
    verbose: bool


def parse_args(argv: Sequence[str] | None = None) -> Options:
    """Read the command line into an `Options`.

    Args:
        argv: Arguments without the program name. `None` reads
            `sys.argv[1:]`.

    Returns:
        The options for this run.

    Raises:
        SystemExit: On a usage error or `--help`, as argparse does.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agents.mic",
        description=(
            "Talk to a clinic's front-desk agent through a microphone. It"
            " opens a real Nova Sonic connection and reads and writes the"
            " same DynamoDB tables the browser will: anything booked here"
            " is really booked. Use a headset."
        ),
    )
    parser.add_argument(
        "clinic_id",
        help="The clinic to answer for, e.g. clinic-dental.",
    )
    parser.add_argument(
        "--model",
        default=_from_env(TEXT_MODEL_ENV),
        help=(
            "Model id for both sub-agents -- not for the voice"
            f" (default: ${TEXT_MODEL_ENV}, or the Strands default)."
        ),
    )
    parser.add_argument(
        "--voice-model",
        default=_from_env(VOICE_MODEL_ENV),
        help=(
            "Nova Sonic model id"
            f" (default: ${VOICE_MODEL_ENV}, or the Strands default)."
        ),
    )
    parser.add_argument(
        "--voice",
        default=_from_env(VOICE_ID_ENV),
        help=(
            "Nova Sonic voice id, e.g. matthew"
            f" (default: ${VOICE_ID_ENV}, or the Strands default)."
        ),
    )
    parser.add_argument(
        "--region",
        default=_from_env(VOICE_REGION_ENV) or DEFAULT_VOICE_REGION,
        help=(
            "Where the speech connection is opened"
            f" (default: ${VOICE_REGION_ENV}, or {DEFAULT_VOICE_REGION})."
        ),
    )
    parser.add_argument(
        "--no-greeting",
        action="store_true",
        help=(
            "Wait for you to speak first, instead of opening the call with"
            " a turn that leaves the greeting to the agent."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print interim transcripts, assistant answers and token usage.",
    )
    args = parser.parse_args(argv)
    return Options(
        clinic_id=args.clinic_id,
        text_model=args.model,
        voice_model=args.voice_model,
        voice=args.voice,
        region=args.region,
        greeting=not args.no_greeting,
        verbose=args.verbose,
    )


class Silence:
    """How long the patient has been hearing nothing, and since what.

    One mark at a time: a mark set while another is pending replaces it,
    because what the patient is waiting for is whatever they last said.
    Reading it clears it, so the first audio frame of an answer is timed
    and the thousand frames after it are not.
    """

    def __init__(self) -> None:
        self._label: str | None = None
        self._since: float = 0.0

    def mark(self, label: str) -> None:
        """Start timing a silence the patient is now sitting through.

        Args:
            label: What they are waiting for, printed as-is.
        """
        self._label = label
        # Monotonic: a clock the machine's own NTP correction cannot move
        # backwards in the middle of a call.
        self._since = time.monotonic()

    def take(self) -> tuple[str, float] | None:
        """Read and clear the pending mark, if a silence just ended.

        Returns:
            The label and how many seconds it lasted, or `None` if
            nothing was being timed.
        """
        if self._label is None:
            return None
        label, self._label = self._label, None
        return label, time.monotonic() - self._since


class CallMonitor(BidiOutput):
    """Print what goes past, and time the silences.

    The visible half of the interface: a developer with a headset can
    hear the call but cannot see what was *heard*, which assistant was
    called, or how long the patient waited. Nothing here is sent to the
    model -- it is an output channel beside the speakers, not instead of
    them.
    """

    def __init__(
        self, silence: Silence, writer: TextIO, *, verbose: bool = False
    ) -> None:
        """Initialise the monitor.

        Args:
            silence: The shared timer, marked by `_Greeting` and by every
                final patient transcript, read at the first audio frame
                of each answer.
            writer: Where the call is printed.
            verbose: Whether to print interim transcripts, the assistants'
                answers, and token usage.
        """
        self._silence = silence
        self._writer = writer
        self._verbose = verbose
        self._calls: dict[str, tuple[str, float]] = {}

    async def __call__(self, event: BidiOutputEvent) -> None:
        """Print one event from the call.

        Args:
            event: Whatever the agent's loop has just produced.
        """
        if isinstance(event, BidiAudioStreamEvent):
            self._on_audio()
        elif isinstance(event, BidiTranscriptStreamEvent):
            self._on_transcript(event)
        elif isinstance(event, ToolUseStreamEvent):
            self._on_tool_use(event)
        elif isinstance(event, ToolResultEvent):
            self._on_tool_result(event)
        elif isinstance(event, BidiInterruptionEvent):
            self._note(f"interrupted ({event.reason})")
        elif isinstance(event, BidiConnectionStartEvent):
            self._note(f"connected to {event.model}")
        elif isinstance(event, BidiConnectionRestartEvent):
            # Not a fault: Nova Sonic caps a connection at eight minutes
            # and the loop reopens it. Printed anyway, because a restart
            # the patient cannot hear is still worth seeing in a demo.
            self._note("connection restarted -- the patient hears nothing")
        elif isinstance(event, BidiConnectionCloseEvent):
            self._note(f"connection closed ({event.reason})")
        elif isinstance(event, BidiErrorEvent):
            self._write(f"{ERROR_PREFIX}{event.code}: {event.message}")
        elif isinstance(event, BidiUsageEvent) and self._verbose:
            self._note(f"tokens: {event.input_tokens} in, {event.output_tokens} out")

    def _on_audio(self) -> None:
        """Report the silence that this first frame of an answer ended."""
        timed = self._silence.take()
        if timed is None:
            return
        label, seconds = timed
        self._note(f"{label}: first audio after {seconds:.1f}s")

    def _on_transcript(self, event: BidiTranscriptStreamEvent) -> None:
        """Print a transcript, and time what the patient now waits for."""
        text = event.text.strip()
        if not event.is_final:
            if self._verbose and text:
                self._note(f"...{text}")
            return
        if event.role != "user":
            self._write(f"{AGENT_PREFIX}{text}")
            return
        self._write(f"{PATIENT_PREFIX}{text}")
        # The patient has stopped talking: everything between here and
        # the next audio frame is silence they are sitting in.
        self._silence.mark(REPLY_LABEL)

    def _on_tool_use(self, event: ToolUseStreamEvent) -> None:
        """Announce an assistant the first time this call is seen.

        The arguments are deliberately not printed: they arrive in
        fragments and are only whole by the time the assistant has
        already been called. What is useful live is *which* one, and when
        -- the request itself is in the answer, under `--verbose`.
        """
        tool_use = event.get("current_tool_use") or {}
        tool_use_id = tool_use.get("toolUseId")
        name = tool_use.get("name")
        if not tool_use_id or not name or tool_use_id in self._calls:
            return
        self._calls[tool_use_id] = (name, time.monotonic())
        self._note(f"-> {name}")

    def _on_tool_result(self, event: ToolResultEvent) -> None:
        """Report how an assistant answered, and how long it took."""
        name, started = self._calls.pop(
            event.tool_use_id, ("assistant", time.monotonic())
        )
        result = event.tool_result
        status = result.get("status", "unknown")
        self._note(f"<- {name} {status} in {time.monotonic() - started:.1f}s")
        if not self._verbose:
            return
        for block in result.get("content", []):
            text = str(block.get("text", "")).strip()
            if text:
                self._note(f"   {text}")

    def _note(self, text: str) -> None:
        """Print something *about* the call rather than something said in it."""
        self._write(f"{NOTE_PREFIX}{text}")

    def _write(self, text: str) -> None:
        """Write and flush, so a live call prints as it happens."""
        self._writer.write(f"{text}\n")
        self._writer.flush()


def build_audio_io() -> BidiAudioIO:
    """Open the machine's default microphone and speakers.

    Imported at call time rather than at module import: `BidiAudioIO`
    pulls in PyAudio and the PortAudio system library under it, which the
    deployed voice path does not need and which is therefore not in
    `requirements.txt`. Nothing about this module's shape should depend
    on a sound card being present, which is also what lets a whole call
    be driven in a test.

    No device is chosen here. PortAudio takes the system default, which
    is what the operating system's own sound settings say.

    Returns:
        A `BidiAudioIO` that hands over one input and one output channel.

    Raises:
        ImportError: If the `bidi-pyaudio` extra is not installed.
            `AUDIO_INSTALL_HINT` is what to tell the operator.
    """
    from strands.experimental.bidi.io import BidiAudioIO

    return BidiAudioIO()


async def run_call(
    agent: BidiAgent,
    *,
    audio: AudioChannels,
    writer: TextIO,
    greeting: bool = True,
    verbose: bool = False,
) -> None:
    """Run one call until the connection closes or the operator stops it.

    Args:
        agent: The call's voice agent, from `start_voice_call`. Built once
            and kept, because like its typed counterpart it is where the
            conversation accumulates.
        audio: Where the patient is heard and the agent is played.
        writer: Where the monitor prints the call.
        greeting: Whether to prompt the agent to speak first. `False`
            waits for the operator instead -- the other arm of the open
            question about who greets the patient.
        verbose: Passed to the monitor.
    """
    silence = Silence()
    inputs: list[BidiInput] = [audio.input()]
    if greeting:
        inputs.append(Greeting(on_start=lambda: silence.mark(GREETING_LABEL)))
    outputs: list[BidiOutput] = [
        audio.output(),
        CallMonitor(silence, writer, verbose=verbose),
    ]
    await agent.run(inputs=inputs, outputs=outputs)


def main(argv: Sequence[str] | None = None) -> int:
    """Open a voice call for one clinic and run it until it ends.

    Args:
        argv: Arguments without the program name. `None` reads
            `sys.argv[1:]`.

    Returns:
        `EXIT_OK` when the call ended normally or the operator hung up;
        `EXIT_START_FAILED` if it could never be opened -- no audio
        support, an unknown clinic, an unusable config, or no credentials
        for the tables; `EXIT_CALL_FAILED` if an open call then broke.
    """
    options = parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO if options.verbose else logging.WARNING,
        format=LOG_FORMAT,
    )
    try:
        audio = build_audio_io()
    except ImportError:
        logger.debug("audio device support is not installed", exc_info=True)
        print(f"{ERROR_PREFIX}{AUDIO_INSTALL_HINT}", file=sys.stderr)
        return EXIT_START_FAILED

    try:
        voice_model = build_nova_sonic_model(
            model_id=options.voice_model,
            region=options.region,
            voice=options.voice,
        )
        # Reads the clinic row, so a missing profile, a wrong region or an
        # unseeded table fails here -- before the microphone is open and
        # while there is still somewhere to report it.
        agent = start_voice_call(
            options.clinic_id,
            voice_model=voice_model,
            text_model=options.text_model,
        )
    except ToolError as error:
        # Printed in full, attribute paths and all: the reader here is a
        # developer, not a patient. Same reasoning as `cli.py`.
        print(f"{ERROR_PREFIX}{error.message}", file=sys.stderr)
        return EXIT_START_FAILED
    except Exception as error:
        print(
            f"{ERROR_PREFIX}could not open a call for {options.clinic_id!r}:"
            f" {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return EXIT_START_FAILED

    print(
        f"Calling clinic {options.clinic_id!r} in {options.region}."
        " Speak when it answers; press Ctrl-C to hang up."
    )
    try:
        asyncio.run(
            run_call(
                agent,
                audio=audio,
                writer=sys.stdout,
                greeting=options.greeting,
                verbose=options.verbose,
            )
        )
    except KeyboardInterrupt:
        # The operator hanging up. `BidiAgent.run` closes the connection
        # and both devices on its way out of its own `finally`.
        print("")
        return EXIT_OK
    except Exception as error:
        logger.exception("the call failed")
        print(
            f"{ERROR_PREFIX}the call ended: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return EXIT_CALL_FAILED
    return EXIT_OK


def _from_env(name: str) -> str | None:
    """Read `name`, treating blank or whitespace as unset."""
    return os.environ.get(name, "").strip() or None


if __name__ == "__main__":
    raise SystemExit(main())
