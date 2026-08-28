"""The deployed voice entrypoint: the same front desk, over a browser.

The third interface over `voice.py`'s agent, after `cli.py` (keyboard)
and `mic.py` (microphone) -- and the first one nothing local drives. It
holds a FastAPI app shaped exactly the way Bedrock AgentCore Runtime
requires: a `/ping` health check, and a `/ws` WebSocket endpoint that
speaks the same JSON event protocol Nova Sonic and the vendored
frontend already use
(`vendor/sample-nova-sonic-websocket-agentcore/agent/strands_agent.py`
is the reference shape this follows).

**It holds no clinic logic, no prompt text and no tool call**, exactly
as `cli.py` and `mic.py` hold none: it reads a clinic id off the
connection, builds the agent from `voice.py`, and pumps events between
the socket and `BidiAgent.run`. A rule written here would be a rule
neither local interface gets.

**Split from the old "deploy to AgentCore Runtime" item.**
`progress-tracker.md` bundled writing this entrypoint with actually
deploying it -- provisioning the AgentCore Runtime resources in
`agent_stack.py`, building and pushing the container, and listening to
a real call. `ai-workflow-rules.md` -> When to Split Work requires
Python logic and its CDK deployment to be separate steps, exactly the
split that already happened once between `voice.py` and `mic.py`. This
module is the half that is code: it is verifiable now, offline, through
FastAPI's own ASGI test client against a scripted speech model, in the
same way `mic.py` is verified without a sound card. Provisioning the
runtime and hearing a real call remain open, in `progress-tracker.md`.

**The clinic is chosen when the connection opens, never by what the
patient says.** `architecture.md` -> Auth and Access Model has the
browser pick a clinic before the call starts. The query string is where
that arrives -- `/ws?clinic_id=clinic-dental` -- not the first message
sent once the socket is open, so there is no point in the exchange
where a spoken sentence could relabel the call. It is also not an
invented mechanism: AgentCore's own presigned URL already carries the
session id the same way
(`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` in
`websocket-presigned.ts`), and query parameters are exactly what
survives AgentCore's proxy from that public URL through to this
container's `/ws` route.

**A call that cannot open is refused before `accept()`, not after.**
`start_voice_call` reads the clinic row, so a missing clinic id, an
unknown clinic, or a config this process cannot resolve all fail before
the socket is accepted -- there is no half-open connection charged to
Bedrock for a call that was never going to work. Starlette allows
`WebSocket.close()` before `accept()` for exactly this. Only the
failure's stable `code` crosses the socket as the close reason; the
message itself is logged, never sent, for the reason `results.py`
already gives `ConfigurationError`: the far end is an anonymous browser
tab, not a developer with a terminal.

**Nothing here calls `agent.stop()`.** `BidiAgent.run`'s own `finally`
already stops every input, every output and the agent itself
(`strands/experimental/bidi/agent/agent.py`) -- the vendored sample
calls it again anyway, which this module deliberately does not, for the
same reason `mic.py` trusts the same cleanup rather than repeating it.

**No PyAudio in this path, and none in its container.** The vendored
sample's `Dockerfile` installs PortAudio "even though we don't directly
use mic/speakers" -- this module never imports `BidiAudioIO` at all, so
there is nothing to install: a browser sends and receives the same JSON
audio events `mic.py`'s fake channels use in tests, never a sound
device. Matches `architecture.md` -> System Boundaries, which already
says the deployed path "never opens a sound card."
"""

from __future__ import annotations

import logging
import os
import time
from typing import Final

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from tools.errors import ToolError

from .orchestrator import TEXT_MODEL_ENV
from .voice import Greeting, start_voice_call

logger = logging.getLogger(__name__)

# What the connection is expected to carry the clinic id as. A query
# parameter, not a path segment: AgentCore's own public URL already adds
# one (the session id, in `websocket-presigned.ts`), so this rides the
# same mechanism rather than inventing a second one.
CLINIC_ID_PARAM: Final[str] = "clinic_id"

# WebSocket close codes this endpoint can send. Standard codes rather
# than invented ones, so a generic client library reports something
# sensible even before the frontend gives them any meaning of their own.
CLOSE_POLICY_VIOLATION: Final[int] = 1008
CLOSE_INTERNAL_ERROR: Final[int] = 1011

app = FastAPI()


@app.get("/ping")
async def ping() -> dict[str, object]:
    """Health check AgentCore Runtime polls before routing traffic here.

    Returns:
        The shape AgentCore's health check expects -- see the vendored
        sample's `strands_agent.py`, the reference this follows.
    """
    return {"status": "Healthy", "time_of_last_update": int(time.time())}


@app.websocket("/ws")
async def voice_session(websocket: WebSocket) -> None:
    """Answer one patient call: read the clinic, then run the front desk.

    Args:
        websocket: The browser's connection. `clinic_id` is read from its
            query string before `accept()`, and nothing sent afterwards
            can change it.
    """
    clinic_id = websocket.query_params.get(CLINIC_ID_PARAM)
    if not clinic_id:
        logger.warning("a call arrived with no %s", CLINIC_ID_PARAM)
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="missing_clinic_id")
        return

    try:
        agent = start_voice_call(clinic_id, text_model=_from_env(TEXT_MODEL_ENV))
    except ToolError as error:
        logger.warning(
            "call for %r refused before it opened: %s", clinic_id, error.message
        )
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason=error.code)
        return
    except Exception:
        logger.exception("call for %r could not be opened", clinic_id)
        await websocket.close(code=CLOSE_INTERNAL_ERROR, reason="internal_error")
        return

    await websocket.accept()
    logger.info("call for %r connected", clinic_id)
    try:
        await agent.run(
            inputs=[websocket.receive_json, Greeting()],
            outputs=[websocket.send_json],
        )
    except WebSocketDisconnect as error:
        logger.info(
            "call for %r ended: the browser disconnected (%s)",
            clinic_id,
            error.code,
        )
    except Exception:
        logger.exception("call for %r ended unexpectedly", clinic_id)
    finally:
        # A failure here is a teardown failure, not a call failure: the
        # model's own connection is already stopped by `run`'s own
        # `finally` either way. Broad and swallowed on purpose -- a socket
        # whose transport is already gone can fail this in ways no
        # in-process test can produce, and none of them should crash the
        # connection's task over a step that has nothing left to do.
        try:
            await websocket.close()
        except Exception:
            logger.debug("closing the socket for %r failed", clinic_id, exc_info=True)


def _from_env(name: str) -> str | None:
    """Read `name`, treating blank or whitespace as unset."""
    return os.environ.get(name, "").strip() or None
