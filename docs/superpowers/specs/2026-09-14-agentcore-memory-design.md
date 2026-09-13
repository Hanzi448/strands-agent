# AgentCore Memory for ClinicPilot — Design

Date: 2026-09-14
Status: approved in conversation; pending implementation plan
Item: `progress-tracker.md` -> Next Up #2 ("AgentCore Memory")

## Purpose

`project-overview.md` -> Core User Flow, step 5: "AgentCore Memory
persists enough session state that a returning patient's context
carries across calls." `architecture.md` -> Stack: "Session
Continuity | Bedrock AgentCore Memory | Per-patient conversation
state across calls", and Storage Model: "per-patient conversation
state/history across voice sessions — not duplicated in DynamoDB".

This design is what that means concretely: one AgentCore Memory
resource holding a **rolling summary per patient**, written when a
call ends and read into the conversation once the caller is
identified.

## Decisions (all confirmed)

1. **Summary memory, not semantic or working.** A rolling
   plain-language summary per patient ("calls about cleanings,
   prefers mornings, asked about whitening pricing") is prompt-sized,
   needs no vector store (semantic would add OpenSearch/S3 Vectors
   infra, cost, and per-turn retrieval latency a voice caller hears
   as pauses), and satisfies the spec's "enough session state".
   Working memory is session-scoped and cannot carry anything across
   calls.
2. **Patient-keyed, not browser-keyed.** The actor id is
   `{clinic_id}#{patient_id}` — the same tenant-safe composite the
   `by-patient` index uses (`schema.clinic_patient_key`), so one
   patient's memory is never reachable from another clinic's session
   (Invariant #1 by construction, not by filter — the same reasoning
   as the per-clinic Knowledge Bases).
3. **Identity comes from the tool layer's existing resolution.**
   Phone + name → `find_patient` / `lookup_or_create_patient` is the
   single source of truth for who is calling. Memory keys on its
   result; no new identity mechanism is invented.
4. **Memory is best-effort at both ends.** A call must never fail,
   slow down noticeably, or change its answers because memory is
   unavailable. The escalation email's rule, applied here: retrieve
   fails → the call proceeds as a first-time caller; record fails →
   the call is over anyway and the summary is one call staler.

## What is remembered

- **Recorded**: the call's final transcripts, both sides, user turns
  and assistant turns (Invariant #4 permits transcripts via AgentCore
  Memory; raw audio is never persisted). The summary strategy
  maintains the rolling summary server-side.
- **Retrieved**: the actor's current summary, as plain text.
- **A call where the patient was never identified records nothing** —
  there is no actor to attribute it to, and inventing a
  session-scoped fallback actor is out of scope.

## Components

### `backend/agents/memory.py` — the client seam (new module)

The `dynamo.py` pattern applied to AgentCore Memory:

- `MEMORY_ID_ENV = "CLINICPILOT_MEMORY_ID"` — unset means memory is
  disabled, and both read and write become no-ops (an enable, not a
  dependency — the same choice the escalation email made).
- `actor_id(clinic_id, patient_id) -> str` — the `clinic#patient`
  composite, spelled once.
- `retrieve_summary(actor) -> str | None` — the actor's current
  summary, or None when empty or memory is disabled.
- `record_conversation(actor, messages) -> bool` — record the call's
  turns; bool outcome, exceptions swallowed by the caller.
- The AWS SDK import is lazy (importing the module must not require
  it), and the boto3/agentcore client is built behind the same kind
  of seam the tests fake.

### `session.py` — identity becomes observable

`ClinicSession` gains `note_patient(patient_id)` and a subscriber
list (`on_patient_identified` callbacks). First identification wins;
later calls (a reschedule after a booking) do not re-fire. The agent
layer's scheduling tool wrappers call it when a tool result carries a
`patient_id` — the wrappers already inspect results, and this keeps
`backend/tools/` free of any session or memory knowledge.

### `voice.py` — the read path

At `build_voice_agent`, subscribe to the session's
patient-identified event. When it fires: retrieve the summary, and if
one exists send it into the running `BidiAgent` as a text input — the
same send mechanism `voice.greet` uses, which the greeting-silence
work already proved Nova Sonic treats as context rather than a turn
to answer. Formatted as a stage direction:
`"Context from this patient's previous calls: {summary}. Use it if
relevant; do not mention that you were given it."`

Injection happens at most once per call (the session event fires at
most once). If the patient is identified only at the very end of the
call, the injection may arrive uselessly late — accepted; the write
path still records, so the *next* call is the one that benefits.

### The write path — at call end, from the transcript monitor

The voice interfaces already collect final transcripts both sides
(`mic.py`'s monitor prints them; `agentcore_app.py` relays them).
Recording reuses that collected transcript: when the call ends (the
`BidiAgent.run` completion path in each interface), if the session
has a patient, call `record_conversation(actor, transcript)`. One
implementation shared by both interfaces — `record_call_end(session,
transcript)` in `memory.py`, called from each interface's call-end
path, taking the collected turns.

The CLI (`cli.py`) gets the read path the cheap way (the injected
context is an ordinary orchestrator-layer message) and the write path
the same shared function. If the CLI write proves awkward, it is
cuttable — the deployed voice path is the one the spec cares about.

### Infra (`agent_stack.py`)

- The AgentCore Memory data-plane actions on the one memory
  resource, granted to the runtime role, scoped to that resource ARN
  only (the KB-grant style).
- The memory resource itself: **created in CDK if a construct
  exists, else a documented one-time CLI/console step** with the id
  in `MEMORY_ID_ENV` — the same pattern the KB ids could not avoid
  and the runtime env already carries.

### Two things to verify before writing any integration code

Recorded here so the plan makes them explicit first steps, not
surprises:

1. **The exact SDK surface.** Research in this environment could not
   verify the `bedrock-agentcore` memory client's method names
   (create/record/retrieve shapes) against live docs. First
   implementation step: install and pin the SDK, read its actual
   client, and adjust `memory.py`'s internals to it. The seam keeps
   this a one-file change.
2. **CDK construct availability** for the memory resource in
   `aws-cdk-lib` 2.269.0 — decides infra's create-in-CDK vs
   CLI-plus-env-var branch.

## Error handling

- `retrieve_summary` unavailable → None → no injection, call proceeds
  as first-time. Never raises into the call.
- `record_conversation` unavailable → False, logged nowhere the
  patient hears. Never raises into the call-end path.
- Memory disabled (`MEMORY_ID_ENV` unset) → both are no-ops; the
  776+ existing tests that drive whole calls must keep passing
  unchanged with memory off, which is also the default for every
  offline test.

## Testing

Offline throughout, per the repo's standing rule:

- `memory.py`: actor composite; disabled-env no-ops; the client seam
  faked at the same boundary `dynamo` fakes tables.
- `session.py`: `note_patient` fires subscribers exactly once, first
  identity wins, no patient → no event.
- Agent level: a scripted voice call where a booking identifies the
  patient mid-call injects the faked summary into the model's input
  exactly once and the orchestrator's prompt is untouched; a call
  with no identification records nothing; call-end recording receives
  both sides' turns in order with the clinic-prefixed actor.
- Drift guard: `backend/tools/` still imports no agentcore/strands
  module (existing scanner extended to the new package name).

## Out of scope

Semantic memory; any dashboard view of memory; frontend changes;
deleting or expiring memories (the demo has two clinics and a
handful of callers); the background job reading memory; memory for
unidentified callers.

## Tenant and privacy invariants held

- Actor ids embed `clinic_id`; no API call can be given another
  clinic's actor without already holding that clinic's session
  (Invariant #1).
- Transcripts only, never audio (Invariant #4).
- Memory is not a second patient record — appointments and patient
  facts stay in DynamoDB via `backend/tools/` (Invariant #3);
  memory holds conversation context only.
