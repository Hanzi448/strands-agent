# AgentCore Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A returning patient's voice call carries context from their previous calls, via one Bedrock AgentCore Memory resource holding a rolling summary per patient — read into the conversation when the tool layer identifies the caller, written when the call ends.

**Architecture:** A new `agents/memory.py` wraps the `bedrock-agentcore` SDK behind the same best-effort seam `tools/escalations.py` uses for SES (env-unset = no-op, failures swallowed). Identity is not a new mechanism: the scheduling tool wrappers call `session.note_patient(...)` when a booking result carries a `patient_id`, and `ClinicSession` fires a first-wins subscriber event. The read path is a `BidiInput` channel in `voice.py` (beside `Greeting`) that waits for that event, retrieves the summary off-loop, and sends it into the running agent as a stage direction. The write path is a `BidiOutput` transcript collector plus `record_call_end`, wired into `mic.py` and `agentcore_app.py` after `BidiAgent.run` returns. Infra: the memory resource is created in CDK (`aws_bedrockagentcore.Memory`, SUMMARIZATION strategy, actor-scoped namespace), its id passed as `CLINICPILOT_MEMORY_ID`, with `grant_read`/`grant_write` on the runtime role.

**Tech Stack:** Strands Agents SDK 1.54 (`BidiAgent`), `bedrock-agentcore` 1.23.0 (`bedrock_agentcore.memory.MemoryClient`), aws-cdk-lib 2.269.0 (`aws_cdk.aws_bedrockagentcore`), pytest (offline, fake clients).

**Spec:** `docs/superpowers/specs/2026-09-14-agentcore-memory-design.md`

## Global Constraints

- **Never run `git commit` or `git push`** (project CLAUDE.md). Every "commit" step below means: provide the suggested message text in a code block for the user to commit manually. Do not execute git commands.
- **All tests offline.** No test opens a Bedrock, AgentCore, or DynamoDB connection. The SDK client is faked at the `agents.memory._client` seam, exactly as table fakes stand in for DynamoDB.
- **Memory is best-effort at both ends.** A call must never fail, slow down noticeably, or change its answers because memory is unavailable. `retrieve_summary` failure → `None` → no injection; `record_conversation` failure → `False`. Neither ever raises into a call path.
- **`CLINICPILOT_MEMORY_ID` unset (or blank) = memory disabled**, and both read and write are no-ops that never construct a client. All 781 existing tests keep passing unchanged with it unset — it is unset by default in every offline test.
- **`backend/tools/` and `backend/lambda/` must never import `strands` or `bedrock_agentcore`** (`architecture.md` → System Boundaries). Enforced by a new AST drift-guard test.
- **Actor ids are `{clinic_id}#{patient_id}`** — the same tenant-safe composite as the `by-patient` index key. No API call can be given another clinic's actor without already holding that clinic's session (Invariant #1).
- **Transcripts only, never audio** (Invariant #4). Only final `BidiTranscriptStreamEvent` text is recorded.
- **CDK: no blanket `*` grants.** Memory permissions use the L2's own `grant_read`/`grant_write` (data-plane actions on the one memory ARN).
- Python 3.12, from `backend/` run tests as `python -m pytest tests/<file> -v` (the venv at `backend/.venv`).

## Resolved unknowns (verified against the installed SDK and CDK, 2026-09-14)

The spec's two verify-first items are settled; the code below uses the real surfaces:

- **SDK** (`bedrock-agentcore` 1.23.0, installed in `backend/.venv`): `bedrock_agentcore.memory.MemoryClient` with `retrieve_memories(memory_id, namespace, query, top_k)` (query is **required**; returns the raw `memoryRecordSummaries` list, empty list on error) and `create_event(memory_id, actor_id, session_id, messages)` where `messages` are `(text, role)` tuples with roles `"user"`/`"assistant"`. `save_conversation` exists but is deprecated in favour of `create_event`. Retrieved records carry their text at `record["content"]["text"]` (per the SDK's own `process_turn_with_llm` example).
- **The summary strategy's default namespace is session-scoped** (`/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}/`), which would defeat cross-call continuity. The fix: the CDK strategy declares a custom actor-scoped namespace template, `/summaries/actors/{actorId}/`, so every call's summary accumulates under one namespace per patient, and retrieval addresses that namespace directly.
- **CDK** (aws-cdk-lib 2.269.0): `aws_cdk.aws_bedrockagentcore` exists with an `Memory` L2 (`memory_name` must match `[a-zA-Z][a-zA-Z0-9_]{0,47}` — no hyphens), `ManagedMemoryStrategy(MemoryStrategyType.SUMMARIZATION, strategy_name=..., namespaces=[...])`, `memory.memory_id`, and `grant_read`/`grant_write` (grantee: the Runtime construct, which is IGrantable). So the memory resource is **created in CDK**, not via CLI.

## Scope note (deviation to flag to the user)

The spec's "The CLI" paragraph gives `cli.py` both paths but explicitly marks the write path cuttable. This plan wires **`mic.py` and `agentcore_app.py` only** — the two voice paths, one of which is the deployed demo. Reason: `orchestrator.start_call` returns a bare `Agent` with the session hidden (its docstring forbids callers building a `ClinicSession` by hand), so the CLI needs the same return-type change `start_voice_call` gets here plus a text-mode injection mechanism of its own — real churn for the one interface no requirement names. Flag this when presenting the plan; if the user wants the CLI too, it is a small follow-up unit.

---

### Task 1: `ClinicSession` learns who the patient is

**Files:**
- Modify: `backend/agents/session.py`
- Test: `backend/tests/test_agents_session.py` (existing file; append)

**Interfaces:**
- Consumes: nothing new.
- Produces (later tasks rely on these exactly):
  - `ClinicSession.patient_id -> str | None` (property)
  - `ClinicSession.note_patient(patient_id: str) -> None` — first non-blank identity wins; fires subscribers once
  - `ClinicSession.on_patient_identified(watcher: Callable[[str], None]) -> None`
  - `ClinicSession(clinic_id=..., clinic=...)` still constructs exactly as before (new field has a default).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_agents_session.py` (reuse its existing `dental_session` fixture; check its import list and add `ClinicSession` if the file constructs sessions directly):

```python
# --------------------------------------------------------------------------
# Who the patient turned out to be
# --------------------------------------------------------------------------


def test_a_session_starts_with_no_patient() -> None:
    """Identity is something the tool layer discovers mid-call, not
    something a session is born with."""
    assert dental_session().patient_id is None


def test_a_noted_patient_is_readable_on_the_session() -> None:
    session = dental_session()
    session.note_patient("pat_one")
    assert session.patient_id == "pat_one"


def test_the_first_identity_wins() -> None:
    """A reschedule after a booking names the same patient; a second,
    different id must not replace the first -- the call is one person."""
    session = dental_session()
    session.note_patient("pat_one")
    session.note_patient("pat_two")
    assert session.patient_id == "pat_one"


def test_a_blank_id_is_not_an_identity() -> None:
    session = dental_session()
    session.note_patient("   ")
    assert session.patient_id is None


def test_watchers_fire_exactly_once_with_the_id() -> None:
    """The memory channel subscribes once and must be released once --
    a second firing would inject the context twice."""
    session = dental_session()
    seen: list[str] = []
    session.on_patient_identified(seen.append)
    session.note_patient("pat_one")
    session.note_patient("pat_one")
    assert seen == ["pat_one"]


def test_a_watcher_registered_after_identification_is_not_called() -> None:
    """First identification wins, and has already happened: a late
    subscriber missed the event, exactly as the spec's at-most-once
    injection promises."""
    session = dental_session()
    session.note_patient("pat_one")
    seen: list[str] = []
    session.on_patient_identified(seen.append)
    assert seen == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_agents_session.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'patient_id'` (or `note_patient`).

- [ ] **Step 3: Implement**

In `backend/agents/session.py`:

Add to the imports at the top:

```python
from collections.abc import Callable
from dataclasses import dataclass, field
```

Add just above `ClinicSession`:

```python
@dataclass
class _PatientIdentity:
    """The one deliberately mutable corner of a frozen session.

    Who the call turned out to be is discovered mid-call by the tool
    layer, and who to tell about it is decided after construction -- so
    both live in this small holder the frozen dataclass owns rather than
    in rebinding the session itself. Same shape as `voice.Greeting`'s
    `asyncio.Event`: frozen outside, mutable inside.
    """

    patient_id: str | None = None
    watchers: list[Callable[[str], None]] = field(default_factory=list)
```

Add a field to `ClinicSession` (last, with a default, so existing keyword construction is unchanged) and the three members:

```python
    clinic_id: str
    clinic: dict[str, Any]
    identity: _PatientIdentity = field(
        default_factory=_PatientIdentity, repr=False, compare=False
    )
```

```python
    @property
    def patient_id(self) -> str | None:
        """The patient the tool layer identified, once it has.

        `None` until a tool result carries one -- an unidentified caller
        stays `None` for the whole call, and memory records nothing.
        """
        return self.identity.patient_id

    def on_patient_identified(self, watcher: Callable[[str], None]) -> None:
        """Register for the moment the caller becomes a known patient.

        Args:
            watcher: Called with the patient id, exactly once, from
                whatever thread the identifying tool ran on. Registering
                after the identification has already happened calls
                nothing.
        """
        self.identity.watchers.append(watcher)

    def note_patient(self, patient_id: str) -> None:
        """Record who this call turned out to be, if anyone has yet.

        First non-blank identity wins; later calls do not replace it and
        do not re-fire the watchers. Blank is not an identity.

        Args:
            patient_id: The `patient_id` a tool result carried.
        """
        patient_id = patient_id.strip()
        if not patient_id or self.identity.patient_id is not None:
            return
        self.identity.patient_id = patient_id
        for watcher in self.identity.watchers:
            watcher(patient_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agents_session.py -v`
Expected: PASS (all, old and new).

- [ ] **Step 5: Run the whole suite (nothing else may shift)**

Run: `python -m pytest -q`
Expected: 787 passed (781 + 6).

- [ ] **Step 6: Suggested commit message**

```text
feat: let a clinic session note and announce the patient it identified

A booking result carries a patient_id; the session now remembers the
first one it sees and fires a one-shot subscriber event, so the memory
layer (next) can react without any new identity mechanism.

Completes the session half of progress-tracker.md Next Up #2.
```

---

### Task 2: `agents/memory.py` — the client seam, plus the boundary drift guard

**Files:**
- Create: `backend/agents/memory.py`
- Create: `backend/tests/test_agents_memory.py`
- Create: `backend/tests/test_boundaries.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Consumes: `ClinicSession.patient_id`, `.clinic_id` (Task 1; only `record_call_end` in Task 4 uses them).
- Produces (later tasks rely on these exactly):
  - `MEMORY_ID_ENV: str = "CLINICPILOT_MEMORY_ID"`
  - `NAMESPACE_TEMPLATE: str = "/summaries/actors/{actor_id}/"`
  - `actor_id(clinic_id: str, patient_id: str) -> str`
  - `retrieve_summary(actor: str) -> str | None`
  - `record_conversation(actor: str, turns: list[tuple[str, str]]) -> bool` — turns are `(text, role)` with roles `"user"`/`"assistant"`
  - `_client() -> Any` — the seam tests monkeypatch
  - (Task 4 adds `TranscriptCollector` and `record_call_end` to this same module.)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agents_memory.py`:

```python
"""Tests for the AgentCore Memory seam in `agents/memory.py`.

The module is the `tools/escalations.py` SES pattern applied to memory:
an environment variable is the enable, everything the AWS SDK does sits
 behind a one-function seam, and no failure of the service may ever
reach a patient on a call. So what is pinned here is the seam's
contract: disabled means no-op and no client, failures mean None/False
rather than exceptions, and the actor composite is the tenant-safe one
the `by-patient` index already uses.
"""

from __future__ import annotations

from typing import Any

import pytest

from agents import memory


class FakeMemoryClient:
    """Stands where `MemoryClient` will, recording what it was asked."""

    def __init__(
        self,
        *,
        records: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.records = records or []
        self.error = error
        self.events: list[dict[str, Any]] = []

    def retrieve_memories(self, **kwargs: Any) -> list[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        self.retrieved = kwargs
        return self.records

    def create_event(self, **kwargs: Any) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        self.events.append(kwargs)
        return {"memoryId": kwargs["memoryId"]}


@pytest.fixture(autouse=True)
def _no_ambient_memory_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Memory off by default, as it is for every other test in the repo."""
    monkeypatch.delenv(memory.MEMORY_ID_ENV, raising=False)


def _bomb() -> Any:
    raise AssertionError("no client may be built while memory is disabled")


# --------------------------------------------------------------------------
# The actor: one tenant-safe composite, spelled once
# --------------------------------------------------------------------------


def test_the_actor_is_the_clinic_patient_composite() -> None:
    """The same key shape the `by-patient` index uses: one patient's
    memory is unreachable from another clinic's session by construction
    (`architecture.md` -> Invariants #1)."""
    assert memory.actor_id("clinic-dental", "pat_one") == "clinic-dental#pat_one"


# --------------------------------------------------------------------------
# Disabled means no-op, and no client
# --------------------------------------------------------------------------


def test_an_unconfigured_memory_retrieves_nothing() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(memory, "_client", _bomb)
    try:
        assert memory.retrieve_summary("clinic-dental#pat_one") is None
    finally:
        monkeypatch.undo()


def test_an_unconfigured_memory_records_nothing() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(memory, "_client", _bomb)
    try:
        assert memory.record_conversation("clinic-dental#pat_one", [("hi", "user")]) is False
    finally:
        monkeypatch.undo()


def test_a_blank_memory_id_is_not_a_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exported-but-empty variable is how a shell profile sets
    nothing -- the same rule every other env reader here follows."""
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "   ")
    monkeypatch.setattr(memory, "_client", _bomb)
    assert memory.retrieve_summary("clinic-dental#pat_one") is None
    assert memory.record_conversation("clinic-dental#pat_one", [("hi", "user")]) is False


# --------------------------------------------------------------------------
# Retrieval: the summary, or nothing
# --------------------------------------------------------------------------


def test_the_summary_is_the_records_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMemoryClient(
        records=[{"content": {"text": " Calls about cleanings; prefers mornings. "}}]
    )
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)

    summary = memory.retrieve_summary("clinic-dental#pat_one")

    assert summary == "Calls about cleanings; prefers mornings."
    assert client.retrieved == {
        "memory_id": "mem_one",
        "namespace": "/summaries/actors/clinic-dental#pat_one/",
        "query": memory.RETRIEVAL_QUERY,
        "top_k": 3,
    }


def test_an_empty_memory_is_a_first_time_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMemoryClient(records=[])
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)
    assert memory.retrieve_summary("clinic-dental#pat_one") is None


def test_records_without_text_are_skipped_not_crashed_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMemoryClient(
        records=[{"content": {}}, {"content": {"text": "  "}}, {"score": 0.4}]
    )
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)
    assert memory.retrieve_summary("clinic-dental#pat_one") is None


def test_a_retrieval_failure_is_none_never_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMemoryClient(error=RuntimeError("throttled"))
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)
    assert memory.retrieve_summary("clinic-dental#pat_one") is None


# --------------------------------------------------------------------------
# Recording: the call's turns, or nothing
# --------------------------------------------------------------------------


def test_the_calls_turns_are_recorded_under_the_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMemoryClient()
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)
    turns = [
        ("Nine on Wednesday, please.", "user"),
        ("That is booked for nine.", "assistant"),
    ]

    assert memory.record_conversation("clinic-dental#pat_one", turns) is True

    assert len(client.events) == 1
    event = client.events[0]
    assert event["memoryId"] == "mem_one"
    assert event["actorId"] == "clinic-dental#pat_one"
    assert event["messages"] == turns
    assert event["sessionId"]  # a fresh id per call, never reused


def test_an_empty_call_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeMemoryClient()
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)
    assert memory.record_conversation("clinic-dental#pat_one", []) is False
    assert client.events == []


def test_a_recording_failure_is_false_never_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMemoryClient(error=RuntimeError("gone"))
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)
    assert memory.record_conversation("clinic-dental#pat_one", [("hi", "user")]) is False
```

Create `backend/tests/test_boundaries.py`:

```python
"""The system boundary, as a test rather than a convention.

`architecture.md` -> System Boundaries: `backend/tools/` (and the
Lambda handlers that call the same functions) must not depend on Strands
or AgentCore -- a data-mutating Lambda has to install without the agent
framework, and business logic has to be reachable from both the live
agent and the background job unchanged. Nothing enforced that before;
`agents/memory.py` adds a second framework package to the tree, which
is the moment the guard starts earning its keep.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# The agent framework packages the tool layer must never import.
FORBIDDEN_ROOTS = frozenset({"strands", "bedrock_agentcore"})

# The packages that must stay framework-free.
GUARDED_DIRS = ("tools", "lambda")


def _imported_roots(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [(node.module or "").split(".")[0]] if node.module else ["."]
    return []


def test_the_tool_layer_imports_no_agent_framework() -> None:
    for directory in GUARDED_DIRS:
        for path in sorted((BACKEND / directory).glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for root in _imported_roots(node):
                    assert root not in FORBIDDEN_ROOTS, (
                        f"{directory}/{path.name} imports {root!r}: business logic"
                        " must stay reachable without the agent framework"
                    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_agents_memory.py tests/test_boundaries.py -v`
Expected: memory tests FAIL with `ModuleNotFoundError: No module named 'agents.memory'` (or ImportError); the boundary test PASSES already (nothing in `tools/` imports the frameworks yet — it is a guard, not a change).

- [ ] **Step 3: Implement `agents/memory.py`**

```python
"""The AgentCore Memory seam: one rolling summary per patient.

`architecture.md` -> Stack names Bedrock AgentCore Memory for "per-
patient conversation state across voice sessions", and the design in
`docs/superpowers/specs/2026-09-14-agentcore-memory-design.md` settles
what that means: one memory resource whose SUMMARIZATION strategy keeps
a rolling plain-language summary per patient, written when a call ends
and read once the tool layer has identified the caller.

This module is the `tools/escalations.py` SES pattern applied to
memory, because the rule is the same: **memory is best-effort at both
ends and must never be why a call fails**. A retrieval that cannot
happen makes the caller a first-time patient; a recording that cannot
happen leaves the summary one call staler. Neither raises into a call
path, and neither is even attempted unless `MEMORY_ID_ENV` is set --
the same "an enable, not a dependency" choice the escalation email
made, for the same reason: the demo must run with memory off.

The actor id is `{clinic_id}#{patient_id}` -- the composite the
`by-patient` index uses (`schema.clinic_patient_key`), so a patient's
memory is scoped to their clinic by construction rather than by a
filter (`architecture.md` -> Invariants #1). Identity itself is not
re-invented here: the session's `patient_id` is whatever the tool layer
already resolved from phone and name.

Only transcripts ever leave this module -- final text both sides of the
call, never audio (`architecture.md` -> Invariants #4).

The SDK is imported lazily and built behind `_client`, the seam the
tests fake, so importing this module requires nothing that is not
already required by `backend/agents/` as a whole.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Final

from .session import ClinicSession

logger = logging.getLogger(__name__)

# Unset (or blank) means memory is disabled and both read and write are
# no-ops -- set by `agent_stack.py` to the deployed memory resource's id.
MEMORY_ID_ENV: Final[str] = "CLINICPILOT_MEMORY_ID"

# Where a patient's summary lives. The strategy the CDK declares writes
# to `/summaries/actors/{actorId}/` -- actor-scoped, *not* session-
# scoped like the strategy's default, which is what makes one call's
# summary visible to the next. This constant is the client-side spelling
# of the same path: the `{actor_id}` placeholder is filled with the
# composite `actor_id` builds, and `tests/test_schema_matches_infra.py`
# fails if it ever disagrees with the stack's own template.
NAMESPACE_TEMPLATE: Final[str] = "/summaries/actors/{actor_id}/"

# `MemoryClient.retrieve_memories` requires a search query even for an
# exact-namespace lookup; with one summary record in the namespace the
# query does no ranking work, it only has to exist.
RETRIEVAL_QUERY: Final[str] = "summary of this patient's previous calls"

# How many records to ask for: the namespace holds the one rolling
# summary; a handful covers a strategy that ever keeps more without
# paying for a wide net.
RETRIEVAL_TOP_K: Final[int] = 3


def actor_id(clinic_id: str, patient_id: str) -> str:
    """The memory actor for one patient at one clinic.

    The same `{clinic}#{patient}` composite the `by-patient` index keys
    on, spelled once so no caller builds it by hand.
    """
    return f"{clinic_id}#{patient_id}"


def retrieve_summary(actor: str) -> str | None:
    """One patient's current summary, or `None`.

    `None` for every outcome that is not "a summary came back": memory
    disabled, nothing recorded yet, or the service unreachable. The
    caller treats all three the same way -- the call proceeds as a
    first-time caller.

    Args:
        actor: The composite from `actor_id`.

    Returns:
        The summary text, or `None`. Never raises.
    """
    memory_id = _memory_id()
    if memory_id is None:
        return None
    try:
        records = _client().retrieve_memories(
            memory_id=memory_id,
            namespace=NAMESPACE_TEMPLATE.format(actor_id=actor),
            query=RETRIEVAL_QUERY,
            top_k=RETRIEVAL_TOP_K,
        )
    except Exception:
        # Best-effort by design (see the module docstring); the log is
        # where a deployment fault belongs, not the patient's ear.
        logger.warning("could not retrieve memory for %r", actor, exc_info=True)
        return None
    texts = [text for text in (_record_text(record) for record in records) if text]
    return " ".join(texts) or None


def record_conversation(actor: str, turns: list[tuple[str, str]]) -> bool:
    """Record one call's final transcripts under the patient's actor.

    Args:
        actor: The composite from `actor_id`.
        turns: The call's final turns in order, as `(text, role)` with
            roles `"user"` and `"assistant"` -- what
            `TranscriptCollector` hands over.

    Returns:
        Whether the event was created. Never raises.
    """
    memory_id = _memory_id()
    if memory_id is None or not turns:
        return False
    try:
        _client().create_event(
            memory_id=memory_id,
            actor_id=actor,
            # A fresh id per call: each call is its own AgentCore
            # session, which is what lets the strategy consolidate them
            # into one rolling summary per actor.
            session_id=uuid.uuid4().hex,
            messages=turns,
        )
        return True
    except Exception:
        logger.warning("could not record the call for %r", actor, exc_info=True)
        return False


def _memory_id() -> str | None:
    """The deployed memory resource id, or `None` when memory is off."""
    return os.environ.get(MEMORY_ID_ENV, "").strip() or None


def _client() -> Any:
    """Build the AgentCore Memory client, importing the SDK here.

    The seam the tests fake: nothing else in this module touches the
    SDK, so a fake here is a fake of the whole service boundary.
    """
    from bedrock_agentcore.memory import MemoryClient

    return MemoryClient()


def _record_text(record: Any) -> str:
    """The text of one retrieved record, or `""`.

    Defensive on purpose: the record is the service's response shape,
    and a field that moves must cost a missing summary, not a crash
    mid-call.
    """
    if not isinstance(record, dict):
        return ""
    content = record.get("content")
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    payload = record.get("payload")
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return ""
```

Note: the `ClinicSession` import is only used by `record_call_end` in Task 4 — if the linter complains in this task, move the import to Task 4 (or guard it under `TYPE_CHECKING` there). Prefer adding it in Task 4.

- [ ] **Step 4: Pin the dependency**

In `backend/requirements.txt`, append:

```text
# `agents/memory.py`: the AgentCore Memory client for per-patient call
# summaries. Imported lazily there, so `tools/` and the Lambda handlers
# still install without it (`tests/test_boundaries.py` holds that line),
# but the deployed container needs it present.
bedrock-agentcore>=1.23
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agents_memory.py tests/test_boundaries.py -v`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q`
Expected: 781 + 16 = 797 passed (6 from Task 1 included; adjust count to what Task 1 actually added).

- [ ] **Step 7: Suggested commit message**

```text
feat: add the AgentCore Memory client seam, disabled by default

One module, agents/memory.py: actor composite, summary retrieval and
turn recording behind a one-function client seam, no-ops unless
CLINICPILOT_MEMORY_ID is set, failures swallowed at both ends. Plus an
AST drift guard keeping tools/ and lambda/ free of agent-framework
imports, and the pinned bedrock-agentcore dependency.

Part of progress-tracker.md Next Up #2.
```

---

### Task 3: The scheduling wrappers announce who the patient is

**Files:**
- Modify: `backend/agents/scheduling_agent.py`
- Test: `backend/tests/test_scheduling_agent.py` (existing; append)

**Interfaces:**
- Consumes: `ClinicSession.note_patient` (Task 1).
- Produces: no new public surface — the observable effect is `session.patient_id` becoming set after a booking, moving or cancelling wrapper returns.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_scheduling_agent.py`:

```python
# --------------------------------------------------------------------------
# The wrappers tell the session who the patient is
# --------------------------------------------------------------------------


def test_a_booking_identifies_the_patient_on_the_session(tables) -> None:
    """The booking result carries a patient_id; the session is where the
    rest of the call reads it from. This is the single identity
    mechanism -- no phone-number lookup is invented for memory's sake."""
    tables()
    session = dental_session()
    result = tool_named(session, "book_appointment")(
        starts_at="2026-07-01T08:00:00Z",
        service="checkup",
        patient_name=NAME,
        patient_phone="555 123 4567",
    )
    assert result["status"] == "scheduled"
    assert session.patient_id == result["patient"]["patient_id"]


def test_rescheduling_identifies_the_patient_the_same_way(tables) -> None:
    tables(appointment_items=one_checkup(), patient_items=[patient()])
    session = dental_session()
    tool_named(session, "reschedule_appointment")(
        patient_phone=PHONE,
        patient_name=NAME,
        new_starts_at=TEN,
    )
    assert session.patient_id == PATIENT_ID


def test_cancelling_identifies_the_patient_the_same_way(tables) -> None:
    tables(appointment_items=one_checkup(), patient_items=[patient()])
    session = dental_session()
    tool_named(session, "cancel_appointment")(
        patient_phone=PHONE, patient_name=NAME
    )
    assert session.patient_id == PATIENT_ID


def test_checking_availability_identifies_nobody(tables) -> None:
    """No patient in the result, no identity on the session -- a caller
    who only asks about times stays anonymous, and memory records
    nothing for them."""
    tables()
    session = dental_session()
    tool_named(session, "check_availability")(
        date=WEDNESDAY, service="checkup"
    )
    assert session.patient_id is None


def test_a_refused_booking_still_identifies_the_patient(tables) -> None:
    """`call` returns an error_result on refusal, but the tool layer
    raised before any patient existed in that case -- this pins that a
    *successful-looking* path with no patient in it is simply ignored."""
    tables(appointment_items=one_checkup())
    session = dental_session()
    result = tool_named(session, "book_appointment")(
        starts_at=NINE,
        service="checkup",
        patient_name="Kit Rowe",
        patient_phone="555 999 0000",
    )
    assert result["status"] == "error"
    assert session.patient_id is None
```

Add `PATIENT_ID` to the existing `from tests.test_appointments import ...` block if it is not already imported.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_scheduling_agent.py -v -k patient`
Expected: FAIL — `session.patient_id` stays `None` in the first three tests.

- [ ] **Step 3: Implement**

In `backend/agents/scheduling_agent.py`:

Extend the `tools.schema` import (it currently has none — add):

```python
from tools.schema import PatientAttrs
```

Add a module-level helper below `scheduling_tools`'s docstring-placed constants, above `scheduling_tools`:

```python
def _note_patient(session: ClinicSession, result: Any) -> None:
    """Tell the session who the call turned out to be, if a tool learned it.

    The booking, moving and cancelling results carry a `patient`
    summary; `ClinicSession.note_patient` keeps the first one and
    ignores the rest. Kept here rather than in `backend/tools/`
    because it is the *session* being told, and the tool layer knows
    nothing about sessions (`architecture.md` -> System Boundaries).
    """
    if not isinstance(result, dict):
        return
    patient = result.get("patient")
    if not isinstance(patient, dict):
        return
    patient_id = patient.get(PatientAttrs.PATIENT_ID)
    if isinstance(patient_id, str) and patient_id.strip():
        session.note_patient(patient_id)
```

In each of the three mutation wrappers inside `scheduling_tools`, change the tail from `return call(...)` to note-then-return. For `book_appointment`:

```python
        result = call(
            "book_appointment",
            booking.book_appointment,
            clinic_id=clinic_id,
            starts_at=starts_at,
            service=service,
            patient_name=patient_name,
            patient_phone=patient_phone,
            patient_email=patient_email,
            notes=notes,
        )
        _note_patient(session, result)
        return result
```

The same shape for `reschedule_appointment` and `cancel_appointment` (keep each existing `call(...)` argument list exactly as it is). `check_availability` is unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_scheduling_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: all pass (5 new).

- [ ] **Step 6: Suggested commit message**

```text
feat: scheduling wrappers note the patient the call turned out to be

A booking, move or cancellation result carries a patient summary; the
wrapper now hands its patient_id to the session, first identity wins,
so the memory layer can key on the tool layer's existing identity
resolution instead of inventing one.

Part of progress-tracker.md Next Up #2.
```

---

### Task 4: The write path — `TranscriptCollector` and `record_call_end`

**Files:**
- Modify: `backend/agents/memory.py`
- Test: `backend/tests/test_agents_memory.py` (append)

**Interfaces:**
- Consumes: `record_conversation`, `actor_id` (Task 2); `ClinicSession.patient_id` / `.clinic_id` (Task 1).
- Produces:
  - `TranscriptCollector` — a `BidiOutput`; `.turns: list[tuple[str, str]]` of `(text, role)` finals in call order
  - `record_call_end(session: ClinicSession, turns: list[tuple[str, str]]) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_agents_memory.py` (imports to add at the top of the file: `from agents.memory import TranscriptCollector, record_call_end` — fold into the existing `from agents import memory` usage as needed — plus `from agents.session import ClinicSession`, `from tests.test_orchestrator import dental_session`, `from tests.test_scheduling import DENTAL_ID`, and `from strands.experimental.bidi import BidiTranscriptStreamEvent`):

```python
# --------------------------------------------------------------------------
# The transcript collector: finals only, both sides, in order
# --------------------------------------------------------------------------


def _transcript(text: str, role: str, *, final: bool = True) -> Any:
    return BidiTranscriptStreamEvent(
        delta={"text": text}, text=text, role=role, is_final=final
    )


def _collected(*events: Any) -> list[tuple[str, str]]:
    collector = memory.TranscriptCollector()

    async def run() -> None:
        for event in events:
            await collector(event)

    import asyncio

    asyncio.run(run())
    return collector.turns


def test_final_transcripts_are_kept_in_order_both_sides() -> None:
    turns = _collected(
        _transcript("Nine on Wednesday, please.", "user"),
        _transcript("That is booked for nine.", "assistant"),
    )
    assert turns == [
        ("Nine on Wednesday, please.", "user"),
        ("That is booked for nine.", "assistant"),
    ]


def test_interim_transcripts_are_not_kept() -> None:
    """Only finals are recorded: an interim is half a sentence the
    patient had not finished, and it would double every turn."""
    turns = _collected(
        _transcript("Nine on Wed...", "user", final=False),
        _transcript("Nine on Wednesday, please.", "user"),
    )
    assert turns == [("Nine on Wednesday, please.", "user")]


def test_blank_transcripts_are_not_turns() -> None:
    assert _collected(_transcript("   ", "assistant")) == []


def test_events_that_are_not_transcripts_are_ignored() -> None:
    assert _collected({"type": "usage"}, "not an event at all") == []


# --------------------------------------------------------------------------
# Recording at call end
# --------------------------------------------------------------------------


def test_an_ended_call_records_under_the_clinic_prefixed_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeMemoryClient()
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)
    session = dental_session()
    session.note_patient("pat_one")

    turns = [("Nine on Wednesday, please.", "user"), ("Booked.", "assistant")]
    assert memory.record_call_end(session, turns) is True

    assert len(client.events) == 1
    assert client.events[0]["actorId"] == f"{DENTAL_ID}#pat_one"
    assert client.events[0]["messages"] == turns


def test_an_unidentified_call_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spec's rule: a call where the patient was never identified
    records nothing -- there is no actor to attribute it to."""
    client = FakeMemoryClient()
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)

    assert memory.record_call_end(dental_session(), [("hello", "user")]) is False
    assert client.events == []


def test_a_disabled_memory_records_nothing_at_call_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory, "_client", _bomb)
    session = dental_session()
    session.note_patient("pat_one")
    assert memory.record_call_end(session, [("hello", "user")]) is False
```

(`dental_session` requires the `tables` fixture in its importing suites — check how `tests/test_agents_session.py` builds its sessions and use the same fixture there; if `dental_session()` in that file needs `tables`, add the fixture argument to these tests too.)

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_agents_memory.py -v`
Expected: FAIL — `AttributeError: module 'agents.memory' has no attribute 'TranscriptCollector'`.

- [ ] **Step 3: Implement**

Append to `backend/agents/memory.py`:

```python
class TranscriptCollector:
    """A `BidiOutput` that keeps the call's final transcripts, both sides.

    The recording half of the write path: the voice interfaces already
    receive final transcript events for the patient and the agent, so
    collecting them is an output channel beside the speakers -- the
    same position `mic.CallMonitor` prints from. What it holds is the
    whole of what memory ever persists: text, never audio
    (`architecture.md` -> Invariants #4).
    """

    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []

    async def __call__(self, event: Any) -> None:
        """Keep one final transcript turn, if that is what this event is."""
        from strands.experimental.bidi import BidiTranscriptStreamEvent

        if not isinstance(event, BidiTranscriptStreamEvent) or not event.is_final:
            return
        text = event.text.strip()
        if text:
            self.turns.append((text, event.role))


def record_call_end(session: ClinicSession, turns: list[tuple[str, str]]) -> bool:
    """Record one ended call, if there is a patient to attribute it to.

    The single write entry point both voice interfaces call when
    `BidiAgent.run` has returned -- one implementation, so the
    microphone and the browser cannot drift. Best-effort like everything
    else here: a call with no identified patient records nothing, and a
    recording that cannot happen is `False`, never an exception in a
    call-end path.

    Args:
        session: The call's session; supplies the clinic and, if the
            tool layer identified one, the patient.
        turns: The collected final turns, as `(text, role)`.

    Returns:
        Whether the call was recorded.
    """
    if session.patient_id is None:
        return False
    return record_conversation(
        actor_id(session.clinic_id, session.patient_id), turns
    )
```

(Move the `from .session import ClinicSession` import to module scope here if it was deferred in Task 2.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agents_memory.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: all pass (7 new since Task 2).

- [ ] **Step 6: Suggested commit message**

```text
feat: collect the call's transcripts and record them at call end

TranscriptCollector is a BidiOutput keeping final turns both sides;
record_call_end is the one shared write entry point the voice
interfaces call when the call is over -- no patient, no recording,
and never an exception in a call-end path.

Part of progress-tracker.md Next Up #2.
```

---

### Task 5: The read path — `MemoryContext` in `voice.py`, and `start_voice_call` exposing the session

**Files:**
- Modify: `backend/agents/voice.py`
- Test: `backend/tests/test_voice.py` (existing; append + update two call sites)

**Interfaces:**
- Consumes: `memory.retrieve_summary`, `memory.actor_id` (Task 2); `ClinicSession.on_patient_identified` / `.patient_id` (Task 1).
- Produces:
  - `MEMORY_CONTEXT_TEMPLATE: str` — `"...{summary}..."`
  - `MemoryContext(BidiInput)` — constructor `MemoryContext(session: ClinicSession)`
  - `VoiceCall` — frozen dataclass with `.agent: BidiAgent` and `.session: ClinicSession`
  - `start_voice_call(...) -> VoiceCall` (was `-> BidiAgent`) — same keyword arguments
  - `build_voice_agent` unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_voice.py`. New imports at the top: `import contextlib`, `from agents import memory`, and `MemoryContext`, `MEMORY_CONTEXT_TEMPLATE`, `VoiceCall` added to the existing `from agents.voice import ...` block.

```python
# --------------------------------------------------------------------------
# A returning patient's context, injected once the call knows who it is
# --------------------------------------------------------------------------


def _drive_with_context(
    agent: Any, session: ClinicSession, turn: str, model: ScriptedBidiModel
) -> None:
    """Run one manual pump of a call that includes the memory channel.

    `take_call` cannot be used here: the memory channel is an *input*
    that `BidiAgent.run` would pump, and this drive owns the equivalent
    pieces itself -- start the channel (which subscribes), pump it in a
    task, and stop it on the way out the way `run`'s own `finally`
    would.
    """

    async def drive() -> None:
        await agent.start()
        context = MemoryContext(session)
        await context.start(agent)
        pump = asyncio.create_task(context())
        try:
            await agent.send(turn)
            async for event in agent.receive():
                if isinstance(event, BidiResponseCompleteEvent) and any(
                    text.startswith("Context from this patient's previous calls:")
                    for text in model.text_sent
                ):
                    return
        finally:
            await context.stop()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
            await agent.stop()

    asyncio.run(asyncio.wait_for(drive(), CALL_TIMEOUT_SECONDS))


def test_a_returning_patients_summary_reaches_the_model_once(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The call's context injection: the booking identifies the patient
    mid-call, the channel retrieves the summary and sends it into the
    running conversation as a stage direction -- exactly once, and never
    as part of the system prompt."""
    tables()
    monkeypatch.setattr(
        memory,
        "retrieve_summary",
        lambda actor: "Calls about cleanings; prefers mornings.",
    )
    session = dental_session()
    voice_model = ScriptedBidiModel(
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
        # The context turn releases one more scripted response, so the
        # drive has something to stop on.
        ("say", "Understood."),
    )
    agent = build_voice_agent(
        session, voice_model=voice_model, text_model=booking_text_script()
    )

    _drive_with_context(
        agent, session, "Nine on Wednesday for a check-up, please.", voice_model
    )

    contexts = [
        text
        for text in voice_model.text_sent
        if text.startswith("Context from this patient's previous calls:")
    ]
    assert contexts == [
        MEMORY_CONTEXT_TEMPLATE.format(summary="Calls about cleanings; prefers mornings.")
    ]
    # And it is context, not configuration: the prompt the call was
    # opened with is untouched.
    assert "Context from this patient's previous calls" not in (
        voice_model.started["system_prompt"] or ""
    )


def test_a_first_time_caller_gets_no_context_at_all(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No summary recorded, or memory unreachable: nothing is sent, and
    the call proceeds exactly as it would have without memory."""
    tables()
    monkeypatch.setattr(memory, "retrieve_summary", lambda actor: None)
    session = dental_session()
    voice_model = ScriptedBidiModel(("say", "Bright Smile Dental, how can I help?"))
    agent = build_voice_agent(session, voice_model=voice_model)

    _drive_with_context(agent, session, "Hello?", voice_model)

    assert not [
        text
        for text in voice_model.text_sent
        if text.startswith("Context from this patient's previous calls:")
    ]


def test_a_call_that_never_identifies_anybody_sends_nothing(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No booking, no identity, no retrieval -- the channel stays
    silent for the whole call rather than inventing a fallback actor."""
    tables()

    def _bomb(actor: str) -> str | None:
        raise AssertionError("retrieve_summary must not run for an unidentified caller")

    monkeypatch.setattr(memory, "retrieve_summary", _bomb)
    session = dental_session()
    voice_model = ScriptedBidiModel(("say", "Bright Smile Dental, how can I help?"))
    agent = build_voice_agent(session, voice_model=voice_model)

    _drive_with_context(agent, session, "Hello?", voice_model)

    assert len(voice_model.text_sent) == 1  # the patient's turn, nothing else


def test_starting_a_call_exposes_the_session_alongside_the_agent(
    tables,  # noqa: F811
) -> None:
    """The interfaces need the session to wire the memory channels, and
    this is the one entry point that already builds it -- so it hands
    both back rather than making a caller rebuild what it checked."""
    tables()
    call = start_voice_call(DENTAL_ID, voice_model=ScriptedBidiModel())
    assert isinstance(call, VoiceCall)
    assert call.session.clinic_id == DENTAL_ID
    assert dental_session().clinic_name in (call.agent.system_prompt or "")
```

Update the existing test that unpacks the agent directly (in "Opening a call" section):

```python
def test_a_voice_call_reads_its_clinic_before_anything_is_connected(
    tables,  # noqa: F811
) -> None:
    tables()
    call = start_voice_call(DENTAL_ID, voice_model=ScriptedBidiModel())
    assert dental_session().clinic_name in (call.agent.system_prompt or "")
    assert call.agent.tool_names == ASSISTANTS
```

(The two parametrized refusal tests and the broken-config test only assert that `start_voice_call` raises — unchanged.)

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_voice.py -v`
Expected: FAIL — `ImportError: cannot import name 'MemoryContext'`, and the `start_voice_call` test fails on the missing `VoiceCall`.

- [ ] **Step 3: Implement**

In `backend/agents/voice.py`:

Add imports:

```python
from dataclasses import dataclass
```

and, beside the existing `.orchestrator` / `.session` imports:

```python
from . import memory
```

Add after `VOICE_PROMPT_SUFFIX`:

```python
# How the retrieved summary is handed to the running conversation: a
# stage direction in the same register as `OPENING_TURN` -- context the
# model may use, not a turn it must answer. The model is told not to
# mention it because a patient who hears "as we discussed last time"
# from a summary they never saw is a patient who stops trusting the
# front desk.
MEMORY_CONTEXT_TEMPLATE: Final[str] = (
    "Context from this patient's previous calls: {summary}."
    " Use it if relevant; do not mention that you were given it."
)
```

Add after `build_voice_agent` (before `start_voice_call`):

```python
@dataclass(frozen=True)
class VoiceCall:
    """One opened voice call: the agent, and the session underneath it.

    The interfaces that drive a call need both -- the agent to run, the
    session to wire the memory channels (`MemoryContext` subscribes to
    it, `record_call_end` reads it) -- and this is the one object that
    has both without any caller rebuilding a `ClinicSession` by hand
    and skipping the checks `ClinicSession.start` runs.
    """

    agent: BidiAgent
    session: ClinicSession
```

Change `start_voice_call`'s signature, docstring Returns section, and body:

```python
def start_voice_call(
    clinic_id: str,
    *,
    voice_model: BidiModel | str | None = None,
    text_model: Model | str | None = None,
) -> VoiceCall:
    """Open a voice call: read the clinic, then build its front desk.

    ... (existing docstring, with Returns replaced:) ...

    Returns:
        A `VoiceCall`: a fresh `BidiAgent` for this call, holding no
        conversation yet and with no connection open, and the
        `ClinicSession` it is pinned to.

    Raises: (unchanged)
    """
    session = ClinicSession.start(clinic_id)
    return VoiceCall(
        agent=build_voice_agent(
            session, voice_model=voice_model, text_model=text_model
        ),
        session=session,
    )
```

Add the channel, after the `Greeting` class:

```python
class MemoryContext(BidiInput):
    """Send a returning patient's summary into the call, once.

    An input *channel* for the same reason `Greeting` is one:
    `BidiAgent.run` owns the connection and pumps every channel on the
    event loop, and this channel has something to say only after the
    tool layer identifies the patient -- which happens on a worker
    thread, mid-call. So `start` subscribes to the session's identity
    event and bridges the thread onto the loop; `__call__` waits for
    that, retrieves the summary *off* the loop (a network call the
    patient would otherwise hear as a pause), and sends it with the
    same `agent.send` mechanism the greeting uses.

    Says nothing at all when the patient is never identified, when
    memory is disabled, or when no summary exists -- a first-time
    caller's call is byte-for-byte the call memory would not have been
    part of. At most one injection per call: the session's event fires
    at most once, and this channel then blocks like `Greeting` does.
    """

    def __init__(self, session: ClinicSession) -> None:
        """Initialise the channel.

        Args:
            session: The call's session. Its identity event is what
                this channel waits for, and its clinic is half of the
                memory actor.
        """
        self._session = session
        self._identified = asyncio.Event()
        self._finished = asyncio.Event()
        self._agent: BidiAgent | None = None

    async def start(self, agent: BidiAgent) -> None:
        """Subscribe to the session's identity event on this loop."""
        self._agent = agent
        loop = asyncio.get_running_loop()
        self._session.on_patient_identified(
            # The tool wrappers run on worker threads; the event they
            # fire must cross onto this loop before anything here
            # reacts to it.
            lambda _patient_id: loop.call_soon_threadsafe(self._identified.set)
        )

    async def stop(self) -> None:
        """Release the pump task waiting on this channel."""
        self._finished.set()

    async def __call__(self) -> NoReturn:
        """Wait for the identity, then say the one thing there is to say.

        Raises:
            asyncio.CancelledError: Always, once the call is over --
                the same contract `Greeting`'s own `__call__` holds.
        """
        await self._identified.wait()
        # Off the loop: this is a network call, and the patient's audio
        # is being pumped on this thread.
        summary = await asyncio.to_thread(
            memory.retrieve_summary,
            memory.actor_id(self._session.clinic_id, self._session.patient_id or ""),
        )
        if summary and self._agent is not None:
            await self._agent.send(
                MEMORY_CONTEXT_TEMPLATE.format(summary=summary)
            )
        await self._finished.wait()
        raise asyncio.CancelledError
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_voice.py -v`
Expected: PASS. If the injection test times out intermittently, check the script has the third scripted turn (the context's send consumes one).

- [ ] **Step 5: Run the whole suite — mic and agentcore will now fail to run**

Run: `python -m pytest -q`
Expected: `tests/test_mic.py` and `tests/test_agentcore_app.py` failures referencing `start_voice_call` returning `VoiceCall` (mic's `main` uses `.system_prompt`-style attributes on the return) — those are the next two tasks' work. Everything else passes.

- [ ] **Step 6: Suggested commit message**

```text
feat: send a returning patient's summary into the voice call, once

MemoryContext is a BidiInput channel beside Greeting: it waits for the
session's patient-identified event, retrieves the summary off the event
loop, and sends it into the running conversation as a stage direction
the model may use but never mention. start_voice_call now returns a
VoiceCall (agent + session) so the interfaces can wire both memory
channels.

Part of progress-tracker.md Next Up #2.
```

---

### Task 6: Wire both memory paths into the microphone interface

**Files:**
- Modify: `backend/agents/mic.py`
- Test: `backend/tests/test_mic.py` (existing; update `drive`, append tests)

**Interfaces:**
- Consumes: `MemoryContext` (Task 5), `TranscriptCollector`, `record_call_end` (Task 4), `VoiceCall` (Task 5).
- Produces: `run_call(agent, *, session, audio, writer, greeting=True, verbose=False)` — new required keyword `session`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_mic.py`:

Update `drive` to create and pass a session (and accept an override):

```python
def drive(
    audio: FakeAudioIO,
    *turns: tuple[str, Any],
    greeting: bool = True,
    verbose: bool = False,
    session: ClinicSession | None = None,
) -> tuple[HangingUpBidiModel, str]:
    """Run one whole call over `run_call` and return the model and output."""
    model = HangingUpBidiModel(*turns)
    session = session or dental_session()
    agent = build_voice_agent(session, voice_model=model)
    writer = io.StringIO()
    asyncio.run(
        asyncio.wait_for(
            run_call(
                agent,
                session=session,
                audio=audio,
                writer=writer,
                greeting=greeting,
                verbose=verbose,
            ),
            CALL_TIMEOUT_SECONDS,
        )
    )
    return model, writer.getvalue()
```

Add `from agents.session import ClinicSession` to the imports if not present.

Append:

```python
# --------------------------------------------------------------------------
# The call is remembered: recorded at hang-up, best-effort
# --------------------------------------------------------------------------


def test_a_call_that_identified_the_patient_is_recorded_at_hang_up(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `run` returns the call is over -- that is the moment the
    collected transcript is handed to memory, under the session that
    knows which clinic and which patient the call was for."""
    tables()
    recorded: list[tuple[ClinicSession, list[tuple[str, str]]]] = []

    def fake_record(
        session: ClinicSession, turns: list[tuple[str, str]]
    ) -> bool:
        recorded.append((session, turns))
        return True

    monkeypatch.setattr(agents.mic, "record_call_end", fake_record)
    session = dental_session()
    session.note_patient("pat_one")

    drive(
        FakeAudioIO("A check-up on Wednesday, please."),
        ("say", "That is booked for nine o'clock."),
        session=session,
    )

    assert recorded == [
        (session, [("That is booked for nine o'clock.", "assistant")])
    ]


def test_a_call_where_nobody_was_identified_records_nothing(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring hands the call-end path a session with no patient;
    `record_call_end` itself is what decides that means no recording
    (pinned in its own suite)."""
    tables()
    recorded: list[tuple[ClinicSession, list[tuple[str, str]]]] = []
    monkeypatch.setattr(
        agents.mic,
        "record_call_end",
        lambda session, turns: recorded.append((session, turns)) or False,
    )
    session = dental_session()

    drive(FakeAudioIO("Hello?"), ("say", "Bright Smile Dental, how can I help?"))

    assert len(recorded) == 1
    assert recorded[0][0].patient_id is None


def test_a_recording_failure_does_not_fail_the_hang_up(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort at the call-end too: memory being unreachable must
    not turn a completed call into an error exit."""
    tables()

    def exploding(session: ClinicSession, turns: list[tuple[str, str]]) -> bool:
        raise AssertionError("record_call_end must swallow its own failures")

    monkeypatch.setattr(agents.mic, "record_call_end", exploding)
    session = dental_session()
    session.note_patient("pat_one")

    model, output = drive(
        FakeAudioIO("Hello?"), ("say", "Bright Smile Dental."), session=session
    )
    assert "Bright Smile Dental" in output
```

Add `import agents.mic` style access — the file already imports names from `agents.mic` directly (`from agents.mic import ...`); add a module import line `from agents import mic as mic_module` if `agents.mic` is not importable as written, or use `monkeypatch.setattr("agents.mic.record_call_end", fake_record)` string form (preferred — matches `test_agentcore_app.py`'s `_patch_voice_model` style).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_mic.py -v`
Expected: FAIL — `run_call() got an unexpected keyword argument 'session'`.

- [ ] **Step 3: Implement**

In `backend/agents/mic.py`:

Extend imports:

```python
from .memory import TranscriptCollector, record_call_end
from .session import ClinicSession
from .voice import (
    DEFAULT_VOICE_REGION,
    VOICE_ID_ENV,
    VOICE_MODEL_ENV,
    VOICE_REGION_ENV,
    Greeting,
    MemoryContext,
    build_nova_sonic_model,
    start_voice_call,
)
```

Change `run_call`:

```python
async def run_call(
    agent: BidiAgent,
    *,
    session: ClinicSession,
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
        session: The call's session -- what the memory channels key on.
            The same session the agent was built from, so the patient
            memory records is the patient the tools resolved.
        audio: Where the patient is heard and the agent is played.
        writer: Where the monitor prints the call.
        greeting: Whether to prompt the agent to speak first. `False`
            waits for the operator instead -- the other arm of the open
            question about who greets the patient.
        verbose: Passed to the monitor.
    """
    silence = Silence()
    collector = TranscriptCollector()
    inputs: list[BidiInput] = [audio.input()]
    if greeting:
        inputs.append(Greeting(on_start=lambda: silence.mark(GREETING_LABEL)))
    # The memory channel says nothing unless the call identifies the
    # patient and a summary exists, so it costs an idle task when
    # memory is off -- not a branch in every interface.
    inputs.append(MemoryContext(session))
    outputs: list[BidiOutput] = [
        audio.output(),
        CallMonitor(silence, writer, verbose=verbose),
        collector,
    ]
    await agent.run(inputs=inputs, outputs=outputs)
    # The call is over: record what was said, best-effort. A failure
    # here is logged inside `record_call_end`, never raised into the
    # operator's exit path.
    record_call_end(session, collector.turns)
```

In `main`, change the call construction and the `run_call` invocation:

```python
        call = start_voice_call(
            options.clinic_id,
            voice_model=voice_model,
            text_model=options.text_model,
        )
```

and the error-print line referring to it stays valid (it prints `options.clinic_id`, not the agent). Then:

```python
        asyncio.run(
            run_call(
                call.agent,
                session=call.session,
                audio=audio,
                writer=sys.stdout,
                greeting=options.greeting,
                verbose=options.verbose,
            )
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_mic.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: only `tests/test_agentcore_app.py` still failing on the `VoiceCall` return (next task). Everything else passes.

- [ ] **Step 6: Suggested commit message**

```text
feat: the microphone interface remembers the call it just took

run_call takes the session, adds the MemoryContext input and a
TranscriptCollector output, and records the collected turns at hang-up
-- best-effort, so a memory outage never turns a completed call into
an error exit.

Part of progress-tracker.md Next Up #2.
```

---

### Task 7: Wire both memory paths into the deployed entrypoint

**Files:**
- Modify: `backend/agents/agentcore_app.py`
- Test: `backend/tests/test_agentcore_app.py` (existing; append)

**Interfaces:**
- Consumes: `MemoryContext` (Task 5), `TranscriptCollector`, `record_call_end` (Task 4), `VoiceCall` (Task 5).
- Produces: nothing new — `/ws` behavior unchanged apart from memory wiring.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_agentcore_app.py` (imports to add: `from agents import memory as agent_memory` or use string-form monkeypatch as below):

```python
def test_the_call_is_recorded_when_the_browser_hangs_up(
    tables,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deployed path gets the same write wiring the microphone has:
    when `run` returns -- here, the browser disconnecting -- the
    collected transcript goes to memory under the call's session."""
    tables()
    model = HangingUpBidiModel(("say", "Bright Smile Dental, how can I help?"))
    _patch_voice_model(monkeypatch, model)
    recorded: list[Any] = []
    monkeypatch.setattr(
        "agents.agentcore_app.record_call_end",
        lambda session, turns: recorded.append((session, turns)) or False,
    )

    def call() -> None:
        with TestClient(app).websocket_connect("/ws") as session:
            session.send_json({"clinic_id": DENTAL})
            _collect_until_disconnect(session)

    _with_timeout(call)

    assert len(recorded) == 1
    ended_session, turns = recorded[0]
    assert ended_session.clinic_id == DENTAL
    assert ended_session.patient_id is None  # nobody booked on this call
    assert ("Bright Smile Dental, how can I help?", "assistant") in turns
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_agentcore_app.py -v -k recorded`
Expected: FAIL — the handler never calls `record_call_end` (and may already fail on `VoiceCall` having no `.run`).

- [ ] **Step 3: Implement**

In `backend/agents/agentcore_app.py`:

Add `import asyncio` to the imports, and extend the voice import:

```python
from .memory import TranscriptCollector, record_call_end
from .voice import Greeting, MemoryContext, start_voice_call
```

In `voice_session`, replace the agent construction and the `run` block:

```python
    try:
        call = start_voice_call(clinic_id, text_model=_from_env(TEXT_MODEL_ENV))
    except ToolError as error:
        ...  # unchanged
    except Exception:
        ...  # unchanged

    logger.info("call for %r connected", clinic_id)
    collector = TranscriptCollector()
    try:
        await call.agent.run(
            inputs=[websocket.receive_json, Greeting(), MemoryContext(call.session)],
            outputs=[websocket.send_json, collector],
        )
    except WebSocketDisconnect as error:
        ...  # unchanged
    except Exception:
        ...  # unchanged
    finally:
        # The call is over: record what was said, off the event loop and
        # best-effort, before the handler gives the thread back. A
        # failure is logged inside `record_call_end`, never raised here
        # -- teardown must not fail a call that already happened.
        await asyncio.to_thread(record_call_end, call.session, collector.turns)
        try:
            await websocket.close()
        except Exception:
            logger.debug("closing the socket for %r failed", clinic_id, exc_info=True)
```

(Keep the existing comment on the `websocket.close()` swallow block.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_agentcore_app.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: all pass — the code half of the unit is complete.

- [ ] **Step 6: Suggested commit message**

```text
feat: the deployed voice entrypoint remembers the call it just took

The /ws handler runs the same MemoryContext input and TranscriptCollector
output the microphone interface does, and records the collected turns
off the event loop when the call ends -- the browser hanging up is the
deployed call-end path.

Part of progress-tracker.md Next Up #2.
```

---

### Task 8: Infra — the memory resource, its id, and its grants

**Files:**
- Modify: `backend/infra/agent_stack.py`
- Test: `backend/tests/test_schema_matches_infra.py` (existing; append)

**Interfaces:**
- Consumes: `aws_cdk.aws_bedrockagentcore` (already imported in this stack as `agentcore`); `agents/memory.py`'s `MEMORY_ID_ENV` and `NAMESPACE_TEMPLATE` (drift-guarded, not imported — see below).
- Produces:
  - `AgentStack.memory` — the `agentcore.Memory` construct
  - `agent_stack.MEMORY_ID_ENV`, `agent_stack.MEMORY_NAMESPACE_TEMPLATE` — constants for the drift guard
  - Runtime env gains `CLINICPILOT_MEMORY_ID`; runtime role gains memory read/write on that one ARN.

- [ ] **Step 1: Write the failing drift-guard tests**

Append to `backend/tests/test_schema_matches_infra.py` (match its existing import style for `agent_stack`; add `from agents import memory` if not already imported):

```python
def test_memory_id_env_var_matches_the_agent_stack() -> None:
    """The env var `agent_stack.py` sets must be the one `agents/memory.py`
    reads -- the same duplicated-constant discipline `KB_ID_ENV_PREFIX`
    already follows."""
    assert agent_stack.MEMORY_ID_ENV == memory.MEMORY_ID_ENV


def test_memory_namespace_template_matches_the_agent_stack() -> None:
    """The namespace the strategy writes to (CDK, `{actorId}` resolved by
    the service) and the namespace the runtime retrieves from
    (`agents/memory.py`, `{actor_id}` filled client-side) must be the
    same path shape, or summaries land where retrieval never looks."""
    assert (
        agent_stack.MEMORY_NAMESPACE_TEMPLATE.replace("{actorId}", "{actor_id}")
        == memory.NAMESPACE_TEMPLATE
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_schema_matches_infra.py -v`
Expected: FAIL — `agent_stack` has no `MEMORY_ID_ENV`.

- [ ] **Step 3: Implement**

In `backend/infra/agent_stack.py`:

Add constants beside `KB_ID_ENV_PREFIX`:

```python
# Duplicated from `agents/memory.py`, not imported: this stack runs in
# a different virtual environment from the agent code
# (`architecture.md` -> System Boundaries), the same tradeoff
# `KB_ID_ENV_PREFIX` documents. `tests/test_schema_matches_infra.py`
# fails if this ever disagrees with `memory.MEMORY_ID_ENV`.
MEMORY_ID_ENV = "CLINICPILOT_MEMORY_ID"

# The namespace the SUMMARIZATION strategy consolidates into. Actor-
# scoped on purpose: the strategy's default namespace is session-
# scoped, which would make every call's summary invisible to the next.
# `{actorId}` is resolved by the AgentCore service; the client-side
# spelling lives in `agents/memory.py` (`NAMESPACE_TEMPLATE`), and the
# same test keeps the two from drifting.
MEMORY_NAMESPACE_TEMPLATE = "/summaries/actors/{actorId}/"


def _memory_name(config: ProjectConfig) -> str:
    """Memory names are letters, digits, and underscores only -- the
    same rule `_runtime_name` already works around."""
    return config.resource_prefix.replace("-", "_") + "_memory"
```

In `AgentStack.__init__`, build the memory before the runtime (it is both an env value and a grant target for the runtime):

```python
        self.memory = self._build_patient_memory()

        self.runtime = self._build_agent_runtime(
            clinics_table=clinics_table,
            patients_table=patients_table,
            appointments_table=appointments_table,
            escalations_table=escalations_table,
        )
```

Add the builder method (beside `_build_clinic_knowledge_base`):

```python
    def _build_patient_memory(self) -> agentcore.Memory:
        """Provision the AgentCore Memory holding each patient's summary.

        One memory resource for the whole project, one SUMMARIZATION
        strategy writing into an actor-scoped namespace: `{clinic_id}#
        {patient_id}` is the actor (`agents/memory.py` -> `actor_id`),
        so a patient's rolling summary accumulates across calls and is
        unreachable from another clinic's session by construction
        (`architecture.md` -> Invariants #1). The runtime's grants and
        env var are the only wiring this stack adds; the read and write
        paths themselves live in the agent code.
        """
        return agentcore.Memory(
            self,
            "PatientMemory",
            memory_name=_memory_name(self.config),
            description=(
                "One rolling summary per patient, across ClinicPilot"
                " voice calls."
            ),
            memory_strategies=[
                agentcore.ManagedMemoryStrategy(
                    agentcore.MemoryStrategyType.SUMMARIZATION,
                    strategy_name="patient_call_summaries",
                    namespaces=[MEMORY_NAMESPACE_TEMPLATE],
                )
            ],
        )
```

In `_build_agent_runtime`, after the SES grant block, add:

```python
        # Read (retrieve a patient's summary mid-call) and write (record
        # the call's turns at hang-up) on the one memory resource -- the
        # L2's own grants, so the action list is the construct's to
        # keep correct. `agents/memory.py` is the only code that makes
        # these calls, and it makes exactly these two.
        self.memory.grant_read(runtime)
        self.memory.grant_write(runtime)
```

In `_runtime_environment`, add to the `env` dict (with a comment in the house style):

```python
            # `agents/memory.py`'s enable: the deployed AgentCore Memory
            # resource id. The read and write paths are no-ops without
            # it, so local development never needs it set.
            MEMORY_ID_ENV: self.memory.memory_id,
```

and extend the method docstring's first line to mention the memory id among the deployment facts.

- [ ] **Step 4: Run the drift-guard tests**

Run: `python -m pytest tests/test_schema_matches_infra.py -v`
Expected: PASS.

- [ ] **Step 5: Synthesize the stack**

Run (from `backend/infra`, with the venv active):
`npx aws-cdk synth ClinicPilot-Dev-Agent`
Expected: synth succeeds; the template contains the memory resource (`AWS::BedrockAgentCore::Memory`), a `CLINICPILOT_MEMORY_ID` entry in the runtime's environment, and the runtime role's policy carries the `bedrock-agentcore:CreateEvent` / `RetrieveMemoryRecords`-family actions scoped to the memory ARN (not `*`).

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest -q` (from `backend/`)
Expected: all pass.

- [ ] **Step 7: Suggested commit message**

```text
feat: provision the AgentCore Memory resource and grant the runtime access

One Memory with a SUMMARIZATION strategy writing to an actor-scoped
namespace, its id handed to the container as CLINICPILOT_MEMORY_ID,
and the L2's read/write grants on the runtime role -- the deployment
half of the memory unit, with the env var and namespace template
drift-guarded against agents/memory.py.

Completes progress-tracker.md Next Up #2.
```

---

## Self-review notes

- **Spec coverage:** summary strategy ✓ (Task 8), patient-keyed actor ✓ (Task 2), identity from the tool layer ✓ (Task 3), best-effort both ends ✓ (Tasks 2/4/6/7), read path via the greet send mechanism ✓ (Task 5), write at call end from both interfaces ✓ (Tasks 6/7), infra scoped grants + CDK-created resource ✓ (Task 8), offline tests with the seam faked ✓ (all), drift guard ✓ (Tasks 2/8). Spec's "two things to verify" — resolved above with the installed SDK/CDK. Deliberate deviation: CLI wiring is out (see Scope note) under the spec's own cut clause.
- **Type consistency:** `turns` are `(text, role)` everywhere (collector, `record_conversation`, `record_call_end`, test assertions); `actor` is always the composite string; `MemoryContext(session)` / `VoiceCall(agent, session)` spellings match across Tasks 5–7.
- **Known flakiness risk:** Task 5's injection test depends on the scripted model consuming the context turn — if it times out, the third scripted `("say", ...)` is missing or the drive's stop condition is wrong; both are local to that one test.
- After Task 8: update `context/progress-tracker.md` (move Next Up #2 to Completed, renumber, note the deploy-time step: `cdk deploy ClinicPilot-Dev-Agent` now creates the memory resource, and the first deploy must succeed before `CLINICPILOT_MEMORY_ID` exists in the container).
