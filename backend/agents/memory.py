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
