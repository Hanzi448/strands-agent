# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- Phase 2 is **complete on the tool layer**. The AWS sample is vendored
  as reference code, `backend/infra/` synthesises with the four DynamoDB
  tables defined (the other four stacks are still empty), and
  `backend/tools/` now has its foundation, the **complete availability
  read surface** (`check_availability`, one day or a bounded window of
  up to 14), the **complete scheduling write surface**
  (`book_appointment`, `reschedule_appointment`, `cancel_appointment`),
  and the **complete escalation surface** (`create_escalation`,
  `list_open_escalations`, `get_escalation`, `resolve_escalation`).
  All four tables are now written by this layer. The one tool still
  missing is the FAQ query, which has nothing to query until the
  Knowledge Base exists and therefore lands with it (Next Up #4).
  `frontend/`, `backend/agents/`, `backend/lambda/`, and `seed/` do not
  exist yet.

## Current Goal

- **Phase 3: the agents.** `backend/tools/` is done, so the next unit
  is the first one that is not a pure function over DynamoDB. Build the
  Orchestrator plus the Scheduling and Escalation sub-agents
  (Agent-as-Tool), wrapping the existing tool functions with `@tool`
  and testing against a text interface before any voice is wired — the
  FAQ sub-agent waits for the Knowledge Base. Nothing in
  `backend/tools/` may move into an agent definition
  (`architecture.md` -> Invariants #3): the agents are a thin
  model-facing surface over functions the background Lambda will call
  directly. After the agents: Nova Sonic voice, AgentCore deploy, the
  KB bucket plus the FAQ tool, the background Lambda, the dashboard,
  and the seed scripts.

## Completed

- **Vendored `aws-samples/sample-nova-sonic-websocket-agentcore`**
  (Next Up #1) at pinned commit
  `ef6e81b7965fc7922b0999f7c63685f72f92a44c` (2026-02-24), into
  `vendor/sample-nova-sonic-websocket-agentcore/`. Nested `.git`
  stripped so it vendors as plain files rather than an embedded repo;
  provenance, license (MIT-0), contents, and a per-file reusability
  assessment recorded in that directory's `VENDOR.md`. Treated as
  read-only reference code per `ai-workflow-rules.md` → Protected
  Files. Also fixed two `.gitignore` faults this surfaced — see
  Session Notes.

- **`backend/infra/` CDK app with five stack skeletons**
  (Next Up #1, superseding the numbering below).
  `app.py` instantiates `DataStack`, `AgentStack`, `ApiStack`,
  `AutomationStack`, `FrontendStack` (`ClinicPilot-Dev-*`), each an
  empty `Stack` subclass carrying a docstring of its planned contents
  and the `architecture.md` section that defines them. No resources
  yet, by design. `config.py` holds the single `ProjectConfig` every
  stack receives, so no name or ARN is hardcoded or duplicated across
  stacks (`code-standards.md` → AWS CDK). Deployment order declared
  now (`data` → `agent`/`api`/`automation`, `api` → `frontend`) so
  `cdk deploy --all` is correct from the first stack that gains a
  resource. Verified: `cdk synth` exits 0 and writes all five
  templates, `cdk list` shows all five, and the synthesised manifest
  carries the intended dependency edges.

- **DynamoDB table schemas in the data stack** (Next Up #1).
  `data_stack.py` defines `Clinics` (PK `clinic_id`), `Patients`
  (PK `clinic_id`, SK `patient_id`), `Appointments` (PK `clinic_id`,
  SK `appointment_id`), and `Escalations` (PK `clinic_id`, SK
  `escalation_id`) as `TableV2` constructs, on-demand billing, physical
  names from `ProjectConfig`. Four GSIs, each carrying `clinic_id`
  inside its own partition key so no index is a cross-clinic query path
  (`architecture.md` -> Invariants #1): appointments `by-start-time`
  and `by-patient`, patients `by-phone`, escalations `by-created-at`.
  Key attribute names and index names are module constants, since the
  tool layer and the seed scripts must spell them identically. Table
  names are exported via `CfnOutput` for the out-of-CDK consumers (seed
  scripts, CLI); in-app stacks will take the table objects directly.
  The schema and the reasoning behind each index are recorded in
  `architecture.md` -> Storage Model. Verified: `cdk synth` exits 0 and
  the Data template carries the four tables with the intended keys,
  indexes, and ALL projections; a `CLINICPILOT_ENV=prod` synth
  confirmed the environment branch (RETAIN + PITR + deletion protection
  in `prod`, DESTROY in `dev`) and its artifacts were removed.

- **`backend/tools/` foundation: item schema, validation, table
  handles** (first unit split out of the old Next Up #1). Four modules
  plus a 66-test suite, all passing.
  `schema.py` fixes what `architecture.md` -> Storage Model explicitly
  deferred to this layer: non-key attribute names for all four tables
  (`ClinicAttrs`, `PatientAttrs`, `AppointmentAttrs`,
  `EscalationAttrs`), the status vocabularies (`AppointmentStatus`,
  `EscalationStatus`, `EscalationSource`, `ClinicType`), and the key
  and timestamp *encodings* — `clinic_patient_key` for the `by-patient`
  composite and one ISO-8601 UTC format for every timestamp.
  `validation.py` holds the boundary checks, `require_clinic_id` first
  among them (`code-standards.md` -> Python). `dynamo.py` resolves
  table names from environment variables the CDK will set, falling back
  to the same naming scheme `backend/infra/config.py` uses.
  `errors.py` is the exception vocabulary. Deliberately *not* fixed
  here: the nested shapes of the clinic's `hours`/`services` and the
  entry shape of the appointment history lists — those are tool-level
  decisions, now Next Up #1 and an open question.
  Verified: `pytest` from `backend/` — 66 passed. The suite covers
  lexicographic sort-key ordering across mixed offsets, composite-key
  ambiguity, phone-format convergence, table-name resolution, and the
  tools/infra drift guard (see Session Notes). `get_table` itself is
  not covered: it needs credentials and a live boto3 resource, so it
  is exercised by the first tool that queries.

- **Clinic availability config shape fixed in `architecture.md`**
  (Next Up #1 — a spec unit, no tool code). `architecture.md` ->
  Storage Model now specifies the five `Clinics` attributes that
  together decide whether a time is bookable, and states that nothing
  outside a clinic's own item may be consulted to decide it:
  `timezone` (IANA, the frame `hours`/`closures` are read in, while
  every stored timestamp stays UTC); `hours` as a weekday -> **list of
  `{open, close}` intervals** so a lunch break or split shift is
  expressible; `closures` as whole-day `{date, label}` entries;
  `services` as `{id, name, duration_minutes}` so a 60-minute consult
  blocks a different span than a 15-minute check-up; and per-clinic
  `slot_minutes`. The composition rule is written down too — candidate
  starts on the `slot_minutes` grid from each interval's `open`, offered
  only if the whole duration fits inside that same interval and overlaps
  nothing in `ACTIVE_APPOINTMENT_STATUSES` — so `check_availability` has
  no decision left to make. Concrete configs for the two demo clinics
  are recorded there as the target for the seed scripts. Four decisions,
  all confirmed with the user rather than defaulted
  (`ai-workflow-rules.md` -> Handling Missing Requirements).
  `schema.py` synced: `ClinicAttrs` gained `CLOSURES` and
  `SLOT_MINUTES` (attribute *names* are this module's job), and the two
  docstrings that called the shape an open question now point at the
  spec. Nested key names (`open`, `close`, `date`, `id`,
  `duration_minutes`) land as constants with the first tool that reads
  them. Verified: `pytest` from `backend/` — 66 passed.

- **`check_availability` in `backend/tools/scheduling.py`**
  (Next Up #1). The first tool function, and the first code that reads
  DynamoDB. Given a `clinic_id`, a local `date`, and a `service`, it
  returns the start times that clinic can offer: the clinic's `hours`
  for that weekday, minus whole-day `closures`, gridded by
  `slot_minutes`, filtered to candidates whose whole
  `duration_minutes` fits inside one opening interval, minus anything
  overlapping an appointment in `ACTIVE_APPOINTMENT_STATUSES`. Read
  only — nothing is written, and `book_appointment` will re-check the
  slot it is finally given rather than trusting a list returned here.
  Landed with it: the nested config key names `schema.py` had deferred
  (`HoursInterval`, `ClosureAttrs`, `ServiceAttrs`, `WEEKDAY_KEYS`,
  `weekday_key`), the `DATE_FORMAT`/`LOCAL_TIME_FORMAT` encodings,
  `from_iso8601` (the counterpart to `to_iso8601`, for the arithmetic
  this tool has to do on stored times), and `validation.require_date`.
  The response carries both `starts_at`/`ends_at` in stored UTC and
  `local_start`/`local_end` as `HH:MM`, because the model must *say*
  "nine o'clock" and must not do timezone arithmetic itself; it also
  distinguishes closed-for-a-holiday (`closure_label`) from
  closed-that-weekday from open-but-fully-booked, which are three
  different things to tell a patient.
  Verified: `pytest` from `backend/` — **125 passed** (66 before, 59
  new). The suite drives the real code path with fake table objects
  (no credentials): the two demo clinics from `architecture.md` answer
  the same question differently, a 30-minute service is refused at
  12:45 against a 13:00 lunch break, overlap is half-open at both
  ends, cancelled/completed/no-show free their slot while an
  *unrecognised* status does not, DST is checked by running the same
  clinic in July and January (09:00 local = 08:00Z then 09:00Z), the
  query window is asserted to be the clinic's local midnight-to-
  midnight expressed in UTC, and every malformed-config case fails as
  `ConfigurationError` rather than as wrong slots. Also eyeballed
  end to end against the seeded demo configs.

- **`days` look-ahead on `check_availability`** (Next Up #1). The last
  change to the availability *read* surface. `check_availability` now
  takes an optional `days` (default 1, max 14, spec in
  `architecture.md` -> Storage Model, "Multi-day look-ahead") and walks
  that many consecutive clinic-local dates, so "when are you next
  free?" is one tool call rather than up to seven — a voice-latency
  decision, since every extra round trip is a pause the patient hears.
  Shape: `slots` stays one flat list, earliest first across the whole
  window, with each slot now carrying its own local `date`; a new
  `days_checked` list carries one `{date, is_open, closure_label,
  slot_count}` entry per day, which is what keeps *closed for a
  holiday* / *never opens that weekday* / *open but fully booked*
  three distinguishable answers per day rather than one summary for
  the window. Top-level `is_open`/`closure_label` remain, mirroring the
  first day, so the ordinary one-day call reads exactly as before.
  Two things landed with it, both load-bearing rather than tidying:
  `validation.require_bounded_int` (a count a *model* chooses, so
  `None`/`"7"`/`Decimal("7")` are all accepted and out-of-range is a
  `ValidationError` rather than a silent clamp — quietly answering for
  14 when it asked for 365 would hide the misunderstanding from it);
  and `_local_midnight`, which rebuilds each day boundary by combining
  a *date* with midnight instead of adding 24 hours to the previous
  one. The old single-day code took the latter shortcut for its window
  end: across the autumn DST transition that lands an hour short and
  would hide the last hour of the window's final day from the query.
  The whole window costs **one** `by-start-time` query, trimmed to the
  first and last day that could offer anything (a window with no open
  day queries nothing at all) — which is the reason `days` exists.
  Verified: `pytest` from `backend/` — **165 passed** (125 before, 40
  new), including the DST-spanning window, the one-query assertion,
  per-day closure reasons, cross-day slot ordering, and the bounds.
  Also eyeballed end to end: a five-day dental window returns Sunday
  closed with no label, the staff-training Wednesday with its label,
  and a Monday whose 09:30 start is missing because an appointment
  holds it.

- **`book_appointment` in `backend/tools/booking.py`, plus patient
  lookup-or-create in `backend/tools/patients.py`** (Next Up #1). The
  first code in this layer that writes. `book_appointment` re-checks the
  requested time, resolves the caller from their phone number and name,
  and writes one `Appointments` item; a refused booking writes nothing
  at all, patient row included, because a voice caller retries and a
  half-written first attempt is what turns one retry into two records.
  **The availability rule is not restated.** `scheduling.py` gained one
  public function, `offerable_slots_for_date`, which runs the same
  `_day_plan`/`_compute_slots` pair `check_availability` runs, for a
  single date; booking asks *that* whether a time is bookable and takes
  the stored `ends_at` from the matched slot rather than recomputing
  one. So a slot is bookable if and only if the read surface would have
  offered it, and `architecture.md` -> Invariants #3 holds by
  construction rather than by discipline. `scheduling.py` stays
  read-only.
  Patient identity is **phone and name together**, confirmed with the
  user rather than defaulted (`ai-workflow-rules.md` -> Handling Missing
  Requirements) and written into `architecture.md` -> Storage Model: a
  household shares a number, so phone alone would put a spouse's booking
  under the first-registered patient's name, silently. An existing
  patient's details are never rewritten by a booking — the one exception
  is a missing `email`, which is filled in, since that adds a fact
  rather than overwriting one and the reminder job has no address
  without it.
  Also landed: `validation.normalise_email` (a deliberately shallow
  check — it stops "dave at gmail dot com" being stored, and does not
  pretend to know whether mail would arrive), and `patient_summary`,
  which fixes what a tool result tells the model about a patient.
  Verified: `pytest` from `backend/` — **254 passed** (165 before, 89
  net new). The booking suite imports its clinic fixtures from
  `test_scheduling.py` rather than restating them, so a rule that
  drifted between the read and the write shows up as a disagreement
  between the two files; it covers the slot taken between quote and
  write, a start off the clinic's grid, a 30-minute cleaning refused at
  12:45 against the 13:00 lunch break (the same case the read suite
  asserts), a closed weekday, the seeded closure day, both clinics'
  differing rules, an instant whose *clinic-local* day is the next one,
  and that nothing is written on any refusal.
  Eyeballed end to end against the seeded dental config: 28 free
  cleaning slots, book 09:00, 26 remain with 09:00 *and* 09:15 gone (a
  30-minute service on a 15-minute grid), the same time refused on retry
  with alternatives named, and the same caller recognised on a second
  call.

- **Fixed: `normalise_phone` gave one number two index keys**
  (surfaced by the end-to-end eyeball above, not by a test). It kept a
  leading `+` when the input had one and dropped it otherwise, so
  `"+1 555 123 4567"` and `"1-555-123-4567"` stored as different
  strings — and the `by-phone` index is an equality match, so a caller
  who said "plus one" on their second call got a *second patient
  record* instead of their own. The function's own docstring claimed the
  opposite, and the existing test asserted the divergence while being
  named `..._converges_on_one_stored_form`, which is why 165 passing
  tests never caught it. Now digits only, with the docstring corrected
  to state exactly what converges and what does not. What it still
  cannot do is reconcile a national number with its international form
  (`555 123 4567` vs `+1 555 123 4567`) — that needs a country
  assumption no context file makes, so it is an open question below and
  a test asserts the limit rather than leaving it implied.

- **`reschedule_appointment` and `cancel_appointment` in
  `backend/tools/appointments.py`** (Next Up #1). The appointment
  lifecycle after booking, and the last of the scheduling tools. One
  module for both, because they are the same operation with a different
  destination: each has to work out *which* of a caller's appointments
  is meant, and each writes one entry to the same `reschedule_history`
  list.
  **Neither restates the availability rule.** A reschedule re-checks the
  new time through `scheduling.offerable_slots_for_date`, exactly as
  `book_appointment` does, and takes its stored `ends_at` from the
  matched slot. That seam gained one argument to make it work:
  `exclude_appointment_id`, threaded down to `_booked_spans`. Without
  it an appointment blocks its own move — any new time within one
  service length of the old one overlaps the row about to be vacated,
  so moving a 30-minute cleaning by 15 minutes would refuse itself.
  **Ownership is the delicate part**, and it is checked once, in
  `_resolve_appointment`. A caller reaches an appointment only through
  the `by-patient` partition their own `patients.find_patient` match
  produces — never by fetching an `appointment_id` by key — so a
  guessed or carried-over id cannot touch another patient's row, and
  past or already-cancelled appointments are unreachable by
  construction rather than by a status check. `patients.py` gained the
  read-only `find_patient`, extracted from `lookup_or_create_patient`,
  so the phone-*and*-name identity rule has exactly one
  implementation; the read half must not register a caller who turns
  out to be unknown.
  **A caller with several upcoming appointments is refused, not
  guessed at.** The `ConflictError` names each one's service, local
  time, and `appointment_id`, so the agent can ask in a single turn.
  Taking the soonest would be a silent wrong cancellation — the kind a
  patient discovers by arriving at a closed clinic.
  **Both writes are one conditional `update_item`**: the field(s), the
  `updated_at` stamp, and the history append land together or not at
  all (an appointment moved without its history entry is a move missing
  from the staff action log), conditioned on the row still being
  `scheduled` and still at the time it was read at. Unlike the slot
  contention documented in `booking.py`, this race is between rows that
  already exist, so DynamoDB settles it; a lost race is a
  `ConflictError`, and any other `ClientError` propagates.
  Landed with them: `schema.RescheduleEntry`, `schema.ReminderEntry`
  and `schema.RescheduleActor` (the nested history key names
  `architecture.md` said would arrive with this tool), and
  `scheduling.unavailable_message` — `booking.py`'s private refusal
  message, promoted rather than copied, since both writes refuse a time
  against the same freshly computed slot list.
  Two spec decisions, both written into `architecture.md` -> Storage
  Model rather than left in code: a **cancellation writes a
  `reschedule_history` entry with `to: null`** (a move to nowhere —
  `status` records that it happened but not who did it or why, which is
  what the action log is for), and the `by-patient` index is documented
  as the ownership check, not just a query path. See Open Questions for
  the one assumption in the first of those.
  Verified: `pytest` from `backend/` — **315 passed** (254 before, 61
  new), and the pre-existing 254 still pass unchanged through the
  `find_patient` and `unavailable_message` refactors. The new suite's
  fake `Appointments` table evaluates both key conditions and actually
  *applies* the `UpdateExpression` it is given, so a malformed
  expression or a missing `if_not_exists` fails here rather than in a
  deployed Lambda; "now" is monkeypatched, since "upcoming" is relative
  to it and fixtures that silently fell into the past would stop
  testing anything. Covered: the household cases (right number wrong
  name, a housemate's appointment, another patient's id), the
  self-overlap move, same-time/closed-day/closure/off-grid refusals,
  duration preserved across a move, the winter/summer offset, the
  cosmetic clinic answering the same call differently, cancelling
  freeing the slot for `check_availability`, and the conditional write
  including a lost race. Each of six guards was mutation-checked —
  removing it fails at least one test.

- **Escalation tools in `backend/tools/escalations.py`** (Next Up #1).
  The last of `backend/tools/`, and the only module here whose items
  exist to be **read by a person** rather than acted on by the agent:
  `create_escalation`, `list_open_escalations`, `resolve_escalation`,
  plus `get_escalation` (see below). `Escalations` was the one table
  nothing had written; `EscalationStatus`/`EscalationSource` and
  `EscalationAttrs` were already fixed in `schema.py`, so **no schema
  change was needed** — this unit is one new module and its tests.
  **Creating one must not acquire a way to fail.** An escalation is
  written when everything else has already gone wrong, so
  `create_escalation` reads nothing: `patient_id` and `appointment_id`
  are validated for *shape* and stored unverified. Checking that they
  resolve would let a stale reference stop the escalation being
  recorded at all, and a mis-referenced escalation a human can still
  read beats a correct one that was never written. `source` is
  keyword-only and defaults to `voice`, exactly as
  `reschedule_appointment`'s `actor` defaults to `agent`: it records
  which agent path raised the item, the live agent and the background
  job each know their own, and it is never a value a model chooses.
  **The queue is capped after the status filter, not by DynamoDB.**
  `list_open_escalations` walks `by-created-at` backwards
  (`ScanIndexForward=False`) and filters to `open` in Python — the
  choice `architecture.md` -> Storage Model already records for this
  index. The `limit` is applied *after* that filter and is deliberately
  not passed as DynamoDB's `Limit`, which counts items **scanned**: a
  clinic whose newest 50 escalations are all resolved would otherwise
  show an empty queue while its real one was full. Ties on
  `created_at` (second precision) are broken by `escalation_id`, so
  "which is at the top?" does not vary between two identical calls —
  the same determinism `find_patients_by_phone` needs.
  **Resolving twice is refused, not absorbed.** Both the read-time
  check and the conditional write raise `ConflictError`, for the reason
  `reschedule_appointment` refuses a move to the time an appointment
  already has: two staff working one queue need to hear that the other
  got there first, and a silent success tells them the opposite. See
  Open Questions — this is the one place the unit went past the letter
  of the spec.
  **`get_escalation` is a fourth function on a three-function item**,
  flagged rather than buried. `resolve_escalation` needs the read
  anyway (read, then conditional write, as `appointments` does), and
  two readers hold an id without the item: the dashboard's escalation
  detail modal (`ui-context.md` -> Layout Patterns) and a staff member
  arriving from the SES escalation email. Making it public rather than
  private is what stops the dashboard adding a second `get_item`.
  The tenant boundary needs nothing beyond `require_clinic_id` here:
  the table is keyed on `(clinic_id, escalation_id)` and the index is
  partitioned on `clinic_id`, so another clinic's escalation is a
  `NotFoundError` indistinguishable from one that never existed — and
  a test asserts the two messages are identical. Nothing belongs to a
  *patient*, so there is no ownership resolution of the kind
  `appointments._resolve_appointment` carries.
  Verified: `pytest` from `backend/` — **380 passed** (315 before, 65
  new), the pre-existing 315 unchanged (nothing outside this module was
  touched except the `tools/__init__.py` module list). The fake
  `Escalations` table honours the index partition key and
  `ScanIndexForward`, serves fixed-size pages so pagination is
  exercised rather than assumed, and *applies* the `UpdateExpression`
  it is given, so the `#status` aliasing that DynamoDB's reserved word
  forces fails here rather than in a deployed Lambda. Ten guards were
  mutation-checked; the first pass caught nine and found a real gap —
  nothing pinned that `clinic_id` is validated **before** the other
  arguments, since the tenant test passed a blank clinic id with an
  otherwise valid call. A test with *every* argument bad now asserts
  the failure names `clinic_id` and not the second argument, and the
  swap is caught for all four functions.

## In Progress

- None.

## Next Up

The old item 1 ("implement `backend/tools/`") bundled five unrelated
tool families, which `ai-workflow-rules.md` -> When to Split Work
forbids in one step. It is now **fully discharged**: the foundation,
the spec decision that blocked the first tool, the availability read
surface, the scheduling write surface, and the escalation tools are all
in Completed. The only tool still unwritten is the FAQ query, which
belongs to the Knowledge Base unit below rather than to that item.

1. Build the Orchestrator agent + Scheduling/Escalation sub-agents
   (Agent-as-Tool pattern), test locally with a text interface before
   wiring voice. The FAQ sub-agent is **not** part of this unit — it
   has nothing to query until item 4 exists, and adding an empty one
   now would mean writing its prompt twice. Split further if it does
   not stay verifiable end to end in one step (the Orchestrator and
   its routing first, sub-agents after, is the natural seam).
2. Wire Nova Sonic + BidiAgent voice on top of the working
   text-agent logic.
3. Deploy to AgentCore Runtime, verify voice session end-to-end.
4. Add the Knowledge Base source S3 bucket to the data stack
   (`kb/{clinic_id}/` prefixes) and the Bedrock Knowledge Base over it
   in the agent stack — these deploy together, so they are one unit.
   The FAQ query tool and the FAQ sub-agent land with them, since they
   have nothing to query until the KB exists.
5. Build the background Lambda + EventBridge schedule, reusing
   `backend/tools/` functions. Its no-show/reschedule heuristic is not
   specified anywhere yet — per `ai-workflow-rules.md` -> When to Split
   Work that is a spec-then-implement step, not something to invent
   inline. Note the tool it needs already exists:
   `create_escalation(..., source="background")`.
6. Build the staff dashboard (Cognito auth, appointment list,
   escalation queue). Its escalation reads are already written —
   `list_open_escalations`, `get_escalation`, `resolve_escalation`.
7. Seed the two demo clinics (dental, cosmetic) with config,
   sample appointments, and FAQ documents for the Knowledge Base.
   Settle the phone-number country-code question below first: this is
   the step that fixes a number format.
8. Architecture diagram, README, demo video, submission assets.

## Open Questions

- ~~**What is the shape of a clinic's `hours` and `services`
  config?**~~ **Resolved** — specified in `architecture.md` ->
  Storage Model, "Clinic availability config". All four sub-questions
  answered by the user: (a) per-weekday **list** of `{open, close}`
  intervals, so a lunch break or split shift is expressible;
  (b) whole-day `closures` entries `{date, label}`, no partial-day
  case; (c) per-service `duration_minutes`; (d) per-clinic
  `slot_minutes`. See Completed.

- ~~**Does the patient flow need a "next available appointment"
  search?**~~ **Resolved** — yes, as a bounded `days` look-ahead on
  `check_availability` itself (default `1`, max `14`), specified in
  `architecture.md` -> Storage Model. Rejected: a separate
  `find_next_available`, which would re-walk the same hours/closures/
  overlap rule and put the booking system's core logic in two places.
  The reason is voice latency — each extra tool round trip is a pause
  the patient hears, and a clinic open `tue`–`sat` would otherwise
  need up to seven to answer "when are you next free?". Additive:
  `days=1` is the behaviour already built and tested. Now Next Up #1.

- ~~**What does one entry in an appointment's `reminders` /
  `reschedule_history` list contain?**~~ **Resolved** — specified in
  `architecture.md` -> Storage Model ("Appointment history entry
  shapes"): `{at, from, to, actor, reason}` and
  `{at, channel, outcome}`. `actor` is `agent`/`staff` because the
  dashboard's whole point is showing which moves the agent made
  unprompted, and that cannot be inferred after the fact; `outcome`
  is `sent`/`failed` because "we reminded them" and "SES rejected it"
  are different facts for staff deciding whether to phone. SES message
  ids, templates, recipients and retry counts were deliberately
  excluded — no screen in `ui-context.md` reads them, and they would
  copy the patient's contact details onto every appointment item.
  `schema.py` synced; the nested key names land there with
  `reschedule_appointment`.

- ~~**AWS region**~~ **Resolved** — `us-east-1`, confirmed in
  `architecture.md` -> Stack. Chosen over the three other Nova Sonic
  regions for Bedrock/AgentCore feature parity: the riskiest
  dependency here is an experimental voice stack, and a capability
  found missing late costs more than the extra round-trip latency of
  a browser demo.
- **Should a cancellation appear in the staff action log?** Assumed
  **yes**, and implemented: `cancel_appointment` appends a
  `reschedule_history` entry with `to: null`, so who cancelled an
  appointment and why is visible beside the moves. `architecture.md`
  specified the entry shape for *moves* and said nothing about
  cancellations, so this is the one place this unit went past the
  letter of the spec — flagged rather than buried. The alternative
  readings were a separate `cancellation_reason` attribute (splits the
  log into two lists to read) or dropping the reason entirely (`status`
  then records that it happened but not who did it, which is what the
  log exists to show). Reversible: the encoding has one writer and, so
  far, no reader. If it is wrong, say so before the dashboard is built.

- **Should marking an already-resolved escalation resolved be an
  error?** Assumed **yes**, and implemented: `resolve_escalation`
  raises `ConflictError` rather than succeeding quietly, both when the
  read sees it already resolved and when the conditional write loses
  the race. `project-overview.md` says only "staff can view an emailed
  escalation and mark it resolved" and says nothing about the second
  attempt, so this is where this unit went past the letter of the spec
  — flagged rather than buried, exactly as the cancellation-history
  decision above was. The reasoning: two staff working one queue, or
  one staff member arriving from an email after a colleague has dealt
  with it, need to *hear* that it is already handled; a silent success
  tells them they resolved something they did not. The message names
  the `resolved_at` stamp so the dashboard can say when. The cost is
  that a double-click on "Mark Resolved" surfaces an error rather than
  a no-op, which the dashboard can absorb by treating `conflict` on
  this call as success. Reversible: one branch, one message, and the
  tests that pin it are named for the behaviour. If the dashboard would
  rather have it idempotent, say so before Next Up #6 is built.

- **What bounds the escalation queue read?** `list_open_escalations`
  takes an optional `limit`, defaulting to 50 and capped at 100
  (`DEFAULT_ESCALATION_LIMIT`/`MAX_ESCALATION_LIMIT`). Not a product
  rule and not asked about — a boundary decision of the same kind as
  `appointments._APPOINTMENTS_IN_ERROR`, so that nothing can walk a
  whole partition into a tool result. There is deliberately **no page
  cursor**: no screen in `ui-context.md` reads one, and a result
  exactly `limit` long is the only signal that more exist. If the
  dashboard ever needs real pagination, the sort key is `created_at`
  and the cursor is the last item's — an additive change.

- **Can a returning caller who is heard differently reach their own
  appointment?** No, and this is the phone-number question below in a
  sharper form. `reschedule_appointment` and `cancel_appointment`
  require phone *and* name, the same identity rule `book_appointment`
  uses, because a household shares a number and cancelling a spouse's
  appointment silently is the failure that rule exists to prevent. The
  cost is that "Dave" cannot cancel what "David" booked — for a
  booking that meant a duplicate patient record, but here it means the
  agent has to escalate. Options if it bites in the demo: (a) match on
  name *or* an appointment id the patient can read back; (b) accept a
  fuzzier name match for reads while keeping the strict one for
  registration. Not blocking, and deliberately not softened on a guess.

- **Does a spoken phone number need a default country code?**
  `normalise_phone` now stores digits only, so every *format* of one
  number converges. What does not converge is a national number against
  its international form: a patient who says "555 123 4567" on their
  first call and "plus one, 555 123 4567" on their second gets two
  patient records. Fixing it means assuming a country code (the demo
  clinics are `Europe/London`, which argues `+44`, but the seeded
  numbers are not written yet), and that is product behaviour no context
  file states. Options: (a) assume one country code per clinic, stored
  on the clinic item alongside `timezone`; (b) leave it, and have the
  seed scripts and the agent prompt use one consistent form; (c) match
  on a digit *suffix*, which risks collisions. Not blocking —
  `book_appointment` works either way — but it should be settled before
  the seed scripts fix a number format.

- **Slot contention between the re-check and the write.**
  `book_appointment` re-checks availability immediately before writing,
  which closes the conversation-length gap (tens of seconds) between a
  slot being quoted and being taken. It does not close the milliseconds
  between that check and the `put_item`: DynamoDB cannot condition a
  write on "nothing overlaps this span" without a transaction over rows
  that do not exist yet, so two callers colliding inside that window
  would both be booked. Accepted for a two-clinic demo and documented in
  `booking.py` rather than hidden. The real fix, if it is ever wanted,
  is a conditionally-written per-clinic-slot lock item — a design
  change, not a line of defensive code.

- **Project name**: using "ClinicPilot" as a placeholder throughout
  — rename before final submission if a better name comes up.
- **Nova Sonic/BidiAgent stability**: marked experimental by AWS
  (Python 3.12+ required, known issue where misconfigured
  credentials hang silently instead of erroring). Budget time in
  week 1 to validate this works before depending on it — this is
  the highest-risk dependency in the stack.
- **SES sandbox**: sender/recipient will be the same personal Gmail
  address, verified manually in the SES console before the demo —
  not automated in CDK since it's a one-time manual verification
  step.
- ~~**How does an unauthenticated patient reach the voice endpoint?**~~
  **Resolved** — a **Cognito identity pool with unauthenticated
  (guest) identities enabled**, written into `architecture.md` → Auth
  and Access Model and into Invariants #5. AgentCore's WebSocket is
  SigV4-signed, so "no auth" could never mean "no AWS credential"; a
  guest identity issues short-lived role-scoped credentials with no
  user record, which is precisely the gap. It also keeps the vendored
  sample's presigning path (`aws-credentials.ts`,
  `websocket-presigned.ts`) working rather than rewriting the
  connection layer during the riskiest week. Rejected: our own
  API Gateway WebSocket bridge (a new deploy surface, and it discards
  working sample code) and patient login (contradicts
  `project-overview.md`). **Carries a build constraint**: the guest
  IAM role is handed to every visitor, so it may invoke the agent
  runtime and nothing else — no direct DynamoDB, S3, or Bedrock
  access on that role, ever. The identity pool stays separate from
  the staff user pool.

## Architecture Decisions

- **Multi-agent via Agent-as-Tool, not remote/A2A agents** — chosen
  over a single flat agent (more genuine Strands usage for judging)
  and over distributed A2A sub-agents (too much extra deployment
  surface for a solo 2-3 week build).
- **Multi-tenant data model, single-tenant demo scope** — every
  table/KB is `clinic_id`-scoped from day one, but only two clinics
  are seeded and no tenant-onboarding UI is built, to get the SaaS
  story without its full build cost.
- **Browser voice, not Amazon Connect/telephony** — a real phone
  number adds contact-flow/telephony integration work that doesn't
  meaningfully improve judging scores relative to its cost on this
  timeline.
- **CDK (Python) for all infrastructure** — keeps IaC in the same
  language as the agent/backend code, single consistent deployment
  story.
- **S3 + CloudFront for frontend hosting** — kept in the same CDK
  app as everything else, rather than introducing Amplify Hosting as
  a separate deployment paradigm.
- **Cognito for staff dashboard only** — patients remain
  unauthenticated (public demo access to the voice endpoint); staff
  dashboard is gated because it's a stronger "real product" signal
  for the Design judging criterion at low implementation cost.
- **AWS sample vendored under `vendor/`, not copied into
  `frontend/`/`backend/`** — kept as a pristine pinned copy so it
  stays identifiable as AWS's code while pieces are adapted out of it
  deliberately. Avoids entangling sample code with ours from day one
  and satisfies `ai-workflow-rules.md` → Protected Files ("treat the
  initial fork as reference code, not final code"). `architecture.md`
  → System Boundaries does not list `vendor/`; added here as the
  location for pinned third-party reference code.
- **Patients reach the voice endpoint with a Cognito *guest* identity,
  not with no credential at all.** "Unauthenticated patient" is a
  product statement, not a network one: AgentCore's WebSocket is
  SigV4-signed, so something must sign it. An identity pool's
  unauthenticated identities issue short-lived role-scoped AWS
  credentials to any visitor with no user record created, which is the
  only option that satisfies both "patients never log in" and "the
  socket is signed" — and it is what the vendored sample already does.
  The lasting constraint: that guest role is handed to everyone who
  opens the page, so it may invoke the agent runtime and nothing else.
  Any DynamoDB/S3/Bedrock reach on it would be a cross-tenant hole no
  amount of `clinic_id` discipline in the tool layer could close.

- **Tenant scoping is enforced in the index keys, not by convention** —
  the appointments-by-patient GSI is keyed on a composite
  `clinic_patient` (`{clinic_id}#{patient_id}`) attribute rather than on
  `patient_id`. A `patient_id`-keyed index would work (ids are unique
  across clinics) but would make a cross-clinic query *expressible*,
  which `architecture.md` -> Invariants #1 rules out. Costs one written
  attribute; buys an invariant the schema enforces instead of the
  reviewer.
- **No separate agent-actions table** — the dashboard's "log of
  autonomous actions" is derived from appointment reminder/reschedule
  history plus `Escalations`. `architecture.md` -> Storage Model names
  four tables and puts that history on the appointment; a fifth table
  would duplicate it.
- **Escalation `status` is a filter, not a key** — the dashboard reads
  a clinic's escalations newest-first from one GSI and filters to open
  ones, rather than maintaining a composite status key. The queue is
  small by construction (the agent escalates only when a human decision
  is needed), so the composite key would cost write complexity for no
  measurable read benefit.
- **Stack files live directly in `backend/infra/`, not a `stacks/`
  subpackage** — `architecture.md` → System Boundaries names
  `backend/infra/data_stack.py` etc. by path, so the flat layout is
  what the spec already describes. `config.py` sits alongside them as
  the one place names are defined; `app.py` is the CDK entrypoint.
- **Environment is a config value, not a separate CDK app** — one
  `ProjectConfig` read from `CLINICPILOT_ENV` (default `dev`) prefixes
  every stack and resource name, so a second environment is an env var
  rather than a code change. Only `dev` is deployed for the hackathon.
- **Sample's TypeScript CDK is reference-only; our CDK stays Python**
  — the sample ships five TS stacks. Re-implementing in Python CDK
  costs more than copying them, but `architecture.md` → Stack and
  `code-standards.md` both mandate Python CDK for a single-language
  deployment story, and mixing two CDK toolchains in one repo would
  be worse. The TS stacks are read as AgentCore wiring references.

- **The item schema lives in `backend/tools/schema.py`, and its overlap
  with the CDK is guarded by a test rather than by an import.** The
  tool layer cannot import `data_stack.py` (that would make business
  logic depend on `aws-cdk-lib`, and the two run in different venvs),
  and the CDK app should not depend on the tool package either. So key
  attribute names and index names are written in both places. The
  failure mode this creates is nasty and silent — DynamoDB answers a
  query against a misspelled key or a missing index with an empty
  result, inside a deployed Lambda, not here — so
  `backend/tests/test_schema_matches_infra.py` reads `data_stack.py`
  with `ast` (no CDK needed) and fails if any of the twelve shared
  constants disagree. It also imports `backend/infra/config.py`
  directly (pure stdlib) and asserts `dynamo.table_name` derives
  exactly what `ProjectConfig.resource_name` produces, so the *scheme*
  is compared, not just its default values.

- **One timestamp encoding, because timestamps are sort keys.** Every
  timestamp this layer writes goes through `to_iso8601`:
  `2026-08-27T14:30:00Z`, UTC, second precision, `Z` suffix, fixed
  width. `starts_at` and `created_at` are sort keys and DynamoDB
  compares strings bytewise, so a `+02:00` offset or a microsecond
  component would order items wrongly with no error at all. This is
  cheap now and unfixable-in-place later, once a table has mixed data.

- **Tool functions raise, they do not return error strings.** A tool
  that returned `{"error": ...}` would let a caller that forgot to
  check it hand an error message to a patient as an answer. The
  exceptions carry a stable `code`, and the `backend/agents/` wrappers
  are the layer that turns them into something a model can read.

- **A reschedule is not an appointment status.** It moves `starts_at`
  and appends to the appointment's reschedule history while the status
  stays `scheduled`. A `rescheduled` status would make "is this slot
  taken" a two-value check and would split the history the dashboard's
  autonomous-action log is derived from.

- **`ACTIVE_APPOINTMENT_STATUSES` is a set, not a `!= cancelled`
  check.** Availability, the day view, and the background scan all
  need "does this occupy its slot", and encoding that once means adding
  a future status is one edit rather than a hunt through comparisons.

- **Escalation `reason` is free text; `source` is an enum.** `reason`
  is written by the Escalation sub-agent and read by a human on the
  dashboard or in an SES email — it has no machine reader, and a closed
  reason vocabulary would be product behavior no context file defines.
  `source` is `voice` or `background` because
  `project-overview.md` describes exactly those two paths feeding one
  queue, and the queue has to show which is which.

- **A clinic's availability rules live entirely on its own item.** The
  five config attributes (`timezone`, `hours`, `closures`, `services`,
  `slot_minutes`) are together sufficient to decide whether a time is
  bookable — no global constant, no environment variable, no
  per-clinic branch in code. That is what makes "the same deployed
  agent serves two different clinics" (`project-overview.md` Goal 2) a
  property of the data rather than a claim, and it is why
  `slot_minutes` is per clinic rather than a module constant: a global
  one would be a second place a clinic's behaviour is defined.

- **Hours are wall-clock local; stored timestamps are UTC; the
  scheduling tools are the only conversion point.** A clinic says it
  opens at 09:00, not at an instant, so `hours` and `closures` cannot
  be UTC without breaking across a DST boundary. Storage cannot be
  local, because `starts_at` is a bytewise-ordered sort key. Fixing the
  boundary at the scheduling tools means no other layer — Lambda,
  dashboard, agent prompt — ever holds a local-time value it might
  compare against a stored one.

- **A slot is offered only if the whole service fits inside one opening
  interval.** Start times are generated on the `slot_minutes` grid, but
  the *duration* is what gets validated against the interval, so a
  60-minute consult is never offered at 12:30 against a 13:00 lunch
  break. This is also why `duration_minutes` need not be a multiple of
  `slot_minutes` — the grid places starts, the duration decides fit,
  and conflating the two would force every service length to be a
  multiple of the granularity.

- **Whole-day closures only.** A partial-day closure would be a second
  kind of interval subtraction layered on `hours`, doubling the branches
  in the one function the whole booking flow depends on, for a case the
  demo does not need. A clinic that closes early on a given day is
  representable as a change to `hours` if it is recurring.

- **"Closed today", "closed for a holiday", and "open but fully
  booked" are three distinguishable answers, not one empty list.**
  `check_availability` returns `is_open` and `closure_label` alongside
  `slots`, because a patient told "nothing available" when the clinic
  is shut for a training day has been told something misleading, and
  the model cannot recover the difference from an empty list. The
  label is the clinic's own text; the tool returns data and never the
  phrasing, which stays the agent's job.

- **Slot arithmetic happens in UTC, on intervals converted once.**
  `hours` are parsed as clinic-local wall clock, converted to UTC
  immediately, and every comparison after that — grid stepping, fit,
  overlap — is between absolute instants. Stepping a `timedelta`
  across an aware *local* datetime advances the wall clock, not the
  elapsed time, so on a DST-transition day it would silently produce
  slots an hour wide in one direction. The local `HH:MM` strings in
  the response are rendered back at the very end, for speech only.

- **A malformed clinic config raises `ConfigurationError`; it never
  degrades to fewer slots.** Inverted or overlapping `hours`, a
  non-positive `slot_minutes`, an unknown timezone — each fails loudly
  rather than being skipped. This is the one function the whole
  booking flow trusts, and a config fault that quietly produced *some*
  plausible slots would surface as a double-booking days later. The
  one exception is a malformed `closures` entry, which is ignored:
  there, failing loudly would take a clinic's entire calendar offline
  over one bad row.

- **Availability is conservative when data is ambiguous.** An
  appointment with an unrecognised status, or missing its `ends_at`,
  still blocks the slot containing it. Offering a slot that is
  actually taken produces a double-booked patient in a chair;
  withholding a free one produces a slightly worse answer. Those are
  not symmetric, so the tie is broken deliberately rather than by
  whichever branch fell out of the code.

- **Services are matched by id *or* name, ids first.** The value
  arrives from speech, so a model that heard "cleaning" may send
  either the id or the spoken name; requiring the id would push a
  lookup table into the agent prompt, which is exactly the per-clinic
  behavior that is supposed to live in the clinic's own item. Ids are
  matched before names so one entry's name can never shadow another
  entry's id.

- **Phone numbers are normalised at the boundary, not at read time.**
  The `by-phone` index is an equality match, so "555 123 4567" from
  speech and "+15551234567" from a seed script have to converge before
  either is stored, or the caller lookup silently misses.

- **Reschedule and cancel live in one module, and a cancellation is a
  move to nowhere.** They share the part that is easy to get wrong —
  working out which of a caller's appointments is meant, and proving it
  is theirs — so splitting them would put that resolution in two
  places. And a cancel writes the same `reschedule_history` entry a
  move does, with `to: null`: `status` records that an appointment was
  called off but not who did it or why, and the dashboard's action log
  needs both. One list to read rather than a status plus a second
  attribute.

- **An appointment is reached only through its own patient's index
  partition, never fetched by id.** Both writes accept an optional
  `appointment_id`, but it is matched *within* the caller's own
  `by-patient` result rather than passed to `get_item`. Ownership then
  holds by construction: a guessed or carried-over id cannot reach
  another patient's row, and past or already-cancelled appointments are
  out of reach without a second status check. Costs one query that was
  needed anyway.

- **A caller with several upcoming appointments is refused, not
  guessed at.** The error names each one's service, local time, and id,
  so the agent asks in one turn. Taking the soonest would be a silent
  wrong cancellation, discovered by the patient at a closed clinic — a
  failure with no error message anywhere in the system.

- **The appointment being moved does not block its own move.**
  `offerable_slots_for_date` takes an `exclude_appointment_id`, dropped
  inside `_booked_spans` where items still have ids. The alternative —
  cancelling first, then re-checking — would leave a patient with no
  appointment if the new time turned out to be unavailable, and the
  alternative to *that* is a second copy of the overlap rule.

- **The two changing writes are conditional; the booking write cannot
  be.** A move or a cancel is conditioned on the row still being
  `scheduled` and still at the time it was read at, so two sessions
  changing one appointment resolve to a single winner. That is possible
  here and impossible for `book_appointment` for a concrete reason:
  this race is between rows that already exist, and DynamoDB can
  condition on a row. The booking race is over a row that does not
  exist yet.

- **An escalation is written unverified, on purpose.**
  `create_escalation` validates the *shape* of `patient_id` and
  `appointment_id` and stores them without checking that either
  resolves. Every other write in this layer reads first; this one must
  not, because it is the path taken when something has already gone
  wrong. A lookup here would add a way for the record of a failure to
  itself fail, and a human can act on a mis-referenced escalation but
  not on one that was never written. It is also why the module reads
  nothing at all on the create path — asserted by a test, not just
  intended.

- **The escalation queue's cap is applied after the status filter, in
  Python — never as DynamoDB's `Limit`.** `Limit` bounds items
  *scanned*, before any filtering, so asking DynamoDB for 50 would
  return an empty queue for a clinic whose 50 newest escalations are
  all resolved. This is the price of the "`status` is a filter, not a
  key" decision above and is the correct half of that trade: paging
  until enough open items are found costs reads only when the queue is
  mostly resolved, whereas a composite status key costs write
  complexity on every escalation.

## Session Notes

- **The reschedule/cancel entry was filed under "In Progress" rather
  than "Completed"** by the previous session, below a "- None." line,
  while describing verified, committed work (`git log`: `a65db21`).
  Reconciled before starting this unit, per `CLAUDE.md` ("if the repo
  and the tracker disagree, stop and reconcile"): the entry moved to
  Completed unchanged and "In Progress: None." now stands alone. No
  work was lost or redone — this was a filing slip, not a state
  disagreement.

- **DynamoDB's `Limit` counts items scanned, not items returned.** It
  applies *before* a `FilterExpression` and before any filtering the
  caller does in Python, so a capped query over a partition whose
  newest items are all filtered out comes back empty rather than short.
  `list_open_escalations` therefore pages and caps in Python. This will
  bite again wherever the dashboard reads a status-filtered list —
  today's appointments most obviously — so cap after the filter there
  too, or use a key that does not need one.

- **Second venv: `backend/.venv`**, on 3.12 like the infra one, with
  `boto3` + `pytest` from `backend/requirements-dev.txt` (runtime deps
  stay in `requirements.txt` so a Lambda bundle never ships the test
  runner). Run the suite as `.venv\Scripts\python.exe -m pytest` from
  `backend/` — `backend/pytest.ini` sets `pythonpath = .` so `tools`
  imports as a package. Two venvs rather than one because the CDK app
  pulls `aws-cdk-lib` and the tool layer must not.

- **`tzdata` is now a runtime dependency** (`backend/requirements.txt`).
  `zoneinfo` reads the operating system's IANA database, and Windows
  does not have one — without the package, `ZoneInfo("Europe/London")`
  raises and *every* clinic looks misconfigured locally while working
  fine once deployed. Cheap insurance, and it also pins the tz data
  for Lambda rather than inheriting whatever the runtime image ships.

- **DynamoDB numbers come back as `Decimal`.** `slot_minutes` and
  `duration_minutes` are read through a coercion helper, not used
  directly: `timedelta(minutes=Decimal("15"))` raises `TypeError`.
  The test fixtures deliberately use `Decimal` for exactly this
  reason, so the suite would catch it if the coercion were dropped.

- **The scheduling tests fake the two table accessors, not boto3.**
  `tools.scheduling` touches DynamoDB only through `clinics_table()`
  and `appointments_table()`, so substituting those exercises the real
  function end to end with no credentials, no moto, and no network —
  including the pagination loop and the key-condition construction,
  which are asserted by reading the recorded `KeyConditionExpression`
  back through boto3's own `get_expression()`.

- **boto3 is imported lazily inside `dynamo.py`**, not at module top.
  It keeps `tools.schema` and `tools.validation` pure-stdlib and
  importable with no AWS SDK present, which is what lets most of the
  suite run without touching boto3 at all. The boto3 resource and the
  table handles are `lru_cache`d — cold-start cost, and they are
  stateless client handles, not the per-session state
  `code-standards.md` forbids at module level.

- **`TableV2`, not `Table`, for the DynamoDB tables.** `TableV2` is the
  current construct and takes the environment branch (removal policy,
  PITR, deletion protection) cleanly; single-region is just "no
  replicas". It synthesises as `AWS::DynamoDB::GlobalTable` rather than
  `AWS::DynamoDB::Table` — expected, but worth knowing before reading a
  template or a console page and wondering. Note also that constructing
  a `TableV2` emits `TableGrantsProps#encryptedResource` /
  `#policyResource` deprecation warnings from inside aws-cdk-lib 2.266
  itself; they are not caused by anything this app passes and there is
  nothing to fix on our side.

- **Two `.gitignore` faults found while vendoring** (both fixed):
  (1) the root `.gitignore` was the stock Python template, whose
  unanchored `lib/` pattern also matches `cdk/lib/` — it would have
  silently dropped all five CDK stack source files from git, breaking
  the "reproducible via `cdk deploy` from a clean account" success
  criterion in a way that only shows up after a fresh clone. Anchored
  to `/lib/`. (2) It ignored `.env` but not `.env.local`, which is
  exactly the filename the sample uses for local credentials/debug
  config — a secret-leak path. Added `.env.local` and `.env.*.local`,
  plus the missing `node_modules/` and `cdk.out/`.
- **The sample's UI is AWS Cloudscape, not Tailwind + shadcn/ui.**
  `ui-context.md` assumes Tailwind/shadcn, so the voice screen is a
  genuine re-style rather than a light adaptation. The behavioral
  parts (audio worklet, presigned WebSocket, `useVoiceAgent` hook)
  carry over; the presentational components mostly do not. Worth
  budgeting for when item 4 comes up.
- **Python 3.12.10 installed** (`winget install Python.Python.3.12
  --scope user`), resolving the earlier 3.11-vs-3.12 gap ahead of the
  Nova Sonic / BidiAgent work. `backend/infra/.venv` was rebuilt on it
  and `cdk synth` re-verified. Caveat: bare `python` on this machine
  resolves to an unrelated `hermes-agent` venv running 3.11, and the
  installer put 3.12 ahead of 3.11 only in the *persisted* user PATH —
  so use **`py -3.12`** (or the project venv) when a specific
  interpreter matters, rather than trusting `python`. The `py` launcher
  now defaults to 3.12.
- **CDK CLI is not installed globally; `npx aws-cdk@2` was used** to
  verify `synth`/`list`. On Windows the CLI spawns the app through
  `cmd.exe`, which rejects a forward-slash venv path — the app must be
  passed as `.venv\Scripts\python.exe app.py` when the venv is not
  activated. Recorded in `backend/infra/README.md` so it isn't
  rediscovered.
- **`Stack.add_dependency` is deprecated in aws-cdk-lib 2.266**; used
  `add_stack_dependency` instead. Worth watching for other deprecated
  APIs when copying wiring out of the vendored TS stacks, which pin an
  older CDK.
- Hackathon context: AWS "Agents for Humans" hackathon, Strands
  Agents SDK, Professional Agents track, $40k prize pool, 2-3 week
  build window (not the full 6-week program length).
- Constraint: no third-party tools (no Vapi, no WhatsApp/n8n) — this
  build is intentionally AWS-native end to end, distinct from the
  developer's other in-progress projects (Vapi clinic voice demos,
  WhatsApp booking agent for Travel Campus), which are separate and
  unrelated to this one.
- Submission requirements to keep in view throughout: public repo
  URL with MIT/Apache license, README, architecture diagram, ≤5min
  demo video (must cover problem/audience/why it matters), AWS
  Builder ID, optional live demo link (scores higher), optional
  bonus builder.aws.com post titled with "Agents for Humans".

- **Local day boundaries are built from dates, never from `+ 24h`.**
  `tools.scheduling._local_midnight` combines a calendar date with
  midnight in the clinic's zone; adding `timedelta(days=1)` to an aware
  local midnight gives 23:00 or 01:00 on a DST-transition day. It bit
  the original single-day query window (an hour short each autumn) and
  would bite any future code that walks days, so the day boundary has
  one implementation and a test that spans 2026-10-25.
