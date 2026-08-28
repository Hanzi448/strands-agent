"""The voice layer: the same front desk, over a microphone.

`architecture.md` -> Stack puts Amazon Nova Sonic behind a Strands
`BidiAgent` for the patient-facing call. This module is the wiring, and
almost nothing else: it builds the Orchestrator described in
`orchestrator.py` as a `BidiAgent` instead of an `Agent`, so that the
speech-to-speech model *is* the front desk rather than a layer of
transcription bolted in front of one. Speech goes in, the same two
assistants are called, speech comes out.

**Nothing about the clinic is decided here.** The system prompt, the
routing rules and the two Agent-as-Tool wrappers all come from
`orchestrator.py` unchanged. What this module adds is what only holds
when there is a microphone: which speech model, and a short prompt
paragraph about the fact the patient is being *heard* rather than read
(`VOICE_PROMPT_SUFFIX`). A routing rule written in this file would be a
rule the text interface does not get, and the two would drift.

**The voice model and the text model are not the same model, and the
signatures below keep them apart.** Nova Sonic is a bidirectional speech
model; the Scheduling and Escalation sub-agents are ordinary text
`Agent`s doing ordinary tool calls. `build_voice_agent` therefore takes
`voice_model` and `text_model` as two separate arguments -- passing the
Sonic model down to `orchestrator_tools` would hand a speech connection
to an agent that wants a request-response one. That is the same
`text_model` value `cli.py` chooses, and settling it is one open question
in `progress-tracker.md`.

**The sub-agent tools work here unchanged, and do not block the audio.**
They are synchronous `@tool` functions -- each one runs a whole text
agent, which is seconds of network -- but Strands runs a non-async tool
in a worker thread (`strands/tools/decorator.py`), so the event loop
carrying the patient's audio keeps turning while a booking is being made.
Nothing in `scheduling_agent.py` or `escalation_agent.py` had to become
async for the voice layer, which is why they are imported rather than
mirrored.

**Nova Sonic is an optional dependency, imported where it is used.**
`BidiNovaSonicModel` pulls in `aws-sdk-bedrock-runtime` and the smithy
stack, installed by the `bidi` extra in `requirements.txt`.
`build_nova_sonic_model` imports it at call time rather than at module
import, so `build_voice_agent` can be built and tested against any
`BidiModel` -- which is what the test suite does -- and so an import of
this module never fails for a reason that has nothing to do with the
caller. `BidiAgent` itself has no such dependency.

**Who speaks first.** `project-overview.md` -> Core User Flow has the
Orchestrator greet the patient, and a `BidiAgent` holds its connection
open in silence until something is sent to it. So a voice call opens the
same way a typed one does: with `OPENING_TURN`, the stage direction that
leaves the greeting itself to the model. `greet` is that one line, here
rather than in each caller so the microphone and the keyboard run the
same experiment.

This module builds the agent. Driving one -- opening the connection,
pumping audio in and out, closing it -- belongs to whatever holds the
session: `mic.py` (a local microphone) and `agentcore_app.py` (a
browser's WebSocket, once deployed).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Final, NoReturn

from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.models.model import BidiModel
from strands.experimental.bidi.types.io import BidiInput
from strands.models.model import Model

from .orchestrator import (
    OPENING_TURN,
    ORCHESTRATOR_SYSTEM_PROMPT,
    orchestrator_tools,
)
from .session import ClinicSession

# Which Nova Sonic model the call runs on. Unset means the Strands
# default, which is Sonic v2 -- named here rather than pinned, so a model
# change is an environment change and not a code one.
VOICE_MODEL_ENV: Final[str] = "CLINICPILOT_VOICE_MODEL"

# Where the Bedrock bidirectional stream is opened. Separate from the
# table region on purpose: Nova Sonic exists in four regions and the
# clinic's data does not have to be in one of them.
VOICE_REGION_ENV: Final[str] = "CLINICPILOT_VOICE_REGION"

# Which Nova Sonic voice the clinic answers in. Left to the library's
# default when unset; which voice each demo clinic uses is an open
# question in `progress-tracker.md`, not something to settle in code.
VOICE_ID_ENV: Final[str] = "CLINICPILOT_VOICE_ID"

# `architecture.md` -> Stack, Region: `us-east-1`, confirmed, for every
# resource in this project. Spelled out rather than left to the ambient
# AWS profile, so a developer whose shell points somewhere else gets the
# region the project was built for instead of a region where Nova Sonic
# does not exist.
DEFAULT_VOICE_REGION: Final[str] = "us-east-1"

# What is true over a microphone and not over a keyboard. Appended to the
# Orchestrator's prompt rather than folded into it, so that reading
# `orchestrator.py` still tells you the whole of how a call is routed and
# this file adds only what the medium adds.
#
# The read-back rule is not a new policy: `orchestrator.py` already
# forbids inventing a phone number and requires the patient's name and
# number before booking. Speech recognition is where those two arrive
# wrong, so this is that existing rule enforced at the point it breaks.
VOICE_PROMPT_SUFFIX: Final[str] = """

You are hearing this patient, not reading them. Speech recognition mishears
names, phone numbers and dates more than anything else:

- Read a name and a phone number back to the patient and wait for them to agree
  before you pass either to an assistant. Say a phone number as digits, in
  small groups, not as a whole number.
- Say a date as the weekday and the day, not as numbers, and say a time the way
  a person says it.
- If you did not hear something clearly, ask for it again. Never fill in a name,
  a number or a day you only half heard.
- The patient can speak over you. If they do, stop and listen: what they say
  then is the next thing to answer, not an interruption to talk through."""


def voice_system_prompt(session: ClinicSession) -> str:
    """The Orchestrator's prompt for one clinic, plus what speech adds.

    Args:
        session: The clinic this conversation is pinned to. Supplies the
            clinic block -- name, today's local date, services.

    Returns:
        The system prompt for the voice agent.
    """
    return (
        ORCHESTRATOR_SYSTEM_PROMPT.format(clinic=session.describe())
        + VOICE_PROMPT_SUFFIX
    )


def build_nova_sonic_model(
    *,
    model_id: str | None = None,
    region: str | None = None,
    voice: str | None = None,
) -> BidiModel:
    """Construct the Nova Sonic model the patient hears and is heard by.

    No connection is opened here -- that happens in `BidiAgent.start`, so
    a bad region or missing credentials surfaces when the call starts
    rather than when the process does.

    Args:
        model_id: Nova Sonic model id. `None` reads
            `$CLINICPILOT_VOICE_MODEL`, and falls back to the Strands
            default.
        region: Bedrock region for the bidirectional stream. `None` reads
            `$CLINICPILOT_VOICE_REGION`, and falls back to
            `DEFAULT_VOICE_REGION`.
        voice: Nova Sonic voice id. `None` reads `$CLINICPILOT_VOICE_ID`,
            and falls back to the library's default voice.

    Returns:
        A `BidiNovaSonicModel` ready to be handed to `build_voice_agent`.

    Raises:
        ImportError: If the `bidi` extra is not installed. It is in
            `requirements.txt`; this is the import that says so.
        ValueError: If the resolved region is not a valid region id.
    """
    # Imported here, not at module scope: see the module docstring on why
    # this module must import cleanly without the `bidi` extra present.
    from strands.experimental.bidi.models import BidiNovaSonicModel

    model_id = model_id or _from_env(VOICE_MODEL_ENV)
    voice = voice or _from_env(VOICE_ID_ENV)
    region = region or _from_env(VOICE_REGION_ENV) or DEFAULT_VOICE_REGION

    # Both left out entirely when unset, rather than passed as `None`:
    # the library's own defaults are the fallback, and a `None` model id
    # would override rather than defer to them.
    provider_config: dict[str, dict[str, str]] = (
        {"audio": {"voice": voice}} if voice else {}
    )
    client_config = {"region": region}

    if model_id:
        return BidiNovaSonicModel(
            model_id=model_id,
            provider_config=provider_config,
            client_config=client_config,
        )
    return BidiNovaSonicModel(
        provider_config=provider_config, client_config=client_config
    )


def build_voice_agent(
    session: ClinicSession,
    *,
    voice_model: BidiModel | str | None = None,
    text_model: Model | str | None = None,
) -> BidiAgent:
    """Construct the patient-facing voice agent for one clinic.

    The Orchestrator of `orchestrator.py`, speaking: same prompt, same two
    assistants, same refusal to answer anything itself. Call this once per
    voice session and keep the returned agent -- like its typed
    counterpart, it is where the conversation accumulates.

    Args:
        session: The clinic this conversation is pinned to. Closed over by
            both sub-agents, so no tool is offered a `clinic_id` and
            nothing the patient says can change the clinic
            (`architecture.md` -> Invariants #1).
        voice_model: The speech model, or a Nova Sonic model id. `None`
            builds one from the environment via `build_nova_sonic_model`.
        text_model: The model the two sub-agents reason with. Not the
            voice model -- see the module docstring. `None` leaves the
            Strands default, which is still an open question rather than a
            decision.

    Returns:
        A `BidiAgent` holding `scheduling_assistant` and
        `escalation_assistant`, and nothing else.
    """
    return BidiAgent(
        model=voice_model if voice_model is not None else build_nova_sonic_model(),
        name="orchestrator",
        description="Answers a patient call for one clinic and routes it.",
        system_prompt=voice_system_prompt(session),
        tools=list(orchestrator_tools(session, text_model)),
    )


def start_voice_call(
    clinic_id: str,
    *,
    voice_model: BidiModel | str | None = None,
    text_model: Model | str | None = None,
) -> BidiAgent:
    """Open a voice call: read the clinic, then build its front desk.

    The voice counterpart of `orchestrator.start_call`, and the single
    entry point anything driving a voice session should use, so that no
    caller builds a `ClinicSession` by hand and skips the checks
    `ClinicSession.start` runs. A clinic that does not exist, or whose
    stored timezone this process cannot resolve, fails here -- before the
    microphone is open and while there is still somewhere to report it.

    Args:
        clinic_id: The clinic selected when the session started. It comes
            from the frontend (`architecture.md` -> Auth and Access
            Model) and nothing in the conversation can change it.
        voice_model: Passed to `build_voice_agent`.
        text_model: Passed to `build_voice_agent`.

    Returns:
        A fresh `BidiAgent` for this call, holding no conversation yet and
        with no connection open.

    Raises:
        ValidationError: If `clinic_id` is missing or malformed.
        NotFoundError: If no clinic exists with that id.
        ConfigurationError: If the clinic's stored config is unusable.
    """
    return build_voice_agent(
        ClinicSession.start(clinic_id),
        voice_model=voice_model,
        text_model=text_model,
    )


async def greet(agent: BidiAgent) -> None:
    """Prompt the agent to speak first, once the connection is open.

    Sends `OPENING_TURN` -- a stage direction, not a greeting, so the
    words the patient hears are the model's own. Call it after
    `BidiAgent.start`; before that there is no connection to send on.

    Args:
        agent: The started voice agent for this call.
    """
    await agent.send(OPENING_TURN)


class Greeting(BidiInput):
    """Speak first, then hold an input channel open saying nothing.

    An input *channel* rather than a bare call to `greet` in whatever
    holds the session, because `BidiAgent.run` owns the connection: it
    starts the agent, then starts each channel, then begins pumping.
    `start` is therefore the only point between "the connection is open"
    and "the patient is being listened to" -- exactly where a greeting
    goes. Shared by every interface that opens a call this way (`mic.py`,
    the AgentCore entrypoint), so the greeting experiment stays one
    channel rather than two that could drift.

    Blocks forever after sending, since `run` reads every input channel
    in a loop and one that yielded twice would talk over the patient's
    first sentence with a second stage direction.
    """

    def __init__(self, *, on_start: Callable[[], None] | None = None) -> None:
        """Initialise the channel.

        Args:
            on_start: Called synchronously just before the greeting is
                sent, for a caller that needs to know *when* -- `mic.py`
                uses it to start timing the silence a model-composed
                greeting costs. Not called at all if omitted.
        """
        self._on_start = on_start
        self._finished = asyncio.Event()

    async def start(self, agent: BidiAgent) -> None:
        """Send the opening turn."""
        if self._on_start is not None:
            self._on_start()
        await greet(agent)

    async def stop(self) -> None:
        """Release the pump task waiting on this channel."""
        self._finished.set()

    async def __call__(self) -> NoReturn:
        """Never return an event: this channel has said its one thing.

        Raises:
            asyncio.CancelledError: Always, once the call is over.
        """
        await self._finished.wait()
        raise asyncio.CancelledError


def _from_env(name: str) -> str | None:
    """Read `name`, treating blank or whitespace as unset."""
    return os.environ.get(name, "").strip() or None
