"""Scratch probe v2: does ending an (empty) audio turn provoke a reply?

Follow-up to scratch_text_turn.py, which proved a bare interactive text
turn gets accepted but never answered (output tokens pinned at 0 — the
same shape the deployed probe showed). Hypothesis: Nova Sonic only
completes a turn — and therefore only responds — once an audio input
container has been opened and closed. This probe opens one, sends a
short silence chunk, closes it (ending the "user turn"), and watches
for the greeting.
"""

import asyncio
import base64
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("strands.experimental.bidi.models.nova_sonic").setLevel(logging.DEBUG)

from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.models import BidiNovaSonicModel
from strands.experimental.bidi.types.events import (
    BidiAudioStreamEvent,
    BidiResponseCompleteEvent,
    BidiTranscriptStreamEvent,
)

# 200ms of 16kHz mono 16-bit silence.
SILENCE = base64.b64encode(b"\x00" * 6400).decode()


async def main() -> None:
    model = BidiNovaSonicModel()
    agent = BidiAgent(
        model=model,
        system_prompt="You are a dental clinic's front desk. Greet the caller briefly.",
    )
    async with agent:
        print("=== sending silence audio chunk ===", flush=True)
        await agent.send(
            {"type": "bidi_audio_input", "audio": SILENCE, "format": "pcm", "sample_rate": 16000, "channels": 1}
        )
        print("=== closing the audio container (end of turn) ===", flush=True)
        await model._end_audio_input()

        async for event in agent.receive():
            if isinstance(event, (BidiTranscriptStreamEvent, BidiAudioStreamEvent)):
                text = event.get("text", "")
                print(f"EVENT: {event['type']} text={text[:120]!r}", flush=True)
            elif isinstance(event, BidiResponseCompleteEvent):
                print(f"EVENT: response complete ({event['stop_reason']})", flush=True)
                break
            else:
                print(f"EVENT: {event['type']}", flush=True)


asyncio.run(main())
