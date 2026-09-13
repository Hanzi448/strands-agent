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

import asyncio
from typing import Any

import pytest
from strands.experimental.bidi import BidiTranscriptStreamEvent

from agents import memory
from agents.session import ClinicSession
from tests.test_scheduling import DENTAL_ID, dental_clinic


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
        return {"memoryId": kwargs["memory_id"]}


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
    assert event["memory_id"] == "mem_one"
    assert event["actor_id"] == "clinic-dental#pat_one"
    assert event["messages"] == turns
    assert event["session_id"]  # a fresh id per call, never reused


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


# --------------------------------------------------------------------------
# The transcript collector: finals only, both sides, in order
# --------------------------------------------------------------------------


def _session_with_patient(patient_id: str | None = None) -> ClinicSession:
    """A dental-clinic session, optionally already identified.

    Constructed directly, the way every agent-layer suite builds one:
    `ClinicSession.start` is for the entry points, and would need the
    clinics table faked to no benefit here.
    """
    session = ClinicSession(clinic_id=DENTAL_ID, clinic=dental_clinic())
    if patient_id is not None:
        session.note_patient(patient_id)
    return session


def _transcript(text: str, role: str, *, final: bool = True) -> Any:
    return BidiTranscriptStreamEvent(
        delta={"text": text}, text=text, role=role, is_final=final
    )


def _collected(*events: Any) -> list[tuple[str, str]]:
    collector = memory.TranscriptCollector()

    async def run() -> None:
        for event in events:
            await collector(event)

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
    session = _session_with_patient("pat_one")

    turns = [("Nine on Wednesday, please.", "user"), ("Booked.", "assistant")]
    assert memory.record_call_end(session, turns) is True

    assert len(client.events) == 1
    assert client.events[0]["actor_id"] == f"{DENTAL_ID}#pat_one"
    assert client.events[0]["messages"] == turns


def test_an_unidentified_call_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spec's rule: a call where the patient was never identified
    records nothing -- there is no actor to attribute it to."""
    client = FakeMemoryClient()
    monkeypatch.setenv(memory.MEMORY_ID_ENV, "mem_one")
    monkeypatch.setattr(memory, "_client", lambda: client)

    assert memory.record_call_end(_session_with_patient(), [("hello", "user")]) is False
    assert client.events == []


def test_a_disabled_memory_records_nothing_at_call_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory, "_client", _bomb)
    session = _session_with_patient("pat_one")
    assert memory.record_call_end(session, [("hello", "user")]) is False
