"""Tests for the deployed voice entrypoint in `agents/agentcore_app.py`.

Like `mic.py` this module is wiring and nothing else, so what is worth
pinning is not the FastAPI boilerplate but the ways the wiring could
quietly cost money or leak something it must not.

*A call that cannot work is refused at the handshake.* A missing
clinic id, an unknown clinic, and a clinic whose stored config this
process cannot resolve are all rejected after the first message is
read but before any Bedrock model is started -- the handshake-first
protocol (AgentCore's gateway strips custom query parameters, so the
first WebSocket frame is the only channel the browser can name its
clinic on; see the module docstring) means the socket is open by then,
but nothing is charged to a call that was never going to work.

*Only a stable code crosses the socket, never the failure's message.*
The far end of a rejected connection is an anonymous browser tab, not a
developer with a terminal -- the same distinction `results.py` already
draws for `ConfigurationError`, applied here to the whole call rather
than to one mid-call tool result.

*The wire protocol really is the one the vendored frontend expects.*
The last section drives whole calls through the real FastAPI app and
the real `BidiAgent` loop, over an in-process ASGI WebSocket (Starlette's
test client, not a socket or a network) -- so a transcript event
serialises to exactly `{"type": "bidi_transcript_stream", ...}`, and a
dict sent from the client reconstructs into what the model receives.
Nothing here opens a Bedrock connection; `HangingUpBidiModel`, imported
from `test_mic.py` rather than restated, stands where Nova Sonic will
and closes the connection itself once its script runs out -- which is
also what ends every test here without a manual timeout tripping.
"""

from __future__ import annotations

import concurrent.futures
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from agents.agentcore_app import CLOSE_POLICY_VIOLATION, app
from agents.orchestrator import OPENING_TURN, TEXT_MODEL_ENV
from agents.voice import VOICE_ID_ENV, VOICE_MODEL_ENV, VOICE_REGION_ENV
from tests.test_mic import HangingUpBidiModel
from tests.test_orchestrator import cosmetic_session, dental_session, tables  # noqa: F401
from tests.test_scheduling import COSMETIC_ID, DENTAL_ID, FakeClinicsTable, dental_clinic
from tools.errors import ConfigurationError, NotFoundError

DENTAL = DENTAL_ID
COSMETIC = COSMETIC_ID

# Long enough that a slow machine is not a failure, short enough that a
# handler which never closes the socket -- the one bug this suite exists
# to catch -- fails the test instead of hanging the run. `TestClient`'s
# websocket support has no timeout of its own, unlike the `asyncio.wait_for`
# every other suite in this package wraps a live call in.
CALL_TIMEOUT_SECONDS = 10.0

ENV_VARS = [TEXT_MODEL_ENV, VOICE_MODEL_ENV, VOICE_REGION_ENV, VOICE_ID_ENV]


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every variable this entrypoint (or the model it builds) reads."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _patch_voice_model(monkeypatch: pytest.MonkeyPatch, model: HangingUpBidiModel) -> None:
    """Stand `model` in for Nova Sonic, wherever `voice.py` builds one."""
    monkeypatch.setattr("agents.voice.build_nova_sonic_model", lambda **_: model)


def _with_timeout(fn: Any) -> Any:
    """Run `fn` on another thread and fail fast rather than hang the suite."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result(timeout=CALL_TIMEOUT_SECONDS)


def _collect_until_disconnect(session: Any) -> list[dict[str, Any]]:
    """Read every output event until the server closes the connection."""
    events = []
    try:
        while True:
            events.append(session.receive_json())
    except WebSocketDisconnect:
        return events


# --------------------------------------------------------------------------
# The health check
# --------------------------------------------------------------------------


def test_ping_reports_healthy() -> None:
    """What AgentCore Runtime polls before it routes a call here at all."""
    response = TestClient(app).get("/ping")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Healthy"
    assert isinstance(body["time_of_last_update"], int)


# --------------------------------------------------------------------------
# A call that cannot work is refused at the handshake
# --------------------------------------------------------------------------


def test_a_call_with_no_clinic_id_is_refused_at_the_handshake() -> None:
    """There is no default clinic and no way to ask the patient for one --
    a handshake that names no clinic is the connection itself being
    malformed."""
    with TestClient(app).websocket_connect("/ws") as session:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            session.send_json({"hello": "clinic?"})
            while True:
                session.receive_json()
    assert excinfo.value.code == CLOSE_POLICY_VIOLATION
    assert excinfo.value.reason == "missing_clinic_id"


def test_a_non_object_handshake_is_refused_the_same_way() -> None:
    """A JSON array or a bare string is not a clinic selection either --
    every malformed handshake is the one fact `missing_clinic_id` names."""
    with TestClient(app).websocket_connect("/ws") as session:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            session.send_json(["clinic-dental"])
            while True:
                session.receive_json()
    assert excinfo.value.code == CLOSE_POLICY_VIOLATION
    assert excinfo.value.reason == "missing_clinic_id"


def test_an_unknown_clinic_is_refused_at_the_handshake(tables) -> None:  # noqa: F811
    """`start_voice_call` reads the clinic row before anything else, so a
    bad id fails before a front desk with nothing behind it is ever
    built."""
    tables()
    with TestClient(app).websocket_connect("/ws") as session:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            session.send_json({"clinic_id": "clinic-nope"})
            while True:
                session.receive_json()
    assert excinfo.value.code == CLOSE_POLICY_VIOLATION
    assert excinfo.value.reason == NotFoundError.code


def test_a_malformed_clinic_config_is_refused_at_the_handshake(tables) -> None:  # noqa: F811
    """The same `ConfigurationError` `test_orchestrator.py` proves fails
    before the greeting over text, here over the socket that would have
    carried the call."""
    tables(clinics=FakeClinicsTable(dental_clinic() | {"timezone": "Mars/Olympus"}))
    with TestClient(app).websocket_connect("/ws") as session:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            session.send_json({"clinic_id": DENTAL})
            while True:
                session.receive_json()
    assert excinfo.value.code == CLOSE_POLICY_VIOLATION
    assert excinfo.value.reason == ConfigurationError.code


def test_only_the_stable_code_crosses_the_socket_not_the_message(tables) -> None:  # noqa: F811
    """The far end is an anonymous browser tab. `ConfigurationError`'s
    message quotes the bad attribute value -- that must stay server-side,
    exactly as `results.py` already keeps it out of a patient's ear."""
    tables(clinics=FakeClinicsTable(dental_clinic() | {"timezone": "Mars/Olympus"}))
    with TestClient(app).websocket_connect("/ws") as session:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            session.send_json({"clinic_id": DENTAL})
            while True:
                session.receive_json()
    assert excinfo.value.reason == "configuration_error"
    assert "Mars/Olympus" not in (excinfo.value.reason or "")


# --------------------------------------------------------------------------
# A whole call over the real FastAPI app and the real `BidiAgent` loop
# --------------------------------------------------------------------------


def test_the_agent_speaks_first_in_the_vendored_frontends_own_wire_shape(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`project-overview.md` -> Core User Flow has the Orchestrator greet
    the patient, sent the same way every interface sends it: the stage
    direction, not a greeting composed here. What comes back must
    serialise exactly the way `websocket-presigned.ts` already parses
    it -- `bidi_transcript_stream`, `text`, `role` -- since that frontend
    is what this entrypoint is built to answer."""
    tables()
    model = HangingUpBidiModel(("say", "Bright Smile Dental, how can I help?"))
    _patch_voice_model(monkeypatch, model)

    def call() -> list[dict[str, Any]]:
        with TestClient(app).websocket_connect("/ws") as session:
            session.send_json({"clinic_id": DENTAL})
            return _collect_until_disconnect(session)

    events = _with_timeout(call)
    assert model.text_sent == [OPENING_TURN]
    assert {
        "type": "bidi_transcript_stream",
        "text": "Bright Smile Dental, how can I help?",
        "role": "assistant",
    }.items() <= next(
        event for event in events if event.get("type") == "bidi_transcript_stream"
    ).items()


def test_what_the_patient_sends_reaches_the_model(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The socket is wired to the connection, not to nothing: a line the
    client sends after the greeting has to arrive at the model in the
    same shape `agent.send` documents for a WebSocket client's dict."""
    tables()
    model = HangingUpBidiModel(
        ("say", "Bright Smile Dental, how can I help?"),
        ("say", "Wednesday at nine it is."),
    )
    _patch_voice_model(monkeypatch, model)

    def call() -> None:
        with TestClient(app).websocket_connect("/ws") as session:
            session.send_json({"clinic_id": DENTAL})
            # The greeting's reply: exactly a transcript and a
            # response-complete event, before anything else is sent.
            session.receive_json()
            session.receive_json()
            session.send_json(
                {
                    "type": "bidi_text_input",
                    "text": "Wednesday at nine, please",
                    "role": "user",
                }
            )
            _collect_until_disconnect(session)

    _with_timeout(call)
    assert model.text_sent == [OPENING_TURN, "Wednesday at nine, please"]


def test_the_browser_disconnecting_mid_call_does_not_escape_the_handler(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A closed tab is the ordinary way a call ends, not a fault: the
    server is still waiting on `websocket.receive_json` when the browser
    goes away, and that must come back as a handled disconnect, not an
    exception that kills the connection's task."""
    tables()
    model = HangingUpBidiModel(
        ("say", "Bright Smile Dental, how can I help?"),
        ("say", "Wednesday at nine it is."),
    )
    _patch_voice_model(monkeypatch, model)

    def call() -> None:
        with TestClient(app).websocket_connect("/ws") as session:
            session.send_json({"clinic_id": DENTAL})
            session.receive_json()
            session.receive_json()
            # No more turns are consumed and nothing more is sent: the
            # `with` block's own exit is what disconnects, while the
            # model still has a second scripted turn it never gets to
            # play -- the server is genuinely still waiting on the
            # patient, exactly as when a tab is closed mid-call.

    _with_timeout(call)  # must return normally, not raise or hang


def test_the_clinic_answered_for_is_whichever_the_handshake_names(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`architecture.md` -> Auth and Access Model has the browser choose
    the clinic before the call starts. Naming the cosmetic clinic in the
    handshake must build the cosmetic clinic's front desk, proven by the
    prompt the model was started with rather than assumed from the code
    path."""
    tables()
    model = HangingUpBidiModel()
    _patch_voice_model(monkeypatch, model)

    def call() -> None:
        with TestClient(app).websocket_connect("/ws") as session:
            session.send_json({"clinic_id": COSMETIC})
            _collect_until_disconnect(session)

    _with_timeout(call)
    assert model.started is not None
    prompt = model.started["system_prompt"]
    assert cosmetic_session().clinic_name in prompt
    assert dental_session().clinic_name not in prompt
