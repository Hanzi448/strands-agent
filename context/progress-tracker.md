# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- **Phase 3 has started.** Phase 2's tool layer is complete: the AWS
  sample is vendored as reference code, `backend/infra/` synthesises
  with the four DynamoDB tables and the KB source bucket defined in
  `data_stack.py`, and the agent stack now also carries one Bedrock
  Knowledge Base per demo clinic over Amazon S3 Vectors (the other three
  stacks — API, automation, frontend — are still empty). `backend/tools/`
  has its foundation, the complete availability read surface, the
  complete scheduling write surface, the complete escalation surface,
  and the FAQ read (`query_faq`, over the Knowledge Base infrastructure
  that landed just before it). All four tables are written by that
  layer, and `backend/tools/` itself is complete — five modules, no tool
  left to write.
- **The agent tree is now complete: three sub-agents, not two.**
  `faq_agent.py` (Next Up #2) has landed and is wired into the
  Orchestrator, so `backend/agents/` now holds Scheduling, FAQ and
  Escalation, all three reachable only as tools of the one Orchestrator
  a patient talks to. Next Up #2 is fully done — see Completed.
- `backend/agents/` now holds its **foundation** (`session.py`,
  `results.py`), **all three patient-facing sub-agents** — Scheduling
  (`scheduling_agent.py`), FAQ (`faq_agent.py`) and Escalation
  (`escalation_agent.py`) — the **Orchestrator** (`orchestrator.py`)
  that routes to them, the **voice layer** (`voice.py`: the same
  Orchestrator built as a `BidiAgent` over Nova Sonic), and **both
  local interfaces** — `cli.py` (keyboard) and `mic.py` (microphone).
  The agent tree is complete, wired, and drivable two ways: a typed
  turn or a spoken one goes in, reaches `backend/tools/`, and comes
  back out as a sentence. `frontend/`, `backend/lambda/` and `seed/`
  do not exist yet.
- **The local half of Phase 3 is finished.** `python -m agents.mic
  <clinic-id>` opens a Nova Sonic connection, pumps a microphone and
  speakers through `BidiAgent.run`, prints both sides of the call and
  times every silence in it. What is left of the voice path is the
  deployed one: the AgentCore entrypoint (Next Up #1), which is the same
  `run` call with a WebSocket's channels instead of a sound card.
- **The deployed entrypoint's code now exists too.**
  `backend/agents/agentcore_app.py` is a FastAPI `/ping` + `/ws` shaped
  like the vendored sample's `agent/strands_agent.py`, verified offline
  through FastAPI's own ASGI test client.
- **`agent_stack.py` now provisions the AgentCore Runtime too, and
  `backend/Dockerfile` exists.** `cdk synth` needs neither Docker nor AWS
  credentials for this (the container image is an ordinary CDK asset,
  fingerprinted at synth time and only built/pushed during `cdk deploy`),
  so this closed the code-and-infra half of Next Up #1 that this
  environment *could* do. What is left of Next Up #1 is no longer code:
  it is the actual `cdk deploy` (a container build/push this environment
  cannot do without Docker, and stack creation it cannot do without
  credentials) and a real Bedrock connection to listen to — see Session
  Notes.
- **Still nothing here has met a real model.** Both interfaces exist and
  run, but running either for real needs credentials and seeded clinics
  (Next Up #5); against an unconfigured shell they fail as designed, on
  the way in, naming the cause. So the four system prompts remain
  unjudged by anything but a script, no audio has been heard, and every
  latency number `mic.py` was built to print is still unmeasured.
- **The background job is now finished, code and CDK both.**
  `tools/automation.py` (`run_daily_scan`) and
  `lambda/background_scan.py` were the Python half: per upcoming
  appointment, escalate a patient's own no-show history to staff or send
  a reminder — never both, never an automatic reschedule (a product
  decision the user made this session; see Completed).
  `automation_stack.py` is now the CDK half: one Lambda packaging just
  `lambda/` and `tools/`, and one EventBridge Scheduler schedule per
  demo clinic, each firing that same Lambda with its own `clinic_id`.
  `cdk synth` verifies it end to end (see Completed); only the actual
  `cdk deploy` and a real send remain, blocked in this environment for
  the same reason Next Up #1 is (Session Notes) — folded into the new
  Next Up #1 and #3 respectively rather than kept as their own item.
- **The dashboard API's Python half has landed.** `tools/appointments.py`
  gained `list_appointments_for_clinic` (the clinic-wide read the
  Appointments screen needs; every existing appointment read was
  per-patient) and `lambda/dashboard_api.py` is now a real module: four
  routes over it and the three existing escalation reads/write, Cognito
  claim scoping, and the `{data, error}` response shape
  `code-standards.md` requires. What is left of Next Up #2 is
  infrastructure and UI, not Python — see Next Up and Completed.
- **The dashboard's CDK half has landed too.** `api_stack.py` now
  provisions the staff Cognito user pool (with its `custom:clinic_id`
  custom attribute, self-sign-up off), a REST API Gateway with the four
  routes `dashboard_api._ROUTES` already fixed, each behind a Cognito
  authorizer, and the Lambda running `dashboard_api.handler` with an
  execution role scoped to exactly the `Appointments`/`Escalations`
  calls it makes. `cdk synth` verifies it alone and as part of all five
  stacks. What is left of Next Up #2 is UI only
  (`frontend/src/dashboard/`) plus the unrelated guest-identity Cognito
  identity pool the voice endpoint still needs — see Next Up.
- **The dashboard's UI has landed too, and with it `frontend/` itself.**
  `frontend/src/dashboard/` is a Cognito login screen, an appointments
  view (with each appointment's own reminder/reschedule history readable
  inline, since that is what `project-overview.md` -> Staff Dashboard's
  "log of autonomous actions" turned out to mean once there was a UI to
  render it in), and an escalation queue with a detail modal and "Mark
  Resolved". This is also the first thing under `frontend/` at all, so
  the unit scaffolded the Vite + React + TypeScript + Tailwind +
  shadcn/ui project `architecture.md` -> Stack specifies, scoped to only
  what the dashboard needs — `frontend/src/voice/` is still unbuilt and
  not this unit's concern. `npm run build` passes; the login screen, its
  unconfigured-backend error state, and the appointment/escalation cards
  were screenshotted in a headless browser (see Completed) — the
  farthest any frontend work in this repo has been verified without a
  deployed backend to point it at.
- **The staff dashboard is now entirely finished, including 2b.**
  `api_stack.py` gained the last piece: a separate, guest-only Cognito
  identity pool for the patient-facing voice endpoint
  (`_build_patient_guest_identity`), its role granted exactly
  `runtime.grant_invoke_runtime` on the AgentCore Runtime `agent_stack.py`
  builds and nothing else. `cdk synth` verifies it alone and as part of
  all five stacks. Nothing left in `progress-tracker.md` -> Next Up is
  dashboard work.
- **`seed/` now exists, and with it the code half of Next Up #2.**
  `clinic_data.py`, `sample_data.py`, `faq_content.py`, `aws_io.py`, and
  `run_seed.py` seed the two demo `Clinics` items, six sample
  appointments (through the real `check_availability`/`book_appointment`
  path, never a hand-built item), three FAQ documents per clinic, and the
  two staff Cognito accounts. `python -m seed.run_seed --dry-run` runs
  today, in this environment, touching no AWS client; the real run is
  blocked the same way Next Up #1's `cdk deploy` is (Session Notes). See
  Completed.
- **The buildable half of the submission-assets item has landed.** A
  root `LICENSE` (MIT), `docs/architecture.md` (a Mermaid system diagram),
  and a rewritten root `README.md` now exist. What is left of Next Up #2
  — demo video, live demo link, AWS Builder ID — is blocked on the same
  missing deploy as Next Up #1, not on anything this environment could
  still write.

## Current Goal

- **Phase 3: the agents.** The full four-agent tree is in — Orchestrator
  over Scheduling, FAQ and Escalation — verified end to end offline, and
  reachable three ways: `python -m agents.cli <clinic-id>` from a
  keyboard, `python -m agents.mic <clinic-id>` from a microphone, and
  (once deployed) `agents.agentcore_app:app`'s `/ws` from a browser.
  All of Phase 3's code is now written; both remaining items are
  infrastructure and data, not agent logic. Next Up #1's CDK resources
  and Dockerfile are now written too (see Completed); what is left is
  **actually deploying it** (a container build/push and real stack
  creation, both blocked in this environment -- Session Notes) and
  **pointing any interface at something real**
  (credentials plus seeded clinics, #2). That second one is the
  bottleneck for three open questions at once — who greets the patient
  and what it costs in dead air, which voice each clinic answers in,
  and which text model the sub-agents reason with — plus one fact no
  test can settle: whether a real Knowledge Base retrieval actually
  reads back like an answer to a patient's question. All of it is
  answered by listening to one call rather than by argument.
  Nothing in `backend/tools/` may move into an agent definition
  (`architecture.md` -> Invariants #3): the agents are a thin
  model-facing surface over functions the background Lambda will call
  directly. The background job, including its CDK half, is now entirely
  done (see Completed) — its own remaining step is the same blocked
  deploy as Next Up #1's. The staff dashboard — Python (the clinic-wide
  appointment read, `dashboard_api.py`'s four routes), CDK (Cognito user
  pool, API Gateway, Lambda), UI (`frontend/src/dashboard/`), and now the
  patient-facing guest-identity Cognito pool too — is entirely done (see
  Completed); nothing dashboard-shaped remains in Next Up.
  The seed scripts' code (config, sample appointments, FAQ documents, and
  the two staff Cognito accounts) is now done too (see Completed) —
  `seed/` is written, offline-tested, and runnable in `--dry-run`. What
  remains of Phase 3 is no longer code anywhere in this repo: it is
  Next Up #1's `cdk deploy` and then `python -m seed.run_seed` for real,
  both blocked in this environment for the same reason (Session Notes) —
  see Next Up.

## Completed

- **Root `LICENSE`, `docs/architecture.md`, and a rewritten root
  `README.md`** (Next Up #2, first half — the buildable half of
  "Architecture diagram, README, demo video, submission assets"). The
  only unit this session could actually do: the other three (demo video,
  live demo link, AWS Builder ID) all need a deployment or an account
  action this environment cannot perform, same as Next Up #1 (Session
  Notes).
  **`LICENSE`** is MIT, satisfying the hackathon's "public repo with
  MIT/Apache license" requirement — the repo root had none before this
  (the only existing `LICENSE` was the vendored sample's own MIT-0, which
  covers only `vendor/`).
  **`docs/architecture.md`** is a Mermaid system diagram (renders natively
  on GitHub) covering the full request paths — patient voice through the
  guest Cognito identity pool to AgentCore, the Orchestrator's three
  Agent-as-Tool sub-agents, `backend/tools/` as the single mutation path
  for both the live agent and the background job, the per-clinic
  Knowledge Base, and the staff dashboard's Cognito-gated REST path —
  plus a short reading guide pointing each structural choice back at
  `architecture.md` -> Invariants rather than restating them. It states
  its own status honestly: designed and built in code/CDK, not yet
  deployed.
  **Root `README.md`** replaced a one-line stub. It covers project
  summary, current status (built and offline-verified, not deployed, and
  why), the stack table, an accurate repository layout (checked against
  the real `backend/`, `frontend/`, `seed/` contents rather than assumed),
  local run instructions for the four things this environment can
  actually run (backend pytest, `cdk synth`, `npm run build`, seed
  `--dry-run`), and a submission checklist section. No instruction here
  claims something works that hasn't been verified — the deploy and seed
  commands are named but marked blocked, consistent with
  `progress-tracker.md` itself.
  Nothing in `backend/`, `frontend/`, `seed/`, or `context/` (other than
  this file) was touched — a docs-only unit, verified by reading the
  written files back and by the Mermaid syntax following the same
  quoted-label patterns used elsewhere (no live renderer available in
  this environment to confirm visually).

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

- **`backend/agents/` foundation + the Scheduling sub-agent**
  (Next Up #1, first half). The first code in this repo a model talks
  to. Three modules and a 65-test suite.
  **Split from the old Next Up #1**, which bundled the Orchestrator and
  two sub-agents. That item allowed a split and suggested "Orchestrator
  first"; this went the other way, and the reason is
  `ai-workflow-rules.md` -> When to Split Work: a router with nothing to
  route to cannot be verified end to end, while a sub-agent over real
  tools can. Escalation shipped next; the Orchestrator is Next Up #1.
  **`clinic_id` is enforced by shape, not by a guard.** `session.py`
  holds a `ClinicSession` created once per call; the tools close over
  it, so `clinic_id` is not a parameter of anything the model is shown
  and is absent from every JSON schema. A model cannot pass a clinic it
  was never offered, and a prompt-injected "use the other clinic" has
  nothing to bind to (`architecture.md` -> Invariants #1). The
  tool-layer functions still run their own `require_clinic_id` first,
  so `code-standards.md` -> Python holds on both sides. `start()` reads
  the clinic once, which also fails a bad id, a missing clinic or an
  unresolvable timezone *before the greeting* rather than inside the
  first booking.
  **The system prompt withholds the opening hours, deliberately.**
  `ClinicSession.describe()` gives the model the clinic's name, its
  local date twice (spoken, so it is not read out digit by digit, and
  `YYYY-MM-DD`, because that is what the tools take) and its services
  with ids and durations. It does *not* give it `hours` or `closures`:
  `check_availability` already composes hours, breaks, holidays,
  service duration and existing bookings into the only correct answer,
  and a copy of the hours in the prompt is an invitation to answer
  "we're open till five" without asking. Durations are normalised out
  of DynamoDB `Decimal`s, or the prompt would say `Decimal('15')`.
  **A refusal has to arrive as a refusal.** `results.py` translates
  `ToolError` into the `{"status": "error", "content": [...]}` shape
  Strands passes through untouched — a failure returned in the ordinary
  payload shape is one the model is told went fine. `ValidationError`,
  `NotFoundError` and `ConflictError` keep their messages verbatim
  (they are things the *patient* can answer, and the tool layer already
  writes them for the model, naming the alternatives).
  `ConfigurationError` and any unexpected exception are logged and
  replaced with one fixed message, because the first quotes internal
  attribute paths and the second would otherwise reach a speech model
  as `Error: KeyError - 'starts_at'` with the microphone open.
  **`scheduling_agent.py` decides nothing.** Four `@tool` wrappers over
  `check_availability`, `book_appointment`, `reschedule_appointment`
  and `cancel_appointment`, each one argument-forwarding only; the
  sub-agent; and `scheduling_agent_tool`, the Agent-as-Tool wrapper the
  Orchestrator will hold. `actor` is not exposed — it is what the
  dashboard reads to show which moves the agent made unprompted, so it
  is not a value a model chooses, exactly as `source` is not on
  `create_escalation`. The sub-agent is built fresh per call and gets
  `callback_handler=None`: its answer is a return value for the
  Orchestrator, and in AgentCore stdout is the log, not the patient's
  ear.
  **Dependency added**: `strands-agents>=1.54` in
  `backend/requirements.txt`. `backend/tools/` still must not import
  it, and a test now enforces that (see below).
  Verified: `pytest` from `backend/` — **445 passed** (380 before, 65
  new), the pre-existing 380 unchanged; nothing outside `backend/agents/`
  and `requirements.txt` was touched. The suite runs entirely offline: a
  `ScriptedModel` implementing the Strands `Model` interface emits real
  Bedrock-shaped stream events, so the event loop, the tool executor and
  the `@tool` decorator all run for real and only the model's judgement
  is replaced. That drives Agent-as-Tool end to end — request in, tool
  call, `backend/tools/` against the same fake tables the tool suites
  use, spoken answer out — including a booking that reaches the table
  and a refusal that arrives with `status: "error"`. Tenancy is
  asserted on the schemas (no tool offers a clinic; passing one is a
  `TypeError`), on what reached DynamoDB, and on two sessions in one
  process not seeing each other's clinic. Each wrapper is also compared
  against its tool-layer function called directly, so a rule drifting
  up into the agent layer shows as a disagreement between the two. New
  guard: `backend/tools/` is scanned for any `strands` /
  `bedrock_agentcore` import, since this package is the first thing
  that could break `architecture.md` -> System Boundaries by tempting a
  `@tool` decorator one module too far down.
  **Not verified, and cannot be yet**: a live text conversation against
  a real model. It needs seeded clinics in deployed tables (Next Up #7,
  over a deployed data stack), so the text interface the old item asked
  for lands with the Orchestrator, which is the thing worth talking to.
  Nothing here has reached Bedrock.

- **The Escalation sub-agent** (`backend/agents/escalation_agent.py`,
  Next Up #1). The handover to a human — `architecture.md` ->
  Invariants #6's route for anything outside the rules
  `backend/tools/` encodes — and the second half of the old bundled
  agent item. One module, a 29-test suite, and the same four-part shape
  as `scheduling_agent.py`: `escalation_tools`, `build_escalation_agent`,
  `escalation_agent_tool`, and a system prompt formatted with
  `ClinicSession.describe()`.
  **It holds one tool, and the choice of which is the point.**
  `tools/escalations.py` has four functions; only `create_escalation`
  is here. `list_open_escalations`, `get_escalation` and
  `resolve_escalation` answer "what is outstanding at this clinic?"
  and "who dealt with it?" — staff questions, behind Cognito on the
  dashboard (`architecture.md` -> Invariants #5). A patient-facing
  agent holding any of them could read another caller's complaint out
  loud. The suite names all three individually, so wiring one back
  fails a test that says why.
  **`source` is not exposed**, for the reason `actor` is not on
  `reschedule_appointment`: it records which path raised the row, and
  each path knows its own. This module passes `voice` explicitly rather
  than leaning on the default, because the background Lambda will call
  the same function with `background` and the contrast is the whole
  point of the attribute.
  **`patient_id` and `appointment_id` *are* exposed**, which was the
  one real decision. They are ids a booking result carries, so the
  conversation genuinely holds them, and the tool layer already asked
  for them ("it is how staff reach the person back"). The hallucination
  risk is real but already settled one layer down: `create_escalation`
  stores back-references unverified on purpose, because a stale
  reference must never stop an escalation being written. Exposing them
  keeps the wrapper pure forwarding; withholding them would push the
  patient's phone number into free text instead. Both docstring and
  prompt say: only an id a tool returned in this conversation, never a
  constructed one.
  **The shared failure message is overridden in the prompt.**
  `results.INTERNAL_FAILURE_MESSAGE` tells the model to say a member of
  staff will follow up — true when a *booking* tool breaks, false here,
  because the thing that records the follow-up is the thing that just
  failed. Fixed in this agent's system prompt (if the tool did not
  succeed, nothing was recorded: say so, do not promise a callback)
  rather than by making the shared message vaguer for every other
  agent. A test pins both halves so the two cannot drift.
  Verified: `pytest` from `backend/` — **474 passed** (445 before, 29
  new), the pre-existing 445 unchanged; nothing outside
  `backend/agents/` was touched (`escalation_agent.py` added,
  `agents/__init__.py`'s module list updated). Offline throughout,
  reusing the `Escalations` fake from `test_escalations.py`, the clinic
  fixtures from `test_scheduling.py` and the `ScriptedModel` from
  `test_scheduling_agent.py` rather than restating any of them. Agent-
  as-Tool is driven end to end — situation in, `create_escalation`
  against the fake table, spoken answer out — including a failed write
  that comes back as `status: "error"` and never as a recorded
  escalation, and a final test asserting the two sub-agents' tool sets
  are disjoint. Two guards were mutation-checked: exposing `source`
  and leaking `list_open_escalations` each fail the tests that name
  them.
  **Not verified, and cannot be yet**: anything against a real model,
  and whether the prompt's "once, and once only" actually stops a
  duplicate queue card. Both need the Orchestrator and seeded clinics.

- **The Orchestrator** (`backend/agents/orchestrator.py`, Next Up #1,
  first half). The agent a patient actually talks to, and the thing
  that makes the two sub-agents reachable at all
  (`architecture.md` -> Invariants #2). One module, a 37-test suite.
  **Split from Next Up #1**, which bundled the Orchestrator with the
  local text interface. Same reasoning as the sub-agent split before
  it (`ai-workflow-rules.md` -> When to Split Work): the Orchestrator
  is verifiable end to end offline against scripted models, and the
  CLI is the first thing in this repo that cannot be — it needs
  credentials and seeded clinics. Bundling them would have made the
  verifiable half wait on the unverifiable one.
  **Its whole tool surface is the two sub-agents.** No
  `backend/tools/` function is reachable from it, so there is no path
  by which the front desk books an appointment or writes an escalation
  without an assistant in between — the appointment rules stay in one
  place (Invariants #3) and this module stays about routing rather
  than about diaries. The suite names `check_availability`,
  `book_appointment`, `reschedule_appointment`, `cancel_appointment`,
  `create_escalation` and `find_upcoming_appointments` individually, so
  wiring any of them up fails a test that says why.
  **It is the only agent in this package that remembers anything.** A
  sub-agent is rebuilt per call and keeps no conversation; the
  Orchestrator is built once per session and accumulates `messages`.
  That is the division of labour the Agent-as-Tool pattern buys: the
  patient's thread of talk in one place, and the multi-turn dance a
  booking takes kept out of it. Both halves are asserted in one test
  run — the front desk sees 1, 3 then 5 messages while the scheduling
  assistant sees 1 and 1.
  **One `model` parameter threads through all three agents.**
  `build_orchestrator(session, model)` passes the same model into both
  sub-agent wrappers, so a session cannot end up half on one model and
  half on another. This does not settle the open question below about
  *which* text model — it makes sure there is one place to settle it.
  **`start_call(clinic_id)` is the single entry point** for anything
  driving a conversation (the CLI next, the voice bridge later), so no
  caller constructs a `ClinicSession` by hand and skips the checks
  `ClinicSession.start` runs. A missing clinic id, an unknown clinic or
  an unresolvable timezone fails there, before the greeting, rather
  than inside the patient's first booking.
  **The prompt's job is to stop it talking.** A fluent model at a front
  desk will invent an opening time or a price because it sounds
  helpful, so the prompt says in as many words that anything it tells
  the patient about the diary, prices, treatments or policies must have
  come back from an assistant in this conversation. It also carries the
  two honesty rules the layer below cannot enforce: never confirm a
  booking the scheduling assistant did not report doing, and if the
  escalation assistant could not record something, do not promise a
  callback. `session.describe()` gives it the clinic's name, local date
  and services — enough to ask "which treatment?" and no more.
  **What is not an escalation is stated as explicitly as what is.** A
  taken slot, a name that does not match the number, a day the clinic
  is closed: things the patient can settle, and a queue full of them is
  a queue where the cards that need a person are lost.
  **`callback_handler=None` here too**, for a different reason than the
  sub-agents': its output *is* the patient's answer, but rendering it
  belongs to the interface layer. Strands' default handler prints every
  token and tool call to stdout, which in AgentCore is CloudWatch — a
  whole call including the patient's name and phone number.
  Verified: `pytest` from `backend/` — **511 passed** (474 before, 37
  new), the pre-existing 474 unchanged; nothing outside
  `backend/agents/` was touched (`orchestrator.py` added,
  `agents/__init__.py`'s module list updated). Offline throughout: one
  `ScriptedModel` (the Scheduling suite's) stands in for all three
  agents, so its script is the turns of the whole tree interleaved in
  the order they actually run and a routing change shows up as a script
  that no longer fits. Four whole calls are driven end to end — a
  booking that reaches the appointments table, a refund question that
  reaches the escalation queue *and leaves the diary untouched*, a
  cross-clinic call that reaches only `clinic-cosmetic`, and a broken
  clinic config whose attribute path never gets past `results.py`.
  Every fake and fixture is imported from the suite that owns it. Three
  guards were mutation-checked: leaking a tool-layer function onto the
  front desk and dropping the model threading each fail the tests that
  name them; skipping `ClinicSession.start` in `start_call` turned out
  to be behaviourally equivalent (the timezone fault still surfaces via
  `describe()` at build time), so that is a real equivalence rather
  than an untested gap.
  **Not verified, and cannot be yet**: anything against a real model.
  Whether the routing prompt actually keeps a fluent model from
  answering a price question itself is exactly what the next unit
  exists to find out.

- **`backend/agents/cli.py`: the local text interface** (Next Up #1).
  `python -m agents.cli <clinic-id>`, run from `backend/`: a keyboard
  loop over `start_call`, printing the Orchestrator's answer and reading
  the next line. The first thing in this repo that drives a conversation
  from outside a test.
  **It holds nothing but the loop.** No clinic logic, no tool call, no
  prompt text — a rule that lived in this file would be a rule the voice
  layer does not get (`code-standards.md` → General). Its whole surface
  is `parse_args`, `take_turn`, `run_call` and `main`, and the agent it
  drives is built once and kept, because that agent *is* the
  conversation.
  **The operator's controls are never turns.** `exit`/`quit` (whole-line
  match only, so a patient can say the word), Ctrl-D and Ctrl-C hang up
  without reaching the model; a blank line is a slip and is not sent,
  since it would spend a model call to say nothing. A patient's
  "goodbye" is an ordinary turn — what the agent does with it is part of
  what this interface exists to show.
  **A failed turn is not a failed call.** The model call is the only
  thing in the loop that touches a network, so a throttle prints one
  error line, logs the stack, and leaves the call open with every turn
  so far still in the agent's `messages`. Dropping the session would
  throw away exactly the turns that were paid for.
  **Errors read differently here than in `results.py`, deliberately.**
  That module hides a `ConfigurationError` because the model has a
  microphone open; this one prints it in full, attribute path included,
  because the reader is a developer with a keyboard. Same exception, two
  audiences, and the contrast is documented in both files.
  **A credential fault surfaces before the greeting**, since
  `start_call` reads the clinic row on the way in: `NoRegionError`,
  `NoCredentialsError` and an unseeded table all exit 1 with the cause
  named rather than hanging — worth stating because the *voice* stack's
  known failure mode (Open Questions) is a silent hang on exactly this.
  **The model is chosen here and only here.** `--model`, defaulting to
  `$CLINICPILOT_TEXT_MODEL`, threaded straight into `start_call` and so
  into all three agents. That is the interface layer's decision to make,
  not an agent definition's. It does **not** settle which model — see
  the open question, now narrowed to a value.
  **The greeting question got its experiment, not its answer.** The CLI
  opens with a stage direction (`OPENING_TURN`) rather than a greeting
  of our own, so the greeting stays the *model's* and the prompt's
  instruction is what gets tested; `--no-greeting` runs the other arm.
  Verified: `pytest` from `backend/` — **544 passed** (511 before, 33
  new), the pre-existing 511 unchanged. Offline throughout: a `FakeAgent`
  drives the loop's own behaviour, and the last test runs the real
  Orchestrator with the Scheduling suite's `ScriptedModel` against fake
  tables, so a line typed at the prompt is proved to reach
  `backend/tools/` and come back printed. Also eyeballed as a transcript:
  greeting, a blank line ignored, an availability question routed and
  answered, a booking that really wrote one row, and `exit` hanging up.
  And run for real against an unconfigured shell, which is what produced
  `!! could not open a call for 'clinic-dental': NoRegionError: You must
  specify a region.` and exit code 1.
  **Not verified, and still cannot be**: anything against a real model.
  That needs Next Up #5 (seeded clinics) plus credentials, and it is the
  only thing that will judge the three system prompts.

- **`backend/agents/voice.py`: Nova Sonic + `BidiAgent`** (Next Up #1,
  first half). The Orchestrator built as a bidirectional speech agent
  instead of a text one, so the speech-to-speech model *is* the front
  desk rather than transcription bolted in front of one. One module, a
  28-test suite, and one dependency change.
  **Split from Next Up #1**, which bundled wiring the voice agent with
  driving it — the same split as `orchestrator.py`/`cli.py` before it
  (`ai-workflow-rules.md` → When to Split Work). The build is verifiable
  now, offline, against a scripted speech model; the microphone
  interface needs PyAudio and a real Bedrock connection and can only be
  judged by listening to it. Bundling them would have made neither
  checkable.
  **It holds no routing rule of its own.** `voice_system_prompt` is
  `ORCHESTRATOR_SYSTEM_PROMPT` formatted with the same
  `session.describe()`, plus `VOICE_PROMPT_SUFFIX`; the tools are
  `orchestrator_tools` unchanged. A test asserts the prompt *begins*
  with the Orchestrator's own text character for character, because a
  paraphrase here would be a second copy of the routing rules free to
  drift, visible only from the typed interface.
  **`VOICE_PROMPT_SUFFIX` says only what a microphone makes true**: read
  a heard name and phone number back before passing them on, say dates
  and times as a person says them, ask again rather than filling in
  something half-heard, and stop when the patient talks over you. The
  read-back is not new policy — `orchestrator.py` already forbids
  inventing a phone number and requires both before booking; speech
  recognition is where those two arrive wrong, so this is the existing
  rule enforced at the point it breaks. A test pins that the suffix
  carries no price, time or policy of its own.
  **The voice model and the text model are two arguments, not one.**
  `build_voice_agent(session, *, voice_model, text_model)`: Nova Sonic
  runs the conversation, and the two sub-agents stay ordinary
  request-response `Agent`s underneath. Threading the Sonic model down
  into `orchestrator_tools` would hand a speech connection to an agent
  that wants an HTTP one — mutation-checked, and it fails three tests.
  **The sub-agent tools needed no change to work here.** They are
  synchronous `@tool` functions, each running a whole text agent, and
  Strands runs a non-async tool in a worker thread
  (`strands/tools/decorator.py`), so the loop carrying the patient's
  audio keeps turning while a booking is made. Nothing became `async`
  for the voice layer, which is why `voice.py` imports the sub-agents
  rather than mirroring them.
  **`OPENING_TURN` moved to `orchestrator.py`.** It was `cli.py`'s; both
  interfaces now import it, because a `BidiAgent` is as silent as an
  `Agent` until something is sent to it and the greeting experiment must
  be one string, not two that drift. `greet(agent)` is the one line that
  sends it. `cli.py` is otherwise untouched.
  **Nova Sonic is imported at call time, not at module import.**
  `BidiNovaSonicModel` needs `aws-sdk-bedrock-runtime` and the smithy
  stack; `BidiAgent` needs neither. Importing it inside
  `build_nova_sonic_model` keeps the module importable and testable
  against any `BidiModel`, and keeps an unrelated ImportError out of the
  path of a caller who supplied their own model.
  **Configuration, not decisions**: `$CLINICPILOT_VOICE_MODEL`,
  `$CLINICPILOT_VOICE_REGION` (defaulting to `us-east-1`, the region
  `architecture.md` confirmed, rather than to the ambient AWS profile —
  which could be a region Nova Sonic is not in) and
  `$CLINICPILOT_VOICE_ID`. Each is left out entirely when unset so the
  library's own default stands; a blank or whitespace value counts as
  unset, since that is how a shell profile exports nothing.
  **Nothing was added for hanging up.** The sample wires
  `stop_conversation`; that tool is deprecated and its own docstring
  says it is not for "goodbye". How a voice call *ends* is not specified
  in `project-overview.md`, so it is an open question below rather than
  a third tool invented onto the front desk.
  **Dependency changed**: `strands-agents>=1.54` →
  `strands-agents[bidi]>=1.54` in `backend/requirements.txt`.
  Verified: `pytest` from `backend/` — **572 passed** (544 before, 28
  new), the pre-existing 544 unchanged. Offline throughout: a
  `ScriptedBidiModel` implementing the `BidiModel` protocol stands where
  Nova Sonic will, so the real `BidiAgent`, its event loop and the real
  tool executor all run and only the speech connection is replaced. Its
  script advances on every *input* — a patient turn and a returning tool
  result each release the next response — which is Nova Sonic's own
  sequencing, so a script that no longer fits is a wiring change. Whole
  spoken calls are driven end to end with two scripted models at once, a
  speech one above and a text one below: a booking that reaches the
  appointments table, an availability question whose sub-agent sentence
  comes back as the tool result rather than a JSON payload for a speech
  model to read out, and assertions that the speech model was shown the
  two assistants and nothing else at the moment the connection opened.
  Every fake and fixture is imported from the suite that owns it. Two
  guards were mutation-checked: dropping the `text_model` threading
  fails three tests, and `build_nova_sonic_model` was exercised for
  real (it constructs without credentials, resolving model id, region
  and voice from arguments and from the environment).
  **Not verified, and cannot be yet**: audio. Nothing has opened a
  Bedrock bidirectional stream, nobody has heard the agent speak, and
  the greeting question's deciding fact — what a real session sounds
  like in its first second — needs the microphone interface (now built,
  below) pointed at credentials and a seeded clinic (Next Up #5).

- **`backend/agents/mic.py`: the local microphone interface** (Next Up
  #1). The voice counterpart of `cli.py` and the second half of the old
  item 1: `start_voice_call` builds the agent, and this drives it —
  `BidiAgent.run` with `BidiAudioIO`'s microphone and speakers, plus a
  monitor that prints what went past and times the silences. One module,
  a 33-test suite, and one dev dependency.
  **It holds no clinic logic, no prompt text and no tool call**, exactly
  as `cli.py` holds none: it builds, pumps, prints and times. A rule
  written here would be a rule the deployed WebSocket entrypoint (#1)
  does not get.
  **The greeting is sent from an IO channel, because `run` gives no
  other hook.** `BidiAgent.run` owns the connection — it starts the
  agent, then starts each channel, then pumps — so `_Greeting.start` is
  the only point between "the connection is open" and "the patient is
  being listened to". The channel blocks forever afterwards, since `run`
  reads every input in a loop and one that yielded twice would talk over
  the patient's first sentence. What it sends is `voice.greet`, the same
  stage direction the keyboard sends; `--no-greeting` runs the other arm.
  **It measures the thing the greeting question is actually about.** A
  `Silence` timer is marked when the greeting is sent and again at every
  final *patient* transcript, and read at the first audio frame of the
  answer — so each turn prints `greeting: first audio after 1.4s` or
  `reply: first audio after 0.9s`. One mark at a time, cleared on
  reading, so the second audio frame of an answer measures nothing.
  Assistant calls are timed separately (`<- scheduling_assistant success
  in 3.1s`), because "was that the speech model or was that a booking?"
  is the first question anyone asks about a pause.
  **The monitor prints what was *heard*.** Final transcripts on both
  sides (`you>` / `clinic>`), which assistant a call was routed to, and
  connection start/restart/close/interruption/error — a developer with a
  headset can hear the call but cannot see that the model wrote the
  phone number down wrong. Interim transcripts, assistant answers and
  token usage are `--verbose` only. Nothing it prints is sent to the
  model: it is an output channel beside the speakers, not instead of
  them.
  **PyAudio is behind a seam, and in `requirements-dev.txt`.**
  `build_audio_io` is the only thing that imports `BidiAudioIO`, and it
  does so at call time; `run_call` takes an `AudioChannels` protocol, so
  a whole call is drivable with no sound card and no PortAudio. That is
  what the test suite does. The dependency is a *dev* one because the
  deployed path takes audio from a browser over a WebSocket and never
  opens a device — a missing one is reported with the install command
  rather than raised as a traceback.
  **`TEXT_MODEL_ENV` moved to `orchestrator.py`**, for the same reason
  `OPENING_TURN` did in the previous unit: two interfaces now choose the
  sub-agents' text model and one env-var name spelled twice is how they
  drift. `cli.py` keeps `MODEL_ENV` as the alias it already exported.
  **Nothing was invented about hanging up.** Ctrl-C, and nothing else —
  a patient saying "goodbye" is an ordinary turn here, as it is over the
  keyboard. The open question below is unchanged and still matters
  before #1.
  **Dependency added**: `strands-agents[bidi-pyaudio]>=1.54` in
  `backend/requirements-dev.txt`, with a comment on why it is not in
  `requirements.txt`.
  Verified: `pytest` from `backend/` — **605 passed** (572 before, 33
  new), the pre-existing 572 unchanged. Whole calls are driven through
  the real `BidiAgent.run` — real task group, real channel start/stop,
  real tool executor — against a `HangingUpBidiModel` (the suite's
  `ScriptedBidiModel`, plus a connection close when its script runs out,
  which is what lets a test end without cancelling a task group
  mid-flight) and a `FakeAudioIO` standing where the sound card will.
  Pinned: the greeting is sent exactly once and only with `greeting=True`,
  what the microphone says reaches the model, both devices are started
  and stopped with the call, and the module imports without PyAudio
  present. `python -m agents.mic --help` and the no-audio path were both
  run for real.
  **Not verified, and still cannot be**: audio. No Bedrock bidirectional
  stream has been opened, nobody has heard the agent speak, and every
  number this module was built to print is still unmeasured. That needs
  credentials and a seeded clinic (#5) — at which point the greeting
  question, the voice choice and the text-model value are all settled by
  listening rather than by argument.

- **`backend/agents/agentcore_app.py`: the deployed voice entrypoint's
  code** (Next Up #1, first half). The third interface over `voice.py`,
  after `cli.py` and `mic.py`, and the one a patient's own browser will
  eventually reach. One module, a 9-test suite.
  **Split from the old "deploy to AgentCore Runtime" item**, the same
  way `voice.py`/`mic.py` split before it
  (`ai-workflow-rules.md` -> When to Split Work: Python logic and its
  CDK deployment are separate steps). This unit is the half that is
  code — a FastAPI app shaped exactly like the vendored sample's
  `agent/strands_agent.py`: `/ping` for AgentCore's health check, `/ws`
  calling `BidiAgent.run` with `websocket.receive_json`/`send_json` as
  its IO channels. Provisioning the AgentCore Runtime resources in
  `agent_stack.py`, a Dockerfile, and hearing a real call all remain,
  now the other half of #1.
  **The clinic arrives on the connection, never in the conversation.**
  `clinic_id` is read from the `/ws` query string
  (`/ws?clinic_id=clinic-dental`) before `websocket.accept()` is ever
  called — not invented: AgentCore's own presigned URL already puts the
  session id in a query parameter (`websocket-presigned.ts`), so this
  rides the mechanism already proven to survive AgentCore's proxy rather
  than adding a second one. A call that cannot work — no clinic id, an
  unknown clinic, a config `ClinicSession.start` cannot resolve — is
  refused with `WebSocket.close()` **before** `accept()`, so nothing is
  ever half-opened for a call that was never going to happen.
  **Only a failure's stable `code` crosses the socket; the message never
  does.** The far end is an anonymous browser tab, not a developer with
  a terminal — the same distinction `results.py` draws for
  `ConfigurationError`, applied here to the whole call. Mutation-checked:
  swapping `error.code` for `error.message` in the close reason fails
  three tests.
  **Nothing here calls `agent.stop()`.** `BidiAgent.run`'s own `finally`
  already stops every input, output and the agent itself — the vendored
  sample calls it again anyway; this module trusts the same cleanup
  `mic.py` already trusts instead of repeating it. The handler's own
  `finally` closes the WebSocket unconditionally and swallows whatever
  that raises, logged at `debug` — a real dead transport can fail this
  in ways no in-process test can produce, and none of them should crash
  the connection's task over a step with nothing left to do.
  **The greeting channel moved out of `mic.py` and into `voice.py`,
  public and renamed `Greeting`.** It was `_Greeting`, private to the
  microphone interface; this entrypoint needs the same one-shot
  "speak-first-then-block" channel (`BidiAgent.run` gives no other hook
  between "connection open" and "patient being listened to"), and a
  second copy would be the greeting experiment split across two files
  that could drift. `mic.py`'s own silence-timing stayed behind, threaded
  through as an optional `on_start` callback `Greeting` calls before
  sending — this entrypoint passes none.
  **No PyAudio anywhere in this path.** Unlike the vendored sample's
  `Dockerfile`, which installs PortAudio "even though we don't directly
  use mic/speakers", this module never imports `BidiAudioIO`: a browser
  sends and receives the same JSON audio *events* `mic.py`'s fake
  channels already use in tests, never raw PCM through a sound card.
  **Dependency added**: `fastapi` and `uvicorn[standard]` in
  `backend/requirements.txt` — this module's web framework. Left in the
  shared file rather than split out for the Lambda handlers, the same
  call already made for `strands-agents[bidi]`.
  Verified: `pytest` from `backend/` — **614 passed** (605 before, 9
  new), the pre-existing 605 unchanged except for the `Greeting` move
  (all `mic.py` tests still pass through it). Offline throughout, via
  FastAPI's own ASGI test client (`fastapi.testclient.TestClient`) rather
  than a real socket: `HangingUpBidiModel`, imported from `test_mic.py`
  rather than restated, stands where Nova Sonic will. Whole calls are
  driven through the real app and the real `BidiAgent` loop — a
  transcript event is asserted to serialise to exactly the
  `{"type": "bidi_transcript_stream", ...}` shape
  `websocket-presigned.ts` already parses, a client-sent dict is proved
  to reach the model as the greeting did, connecting to the cosmetic
  clinic is proved to build the cosmetic clinic's prompt (not assumed
  from the code path), and a browser disconnecting mid-call — the
  server still blocked on `receive_json` — is proved not to escape the
  handler as an unhandled exception. Two guards were mutation-checked
  (the close-reason leak above, and that `accept()` cannot move ahead of
  clinic validation, which fails seven of the nine tests). A manual
  thread-pool timeout wraps every live-call test, since `TestClient`'s
  WebSocket support has none of its own — the same role
  `asyncio.wait_for` plays in every other suite that drives a live call.
  **Not verified, and cannot be yet, in this environment**: the actual
  deploy. No AWS credentials are usable here — see Session Notes — so
  the Dockerfile, the CDK wiring, the container build and a real Bedrock
  connection all remain, along with everything that needed a real call
  before this point.

- **The Knowledge Base infrastructure: KB source bucket + one Bedrock
  Knowledge Base per demo clinic** (old Next Up #2, infra half). CDK
  only — `ai-workflow-rules.md` -> When to Split Work keeps this
  separate from the FAQ tool/sub-agent that will read it, the same split
  already applied to #1 (`agentcore_app.py` vs. its deploy). `data_stack.py`
  gained `kb_bucket` and `kb_source_prefix(clinic_id)`
  (`kb/{clinic_id}/`); `agent_stack.py`, empty until now, gained real
  resources.
  **A separate Knowledge Base per clinic, not one shared Knowledge Base
  filtered by `clinic_id`.** `architecture.md` -> Stack previously read
  "filtered/scoped by `clinic_id`", which this unit resolved toward the
  stronger reading already implied by the Storage Model section's "the
  *per-clinic* Bedrock Knowledge Base": one Knowledge Base id per
  clinic, so `architecture.md` -> Invariants #1 holds because a
  retrieval call is only ever given one clinic's Knowledge Base id,
  never because a filter was applied correctly. `config.py` gained
  `DEMO_CLINIC_IDS` (`clinic-dental`, `clinic-cosmetic`) as the one
  place this fixed pair is spelled — correct for this build rather than
  a shortcut, since `project-overview.md` -> Out of Scope rules out
  self-serve onboarding, and `agent_stack.py` provisions a fixed
  resource per id rather than reading a dynamic clinic list.
  **Vector storage is Amazon S3 Vectors, not OpenSearch Serverless.**
  `architecture.md` -> Stack already called the Knowledge Base
  "S3-backed"; this unit made that literal — one `CfnVectorBucket` and
  one `CfnIndex` per clinic (1024 dimensions, cosine), rather than an
  OpenSearch Serverless collection, which would be a cluster to size and
  keep warm for two small FAQ corpora with no other use in this stack.
  Embeddings are Titan Text Embeddings V2 at its default width — an
  AWS-native model needing no separate access request, picked as an
  implementation default the way `TableV2` was for the tables, not
  escalated as a product decision.
  **The ingestion role is scoped per clinic, and the Knowledge Base
  waits for its policy.** Each clinic gets its own IAM role and inline
  `iam.Policy`, granted `bedrock:InvokeModel` on the embedding model
  only, `s3:GetObject`/`ListBucket` on that clinic's own
  `kb/{clinic_id}/` prefix only (not the whole bucket), and the
  `s3vectors:*` actions needed on that clinic's own index ARN only —
  `code-standards.md` -> AWS CDK's "no `*` resource/action grants," read
  per clinic since nothing requires one role to reach two clinics'
  documents. `CfnKnowledgeBase.add_dependency(ingestion_policy)` is
  explicit rather than assumed, since CDK's automatic dependency
  tracking follows attribute references (the role ARN) but not the fact
  that a `.attach_inline_policy()` call happened — without it, a real
  deploy could create the Knowledge Base before its role can read
  anything.
  Verified: `cdk synth` exits 0 with all five stacks still listed; the
  Agent template carries both clinics' `AWS::S3Vectors::VectorBucket`,
  two `AWS::S3Vectors::Index`, two `AWS::Bedrock::KnowledgeBase` (type
  `S3_VECTORS`, dimension 1024, cosine), two `AWS::Bedrock::DataSource`
  (each `inclusion_prefixes` scoped to one clinic), and each
  `KnowledgeBase`'s `DependsOn` naming its own `IngestionPolicy` by
  inspecting the synthesised JSON directly rather than assuming CDK's
  reference wiring produced it. A `CLINICPILOT_ENV=prod` synth confirmed
  the bucket's environment branch (retain + versioned, no
  auto-delete-objects custom resource) and its artifacts were removed
  after. `cdk deploy` remains untried — see Next Up #1's Session Note on
  this environment's credentials.
  **Not verified, and cannot be yet**: whether Amazon S3 Vectors is
  available in `us-east-1` for real, and whether `retrieve` calls
  against it actually return relevant FAQ passages — both need a real
  deploy and real documents, which is what the FAQ tool (Next Up #2)
  and a seeded clinic (#5) will exercise.

- **`query_faq` in `backend/tools/faq.py`** (Next Up #2, tool half). The
  fifth tool module, the last one Next Up #2 needs before the sub-agent,
  and the only module in `backend/tools/` that reads something other than
  DynamoDB. One module, a 19-test suite.
  **Split from the old bundled #2** (tool, sub-agent, and orchestrator
  wiring together): the same reasoning `ai-workflow-rules.md` -> When to
  Split Work already applied to `scheduling_agent.py` and
  `escalation_agent.py` — a tool is independently verifiable the moment
  the resource under it exists, a sub-agent wrapping it and the
  Orchestrator prompt edit that routes to it are one wiring change and
  land together next.
  **Resolved the one open question blocking this unit**: `retrieve`, not
  `retrieve_and_generate` — see Open Questions for the reasoning. What
  that decided in code: `query_faq` returns `{"question", "passages":
  [{"text": str}, ...], "found": bool}`, never a composed sentence, so
  phrasing the answer stays the sub-agent's model's job, exactly as
  `check_availability` returns slots rather than a sentence about them.
  **No match is a normal answer, not a failure.** An empty
  `retrievalResults` comes back as `found: False` with an empty
  `passages` list, never `NotFoundError` — the same choice
  `check_availability` already made for a fully-booked day, because "I
  don't know" is an answer the sub-agent's model has to hear and act on
  (say so plainly, or escalate), not an exception unwound past it.
  **The Knowledge Base id is resolved per clinic, not read from
  `Clinics`.** `agent_stack.py`'s own docstring called this out when it
  landed: each clinic's Knowledge Base id is read from one environment
  variable, `knowledge_base_id_env_var(clinic_id)` (e.g.
  `CLINICPILOT_KB_ID_CLINIC_DENTAL`) — the same role `dynamo.table_name`
  plays for the four tables, except derived from the `clinic_id` itself
  rather than being one of a fixed handful, since a Knowledge Base (unlike
  a table) is not shared across tenants. Unlike a table name, there is no
  naming scheme to derive a real id from before `agent_stack.py` deploys
  one, so an unset variable is a `ConfigurationError`, not a fallback.
  **`max_results` is a bounded model choice, not a free integer** — the
  same `require_bounded_int` shape `check_availability`'s `days` uses,
  capped at `MAX_MAX_RESULTS` (10) so a model that guessed a large number
  cannot turn one FAQ question into an oversized retrieval call.
  Verified: `pytest` from `backend/` — **633 passed** (614 before, 19
  new), the pre-existing 614 unchanged; nothing outside
  `backend/tools/faq.py`, its test, and `tools/__init__.py`'s module list
  was touched. Offline throughout: a `FakeBedrockAgentRuntimeClient`
  returns Bedrock's own `retrieve` response shape (`retrievalResults[].
  content.text`), so the module is proved to read the real field path
  rather than a simplified stand-in for it. Covers: each clinic resolving
  its own configured id (never another clinic's), an unset or blank
  variable failing as `ConfigurationError` naming the variable, passages
  returned closest-match-first, a `retrievalResults` entry with no
  readable text dropped rather than surfaced as an empty passage,
  `max_results` forwarded to `vectorSearchConfiguration.numberOfResults`
  and defaulting/bounding correctly, and `clinic_id` validated before
  `question` when both are bad.
  **Not verified, and cannot be yet**: against a real Knowledge Base.
  Every clinic's id is env-var-supplied and every response in the suite
  is synthetic; whether a real `retrieve` call against the seeded FAQ
  documents returns something a patient would recognise as an answer
  needs a real deploy (#1) and real documents (#5).

- **`faq_agent.py` and its wiring into the Orchestrator** (Next Up #2,
  agent half — the last piece of the old #2, and the last sub-agent the
  agent tree needed). One module, a 31-test suite, plus edits to
  `orchestrator.py` and `agents/__init__.py`.
  **Same four-part shape as the other two sub-agents**: `faq_tools`,
  `build_faq_agent`, `faq_agent_tool`, and `FAQ_SYSTEM_PROMPT` formatted
  with `session.describe()`. It holds one tool, `query_faq`, for the
  reason `escalation_agent.py` holds one tool and not four: the
  patient-facing surface is exactly what a patient-facing agent needs
  and nothing a staff-only reader would.
  **It composes the answer; `query_faq` deliberately does not.**
  `tools/faq.py`'s own docstring resolved `retrieve` over
  `retrieve_and_generate` specifically so that phrasing stays a
  sub-agent model's job — this agent is that job, over the passages
  `query_faq` returns. The prompt tells it, in as many words, to answer
  only from what it retrieved and never from its own knowledge of
  dentistry or cosmetics — the same shape as `scheduling_agent`'s "never
  reason about opening hours yourself," because a fluent model asked a
  price question will invent a plausible one if allowed to, and a
  plausible wrong price is worse than "I don't know."
  **It does not decide to escalate.** `query_faq` returns `found: False`
  as an ordinary answer, not a failure, and whether that becomes a card
  in the staff queue is the Orchestrator's call
  (`architecture.md` -> Invariants #2 and #6) — the same boundary
  `escalation_agent.py` draws around raising an escalation at all. This
  agent holds no `create_escalation` tool; its prompt says plainly that
  it does not have the answer and stops, and the test suite pins that
  the tool is absent by name, not merely uncalled.
  **The Orchestrator's routing changed, not just its tool list.**
  `orchestrator_tools` now returns three wrappers —
  `scheduling_assistant`, `faq_assistant`, `escalation_assistant` — and
  `ORCHESTRATOR_SYSTEM_PROMPT` moved prices, treatments, preparation and
  policy questions out of the escalation bullet and into a new one that
  sends them to `faq_assistant` first; the escalation bullet keeps
  everything that was never a published fact (billing, insurance, a
  refund, a complaint, clinical judgement) and gained the FAQ assistant's
  own "could not answer it" outcome as a fourth reason to raise a card.
  A price or preparation question no longer becomes a staff callback by
  default — the gap `query_faq`'s own Completed entry named as "correct,
  and lossy" is closed for anything the clinic has actually published.
  Verified: `pytest` from `backend/` — **666 passed** (633 before, 33
  new: 31 in `test_faq_agent.py`, 2 new whole-call tests in
  `test_orchestrator.py`), the pre-existing 633 unchanged except one
  assertion in `test_agents_cli.py` that named the Orchestrator's tool
  list literally and needed `faq_assistant` added to it — found by the
  run, not missed by it. `test_faq_agent.py` follows
  `test_escalation_agent.py`'s shape throughout: the surface is exactly
  one tool, the wrapper is checked against `tools/faq.py` called
  directly, a missing Knowledge Base id reaches the model as the shared
  internal-failure message (not as a "no match" answer), and Agent-as-
  Tool is driven end to end against the fake Bedrock client
  `test_faq.py` already owns. `test_orchestrator.py` gained two whole-
  call tests: a price question that reaches `faq_assistant` and answers
  without touching the escalation queue, and a miss that the front desk
  itself sends on to `escalation_assistant` — proving the hand-off is a
  routing decision the Orchestrator makes, not something either
  sub-agent decides on its own.
  **Not verified, and cannot be yet**: anything against a real model or a
  real Knowledge Base. Every script in the new suite is synthetic, and
  whether a real patient's phrasing actually retrieves the passage that
  answers it needs a deployed KB, real seeded documents, and a live
  session (Next Up #1 and #4) — the same gap `query_faq`'s own entry
  already named.

- **`agent_stack.py`'s remaining CDK resources, plus `backend/Dockerfile`**
  (Next Up #1, second half — the code-and-infra half of it this
  environment could actually do). `agentcore_app.py`'s own Completed
  entry split "deploy to AgentCore Runtime" into a code half (done) and
  an infra half; this unit is that infra half, minus the one piece no
  offline environment can do at all (the real `cdk deploy`).
  **The container image is an ordinary CDK asset, not the vendored
  sample's CodeBuild pipeline.** `vendor/.../cdk/lib/runtime-stack.ts`
  uploads agent source to S3 and triggers a CodeBuild project to build
  and push the image, with a custom-resource Lambda to wait for it — a
  real workaround, but for a problem this build does not have: it exists
  so the machine running `cdk deploy` never needs Docker itself. This
  stack uses `AgentRuntimeArtifact.from_asset("backend/", file="Dockerfile")`
  instead, CDK's standard container-asset path: the image is
  fingerprinted from the source tree at `cdk synth` time (no Docker, no
  credentials needed for that) and only actually built and pushed during
  `cdk deploy`'s own asset-publishing step. Simpler, and
  `code-standards.md` -> General's "fix root causes, do not layer
  workarounds" is the reason it was not copied anyway once it turned out
  not to be needed.
  **`backend/Dockerfile` drops the PyAudio/PortAudio layer**, exactly as
  `progress-tracker.md` already flagged when `agentcore_app.py` landed:
  this container never opens a sound device, and `requirements.txt`
  installs `strands-agents[bidi]`, not `[bidi-pyaudio]`. ARM64 platform
  and port 8080 are kept from the vendored sample's Dockerfile —
  AgentCore Runtime requires both, and nothing here is free to change
  them. `.dockerignore` keeps `infra/`, `tests/`, and the dev-only
  `requirements-dev.txt` out of the build context and, so, out of the
  asset hash.
  **The execution role is the L2 `Runtime` construct's own auto-created
  role, not a hand-built one** — unlike `_build_clinic_knowledge_base`'s
  ingestion role, which has no construct to auto-create it. This stack
  only *adds* the grants that role does not get for free: `GetItem` on
  `Clinics`; `Query` + `PutItem` + `UpdateItem` on `Patients` and
  `Appointments` (their GSIs included); `PutItem`-only on `Escalations`,
  because the only tool this runtime's agents expose is
  `create_escalation` — `list_open_escalations`, `get_escalation`, and
  `resolve_escalation` are staff-dashboard reads that belong to a Lambda
  role in `api_stack.py`, not to this one. Every action list was checked
  against the actual `boto3` calls in `tools/scheduling.py`,
  `tools/patients.py`, `tools/booking.py`, `tools/appointments.py`, and
  `tools/escalations.py` (grep'd, not assumed), and `bedrock:Retrieve` is
  granted per clinic, scoped to that clinic's own Knowledge Base ARN and
  no other's (`architecture.md` -> Invariants #1).
  **Bedrock model invocation is scoped to the `foundation-model` resource
  type, not to one model id.** Which text model the sub-agents reason
  with, and Nova Sonic's own model id, are both still open questions
  below, threaded through a `model` argument this stack has no way to
  read — pinning an ARN now would silently break the moment either
  question is answered with a different id. Still not the blanket grant
  `code-standards.md` -> AWS CDK forbids: scoped to one resource type, in
  this account and region, and the trade-off is written into this
  module's own docstring rather than left implicit.
  **The runtime is public and IAM-authorized, matching
  `architecture.md` -> Auth and Access Model as already written**: network
  mode `PUBLIC` (an AgentCore Runtime is not placed inside a VPC for this
  build) and `RuntimeAuthorizerConfiguration.using_iam()` — SigV4, which
  is exactly what a Cognito identity pool's guest credentials produce.
  The identity pool and its guest IAM role (scoped to
  `grant_invoke_runtime` on this resource and nothing else) are **not**
  part of this unit: they belong beside Cognito in
  `api_stack.py`/`frontend_stack.py`, which do not exist yet.
  **`KB_ID_ENV_PREFIX` is duplicated from `tools/faq.py`, not imported** —
  the same reason `data_stack.py` duplicates `schema.py`'s key and index
  names rather than importing them: this stack needs `aws-cdk-lib`, which
  `backend/tools/` must never depend on, and the two run in separate
  virtual environments. A new guard,
  `test_kb_id_env_prefix_matches_the_agent_stack` in
  `test_schema_matches_infra.py`, fails if the two ever disagree — the
  same drift-guard shape that file already used for the data stack.
  **AgentCore Runtime names may not contain hyphens** (letters, digits,
  underscores only — the vendored sample's own runtime is
  `nova_sonic_bidi_agent` for the same reason), unlike every other
  resource name `ProjectConfig.resource_name` builds. `_runtime_name`
  is the one place that gets special-cased rather than changing the
  naming scheme everything else uses.
  Verified: `pytest` from `backend/` — **667 passed** (666 before, 1
  new), the pre-existing 666 unchanged. `cdk synth` exits 0 with all five
  templates still written, and the synthesised `ClinicPilot-Dev-Agent`
  template was read back and checked directly (not assumed from the
  code): one `AWS::BedrockAgentCore::Runtime` resource, correct
  `AgentRuntimeName`/`ProtocolConfiguration: HTTP`/
  `NetworkConfiguration: PUBLIC`, IAM auth (an absent
  `AuthorizerConfiguration`, which is exactly what `using_iam()` produces
  at the CloudFormation layer), both clinics' Knowledge Base ids wired as
  environment variables via `Fn::GetAtt` tokens (not deploy-time
  constants — they do not exist until this stack deploys), a `RoleArn`
  pointing at the auto-created execution role, and a container URI built
  from CDK's own bootstrap asset ECR repository with an unresolved-token
  info note ("validated at deployment time") rather than a build attempt
  — confirming Docker is genuinely not invoked at `synth` time. The
  execution role's own policy was read back too: every added statement
  present with the exact scoped resource expected (per-clinic KB ARNs,
  `foundation-model/*`, each table's own ARN plus `/index/*` where
  `Query` is granted, `Escalations` with `PutItem` alone), alongside the
  framework's own baseline grants (CloudWatch Logs, X-Ray, the workload-
  identity token calls, and pulling the image from the bootstrap ECR
  repo) which this unit did not have to add and does not touch. A second
  synth with `CLINICPILOT_ENV=prod` confirmed the naming branch
  (`clinicpilot_prod_agent_runtime`) and its artifacts were removed
  after, matching the verification style every other environment-branched
  resource in this stack already got.
  **Not verified, and cannot be yet, in this environment**: the actual
  `cdk deploy` (needs Docker, to build and push the image, and AWS
  credentials, to create the stack — neither available here, Session
  Notes), and everything downstream of it: a real container running,
  AgentCore actually invoking it, and a real voice session over the
  deployed `/ws`.

- **`tools/automation.py`: the background job's whole decision, and
  `lambda/background_scan.py`, its thin entrypoint** (Next Up #2, tool +
  Lambda-code half). `ai-workflow-rules.md` -> When to Split Work: agent/
  tool logic and its CDK deployment are separate steps, the same split
  `agentcore_app.py`/`agent_stack.py` already went through — this unit is
  the Python logic; wiring an EventBridge Scheduler + a deployed Lambda
  resource around it is the new Next Up #2 below.
  **The no-show/reschedule heuristic was the blocker named in the old
  Next Up #2**, and it needed answers no context file gave, so it was put
  to the user rather than guessed (`ai-workflow-rules.md` -> Handling
  Missing Requirements): (a) the signal is a patient's own count of past
  `no_show` appointments at this clinic — the only signal available at
  all, since reminders are one-way SES email and there is no confirmation
  channel a "did they mean to come?" read could be taken from; (b) a
  flagged appointment is **escalated to staff outright**, not
  auto-rescheduled — `project-overview.md`'s middle option
  ("attempt an automatic reschedule") is not implemented, so
  `architecture.md` -> Invariants #6 holds by construction: the job's only
  autonomous action is a rule this layer defines, and "guess a new time
  nobody asked for" is not one; (c) one reminder, sent once, for anything
  starting within 24 hours of the scan running.
  **The decision per appointment is binary and mutually exclusive**:
  escalate, or remind — never both, and `_process_appointment` returns
  before reaching the reminder path once it escalates. It reads through
  `tools.escalations.create_escalation` and (a new addition)
  `tools.patients.get_patient`, never its own query or write, so the live
  agent path and this job share every rule (Invariants #3).
  **`NO_SHOW_RISK_THRESHOLD = 1` is not a product rule and was not asked
  about** — a boundary decision of the same kind as
  `escalations.DEFAULT_ESCALATION_LIMIT`, flagged here rather than buried.
  Reversible: one constant, one reader. Raise it if the demo shows it
  firing too eagerly.
  **Idempotency comes from the appointment's own `reminders` list**, not a
  second table: an appointment that already carries an entry is excluded
  from the scan before any decision is made about it. The module docstring
  notes this is a property of the once-daily/24-hour-window design, not a
  guarantee enforced beyond the reminder branch — worth re-checking if the
  schedule's cadence or window width ever changes, since nothing stops a
  no-show escalation firing twice if an appointment somehow appeared in
  two days' windows.
  **One invocation is one clinic.** `background_scan.handler` reads
  `clinic_id` off the triggering event and does nothing else — a decision
  recorded in both modules' docstrings and in `architecture.md` ->
  System Boundaries, since it fixes the shape the not-yet-built
  EventBridge Scheduler infra must take: one schedule per seeded clinic,
  each with its own `{"clinic_id": ...}` input, never a single schedule
  fanning out across clinics inside one run (Invariants #1).
  **`appointments.py` gained `appointment_history_for_patient`**, the
  no-show count's read: the whole `by-patient` partition, every status,
  every time — `upcoming_appointments_for_patient` is now this narrowed in
  Python to `scheduled`/not-yet-started rather than restating the query,
  which is what let the by-patient index range condition
  (`Key(STARTS_AT).gte(now)`) be dropped in favour of a plain partition
  read; small extra data transferred per patient (these tables are small —
  `architecture.md` -> Storage Model already accepts this trade for
  `list_open_escalations`), and one fewer query shape to keep in sync with
  the no-show reader.
  **`patients.py` gained `get_patient`**, the by-key counterpart to
  `find_patient`: the background job holds a `patient_id` off an
  appointment record and has no phone number to look one up by. Returns
  `None` rather than raising on a stale reference, since what to do about
  a patient record that vanished is the caller's call, not a failure of
  the read itself.
  **`schema.py` gained `ReminderChannel` and `ReminderOutcome`** — the two
  value vocabularies `ReminderEntry`'s own docstring already said would
  land with this job, the only writer of a `reminders` entry.
  **SES sending is real, not stubbed**, behind `_send_reminder_email` —
  `boto3.client("ses").send_email`, with the sender address read from
  `CLINICPILOT_REMINDER_SENDER_EMAIL` (the verified personal Gmail,
  Session Notes) and a `ClientError`/`BotoCoreError` caught and turned into
  `ReminderOutcome.FAILED` rather than raised, since a bounced send is an
  expected outcome for a batch job, not a programming fault. A missing
  sender address is a `ConfigurationError` instead, and deliberately
  **not** special-cased to abort the whole scan up front — it surfaces
  identically for every due appointment via the same per-appointment
  `ToolError` catch that guards a bad row, which is simpler than a second
  code path for what is, in the end, the same fact reported N times
  instead of once.
  **One bad appointment cannot sink the scan.** `run_daily_scan` catches
  `ToolError` per appointment (a service the clinic no longer offers, a
  `patient_id` missing off a corrupt row) and records it as a `"failed"`
  result rather than letting the whole clinic's run die on one row — a
  batch-job property none of the live-call tools needed, since a live call
  is already about one appointment at a time.
  Landed on the way: `lambda/__init__.py`, the first file in
  `backend/lambda/`. **`lambda` is a Python keyword**, so nothing may
  reach this package with an ordinary `import`/`from` statement — only
  `importlib.import_module("lambda.background_scan")` works, which is also
  exactly how the Lambda runtime itself resolves a configured handler
  string, so deployment pays nothing for this; it only affects code (this
  suite, a REPL) that wants to reach the package by name. Documented in
  `architecture.md` -> System Boundaries so it is not rediscovered by the
  next thing that tries a plain import and hits a `SyntaxError`.
  Verified: `pytest` from `backend/` — **688 passed** (667 before, 21
  new), the pre-existing 667 unchanged except one test updated to match
  `appointment_history_for_patient`'s simpler (single-condition) query
  shape rather than the old two-condition one
  (`test_by_patient_query_is_keyed_on_the_clinic_patient_composite`) — a
  query-shape change, not a behaviour change; the same 254+61+... case
  coverage for reschedule/cancel still passes unchanged. The new suite
  drives `run_daily_scan` end to end against the real `by-start-time` and
  `by-patient` queries (the same `FakeAppointmentStore` `test_appointments.py`
  owns, which actually evaluates key conditions and applies
  `UpdateExpression`s rather than only recording them) and a real
  `FakeEscalationsTable`/`FakePatientsTable` — no credentials, no moto, no
  network, and `_send_reminder_email` stubbed rather than hitting SES.
  Covered: escalate-vs-remind on both sides of the threshold, a
  housemate's no-show history staying invisible (by-patient isolation), a
  cross-clinic appointment staying invisible to the wrong clinic's scan,
  the reminder window's edges (too far ahead, already started, already
  reminded, cancelled), a missing email short-circuiting before any SES
  call, a rejected SES send recorded as `failed` rather than raised, one
  bad row not stopping a good one in the same scan, and the sender-env
  helper both unset (`ConfigurationError`) and set-with-whitespace
  (trimmed). `lambda/background_scan.py` itself is driven through
  `importlib.import_module`, asserting it forwards `clinic_id` unchanged
  and that a `ToolError` is logged before it propagates rather than being
  swallowed.
  **Not verified, and cannot be yet**: an actual SES send (needs a
  verified sender identity and credentials this environment does not
  have — Session Notes), and whether `NO_SHOW_RISK_THRESHOLD = 1` reads as
  the right sensitivity against real seeded data, which needs Next Up #4
  (seed) before it can be judged rather than argued.

- **`automation_stack.py`: the EventBridge schedule and the background
  Lambda** (old Next Up #2, now finished). The CDK half of the background
  job — the same "code first, deploy second" split `agentcore_app.py`/
  `agent_stack.py` went through — over `tools/automation.py` and
  `lambda/background_scan.py`, both already done and tested (see above).
  **The Lambda's code asset is `lambda/` and `tools/` only.** A plain
  `lambda_.Code.from_asset(_BACKEND_DIR, exclude=[...])` over a source
  zip, not a Docker asset and not `aws-lambda-python-alpha` bundling:
  `tools/automation.py` reaches only `boto3` (already in the Lambda
  Python runtime) and the standard library, so there is no dependency to
  bundle. `exclude` keeps `agents/`, `infra/`, `tests/`, `.venv/`, and
  `__pycache__` out of the zip, mirroring the restriction `Dockerfile`
  already applies to the AgentCore container's own `COPY agents/
  tools/` — verified by inspecting the staged `cdk.out/asset.*`
  directory directly rather than trusting the exclude list read
  correctly.
  **One `AWS::Scheduler::Schedule` per demo clinic**, each a `rate(1
  day)` expression targeting the same Lambda with its own
  `{"clinic_id": ...}` JSON input (`architecture.md` -> Invariants #1) —
  the plain `aws_scheduler.CfnSchedule` L1 construct, since no L2 alpha
  module is a dependency here and one stack's IAM/target shape is a small
  enough surface not to need one. One `SchedulerExecutionRole`, scoped to
  `lambda:InvokeFunction` on this one function's ARN, is shared by both
  schedules rather than one role each.
  **The execution role's DynamoDB grants are scoped per module, not per
  table wholesale** — checked against the actual calls each one makes:
  `GetItem` only on `Clinics` (`scheduling.get_clinic`) and `Patients`
  (`patients.get_patient`, which reads a `patient_id` already in hand and
  never looks up by phone); `Query` (plus `/index/*`) and `UpdateItem` on
  `Appointments` (`appointment_history_for_patient`'s `by-patient` query,
  `_scheduled_starting_within`'s `by-start-time` query, and
  `_record_reminder`'s write onto the same item); `PutItem` only on
  `Escalations`, since the only escalation path this job takes is
  `create_escalation`. `ses:SendEmail`/`ses:SendRawEmail` are scoped to
  `arn:aws:ses:{region}:{account}:identity/*` — a resource *type*, not
  `*` outright, the same tradeoff `agent_stack.py` already documents for
  `bedrock:InvokeModel` against `foundation-model/*`: the verified sender
  identity is created manually outside CDK (Session Notes), so its exact
  ARN cannot be pinned at synth time, but the grant still stops short of
  every SES action on every resource (`code-standards.md` -> AWS CDK).
  `CLINICPILOT_REMINDER_SENDER_EMAIL` is deliberately left unset on the
  function's environment — no identity is verified yet — rather than
  invented; setting it is now folded into Next Up #3 (seed).
  Verified: `npx aws-cdk@2 synth` exits 0 with all five stacks
  (no Docker, no AWS credentials needed for a source-zip Lambda asset any
  more than for the Docker asset `agent_stack.py` already synthesises
  without them); the Automation template carries exactly one
  `AWS::Lambda::Function`, its role and policy, one scheduler role, and
  two `AWS::Scheduler::Schedule` resources (`DentalDailyScanSchedule`,
  `CosmeticDailyScanSchedule`) each with the right `rate(1 day)`
  expression and per-clinic JSON input; the policy document was read back
  and diffed against the module-by-module grant list above line for
  line; the staged Lambda asset directory was inspected directly and
  contains only `lambda/`, `tools/`, and `requirements.txt` — no
  `agents/`, `infra/`, `tests/`, or `__pycache__`. `pytest` from
  `backend/` — **688 passed**, unchanged (this unit touched no Python
  under `backend/tools/`, `backend/lambda/`, or `backend/agents/`).
  **Not verified, and cannot be yet**: an actual `cdk deploy` (this
  environment has neither Docker nor AWS credentials — Session Notes),
  and therefore whether the deployed schedule really fires and reaches a
  real inbox, which needs Next Up #1 (the environment-blocked deploy) and
  #3 (seed, for a verified SES identity and real appointments to scan).

- **The staff dashboard API's Python half: `list_appointments_for_clinic`
  and `lambda/dashboard_api.py`** (Next Up #2, first of three split
  units — infra and frontend are next, per `ai-workflow-rules.md` ->
  When to Split Work). The first code any staff-facing screen will call.
  **One new tool function, no schema change.** Every existing appointment
  read in `tools/appointments.py` answers "what can this *caller*
  change?" — scoped to one patient, via `find_patient` or a `patient_id`
  already in hand. The dashboard's Appointments list needs the opposite:
  every booking at the clinic, for a person who has no patient identity
  to start from. `project-overview.md` -> Staff (dashboard) fixes the
  scope as "today's appointments", so `list_appointments_for_clinic`
  is a **one clinic-local day** read, not an unbounded one — today by
  default, or an explicit `date` — mirroring `check_availability`'s own
  local-day framing rather than inventing a second one:
  `scheduling.local_midnight` (promoted from private, the same way
  `unavailable_message` was, since this is now its second caller) builds
  the day's UTC window so a DST-transition day is not silently an hour
  short here either, and the query goes straight at `by-start-time`
  without `scheduling._booked_spans`'s status filter — a cancelled or
  no-show appointment is still something staff review, unlike an
  availability check. Capped after the fetch the way
  `list_open_escalations` already is, rather than passed to DynamoDB as
  `Limit` (`DEFAULT_APPOINTMENT_LIMIT` = 50, `MAX_APPOINTMENT_LIMIT` =
  200). The return is a dict (`clinic_id`, `date`, `timezone`,
  `appointments`) rather than a bare list, so a dashboard that opens with
  no `date` can still show which day it is looking at — the same reason
  `check_availability` echoes `date`/`days_checked` rather than only
  returning `slots`. `AppointmentAttrs.PATIENT_NAME` being denormalised
  onto every appointment (an existing decision) means the list needs no
  second read per row to be useful.
  **`dashboard_api.py` holds no logic of its own**, for the reason
  `background_scan.py` holds none of `tools.automation`'s
  (`code-standards.md` -> General): a plain `(httpMethod, resource)` dict
  routes to one of four functions, each forwarding straight into
  `tools/appointments.py` or `tools/escalations.py`. No new tool was
  needed for the three escalation routes — `list_open_escalations`,
  `get_escalation`, `resolve_escalation` already existed, written ahead
  of any caller back when the escalation module landed.
  **`clinic_id` comes from the Cognito token and nowhere else** — see the
  Architecture Decision above and the synced line in `architecture.md` ->
  Auth and Access Model. `_clinic_id_from` reads `custom:clinic_id` off
  `requestContext.authorizer.claims`; no route function's signature
  accepts a `clinic_id` from the request, so there is no parameter a
  compromised or careless frontend could set to reach another clinic's
  data — asserted by a test that plants a different `clinic_id` in the
  query string and checks it never reaches the tool layer.
  **Every response is `{data, error}`**, per `code-standards.md` -> API
  Routes. A `ToolError` keeps its own message — these are already
  written for a human reader, staff rather than a patient, so nothing
  here paraphrases `tools/`'s own words — and is mapped to a status by
  `_STATUS_BY_ERROR` (400/404/409/500). Anything that is not a `ToolError`
  is logged in full and replaced with one fixed message, the same
  contrast `agents/results.py` draws for the voice path: a KeyError with
  an internal attribute path is a CloudWatch fact, not a dashboard one. A
  `Decimal` (every stored duration/count) is encoded through a small
  `json.JSONEncoder` rather than reaching `json.dumps` raw, which is
  exactly the failure Session Notes already records for the *voice* path
  (Strands' fallback to `repr` on a tool result) — the same class of bug,
  caught here before a browser ever sees it.
  **Route paths are fixed now, by this module, not invented later.**
  `GET /appointments`, `GET /escalations`, `GET /escalations/{escalation_id}`,
  `POST /escalations/{escalation_id}/resolve` — `_ROUTES`' keys are the
  literal contract `api_stack.py`'s API Gateway resources must match
  (Next Up #2a).
  Verified: `pytest` from `backend/` — **719 passed** (688 before, 31
  new), the pre-existing 688 unchanged; nothing outside
  `tools/appointments.py`, `tools/scheduling.py` (the `local_midnight`
  rename) and the two new/touched test files was touched.
  `tools/appointments.py`'s new function is driven against the
  same `FakeAppointmentStore` `test_appointments.py` already uses for
  reschedule/cancel — clinic scoping (another clinic's appointment is
  invisible), soonest-first ordering across any status within a day, a
  different calendar day's appointment excluded, the default resolving
  to the clinic's current local date (asserted against a monkeypatched
  "now" the way every other "upcoming" read in this module is), an
  unknown clinic, a malformed date, and the limit's bounds. `dashboard_api.py`
  is tested the same thin way `test_background_scan.py` tests its Lambda
  — every tool-layer call monkeypatched, nothing built against a fake
  table here — covering all four routes' argument forwarding, a missing
  or blank Cognito claim, a smuggled `clinic_id` in the query string
  being ignored, an unknown route (404), a missing path parameter
  reaching the real (unmocked) `get_escalation` and failing as
  `ValidationError`, each `ToolError` subtype's status and verbatim
  message, an unexpected exception never reaching the response as raw
  text, and `Decimal` serialising cleanly.
  **Not verified, and cannot be yet**: anything through a real API
  Gateway or a real Cognito token — that needs Next Up #2a, which fixes
  these route paths and the `custom:clinic_id` attribute into actual AWS
  resources.

- **`api_stack.py`: the Cognito user pool, REST API, and dashboard
  Lambda** (Next Up #2a, the CDK half of the staff dashboard). The same
  "code first, deploy second" split `agent_stack.py`'s AgentCore Runtime
  and `automation_stack.py`'s background scan already went through
  (`ai-workflow-rules.md` -> When to Split Work); `dashboard_api.py`'s
  four routes were already done and tested (see the entry above), so
  this unit only wires them into real resources.
  **The four API Gateway resources are the literal contract
  `dashboard_api._ROUTES` already fixed**, not invented here: `GET
  /appointments`, `GET /escalations`, `GET /escalations/{escalation_id}`,
  `POST /escalations/{escalation_id}/resolve`, each an explicit
  `Resource`/`Method` rather than one `{proxy+}` catch-all
  (`code-standards.md` -> AWS CDK: every route defined in CDK), each
  behind a `CognitoUserPoolsAuthorizer` on the one staff user pool.
  **The `clinic_id` custom attribute is declared, not seeded.** The user
  pool carries a `clinic_id` custom attribute (`CLINIC_ID_ATTRIBUTE`,
  read back by `dashboard_api._clinic_id_from` as `custom:clinic_id` —
  Cognito's own prefix, added once and read once) with self-sign-up and
  password recovery both off, since the only two accounts this pool will
  ever hold are the demo clinics' own. **Creating those two accounts is
  Next Up #3, not this unit** — a decision recorded in Architecture
  Decisions below before this stack was written, because a CDK-managed
  Cognito user needs a password strategy that is not a resource-naming
  decision, and the seed script that already writes sample appointments
  is the natural place for the `admin-create-user` /
  `admin-set-user-password` calls instead.
  **The Lambda is packaged exactly like `automation_stack.py`'s
  background-scan function**: `backend/`'s own `lambda/` and `tools/`
  directories only, running `lambda.dashboard_api.handler` — the same
  reasoning (`boto3` plus the standard library needs no bundling step)
  and the same asset excludes.
  **The execution role is scoped to exactly what `dashboard_api.py`'s
  four routes call**, verified against `tools/appointments.py` and
  `tools/escalations.py` rather than assumed: `Query` on `Appointments`'
  `by-start-time` index for `list_appointments_for_clinic`; `Query` on
  `Escalations`' `by-created-at` index, `GetItem`, and `UpdateItem` for
  `list_open_escalations`/`get_escalation`/`resolve_escalation`. No grant
  onto `Clinics` or `Patients` — this Lambda's own imports never touch
  either table.
  **CORS is wide open** (`default_cors_preflight_options`, all
  origins/methods) because `frontend_stack.py` is still a skeleton with
  no CloudFront domain to narrow it to yet — an engineering default for
  an unbuilt frontend, not a product decision, and one line to tighten
  once Next Up #2b exists.
  `app.py` now threads `data.appointments_table` and
  `data.escalations_table` into `ApiStack` (it previously took no table
  arguments, since it had no resources yet) — `Clinics` and `Patients`
  are deliberately not passed, mirroring the grant list above.
  Verified: `cdk synth` for `ClinicPilot-Dev-Api` alone, and
  `cdk synth --all` for all five stacks, both exit 0 with no code
  changes needed elsewhere; `cdk list` still shows all five stack names.
  The synthesised template carries the user pool with its custom
  attribute, the app client, the four `AWS::ApiGateway::Method` resources
  each with `AuthorizationType: COGNITO_USER_POOLS` and the shared
  authorizer, the Lambda with its handler string and environment
  variables, and the two scoped `AWS::IAM::Policy` statements (no `*`
  resource, per `code-standards.md`). The two pre-existing
  `TableGrantsProps` deprecation warnings in the synth output were
  confirmed present on `ClinicPilot-Dev-Data` alone on the pre-change
  tree (via `git stash`), so they predate this unit and are not
  addressed here — out of scope for a `data_stack.py` change this item
  never touches.
  **Not verified, and cannot be yet**: an actual `cdk deploy`, a real
  Cognito token reaching API Gateway, and a real login — all blocked in
  this environment for the same reason Next Up #1 is (see Session
  Notes), and all still waiting on Next Up #3's seed script for the two
  demo accounts this pool is built to hold.

- **`frontend/src/dashboard/`: the staff dashboard UI** (Next Up #2a).
  The first frontend code in this repo, and the first thing under
  `frontend/` at all — so this unit also scaffolds the Vite + React +
  TypeScript + Tailwind + shadcn/ui project `architecture.md` -> Stack
  names, scoped to exactly what the dashboard needs (`ai-workflow-rules.md`
  -> When to Split Work: backend and frontend are separate steps, and
  `frontend/src/voice/` is not this step — it does not exist yet and
  nothing here builds toward it beyond the shared scaffolding both will
  use).
  **`App.tsx` mounts the dashboard directly, not behind a router.**
  `architecture.md` -> Stack says one SPA serves both surfaces
  eventually, but `frontend/src/voice/` is unbuilt and not in this unit's
  scope, so inventing a router for a second route with nothing behind it
  would be exactly the kind of unspecified behavior `ai-workflow-rules.md`
  -> Handling Missing Requirements says not to guess at. Splitting the
  two by route is `voice/`'s own task when it lands.
  **shadcn/ui components are hand-authored, not CLI-generated** —
  `button`, `card`, `badge`, `input`, `label`, `dialog` in
  `shared/components/ui/`, each following the CLI's own structure
  (`cva` variants, `forwardRef`, Radix primitives where the CLI would use
  one) so they stay swappable for real CLI output later
  (`ai-workflow-rules.md` -> Protected Files already treats this
  directory as CLI-owned). Colors reference the CSS custom properties in
  `index.css` directly (`bg-[var(--bg-surface)]`) rather than shadcn's
  usual `hsl(var(--x))` indirection, since `ui-context.md` already gives
  hex values and converting ten of them to HSL by hand for an effect
  (alpha-channel utilities) this build does not need was not worth the
  transcription risk.
  **One real bug this surfaced**: Tailwind's opacity modifier on an
  arbitrary `var()` reference (`bg-[var(--state-success)]/15`) silently
  emits no CSS rule at all — no build error, just a badge with no
  background. Fixed by precomputing five light "wash" tints as their own
  CSS custom properties (`--bg-state-success-wash`, etc., ~12% of each
  state color over `--bg-surface`) and a separate `--overlay-scrim` for
  the modal backdrop (which has to stay a translucent `rgba()`, unlike
  the flat wash tokens, since it sits over arbitrary page content) —
  documented in `index.css` so the next person reaching for `/NN` on a
  `var()` does not repeat it.
  **Cognito is built lazily**, not at module load
  (`dashboard/lib/auth.ts`): `CognitoUserPool`'s constructor throws on a
  blank id, and no `.env` has real values yet — Next Up #3 (seed) has not
  run and the CDK that precedes it has not deployed (Session Notes). A
  module-level throw would blank-screen the app before the login form
  could explain why; instead `getCurrentUser`/`getIdToken` resolve `null`
  and `signIn` throws a clear "Dashboard is not configured" message the
  login form renders — verified by screenshot (see below), not just
  inferred.
  **No `signUp`/`confirmSignUp`**, unlike the vendored sample's own
  `auth.ts` this was adapted from: `api_stack.py`'s user pool has
  self-sign-up disabled and will only ever hold the two seeded demo
  accounts (`architecture.md` -> Auth and Access Model), so a
  registration flow would be dead code against a pool that refuses it.
  **The "log of autonomous actions"** (`project-overview.md` -> Staff
  Dashboard) is rendered inline per appointment (`AppointmentCard`'s
  expandable section) rather than as a fourth nav page: `ui-context.md`
  -> Layout Patterns names exactly three sidebar items
  (Appointments/Escalations/Settings), and `architecture.md` -> Storage
  Model already derives the log from each appointment's own
  `reschedule_history`/`reminders` — data `list_appointments_for_clinic`
  already returns, so no new route was needed and none was added. Only
  `actor: "agent"` reschedule/cancel entries are shown, mirroring
  `schema.RescheduleActor`'s own reason for existing: the log's whole
  point is showing which moves the agent made unprompted. Settings has no
  behavior defined anywhere in the context files, so its nav entry
  renders a one-line placeholder rather than invented functionality.
  **`clinic_id` is never a frontend parameter.** Every `dashboardApi.ts`
  function takes only what its route needs beyond the Cognito token
  (`date` for `listAppointments`, an id for the two escalation routes) —
  matching `dashboard_api.py`'s own rule that the claim is the only
  source, never a request parameter, so there is nothing here for a
  compromised frontend to override even if it tried.
  Verified: `npm run build` (`tsc -b && vite build`) exits 0. Screenshotted
  end to end via a headless-Chromium harness (Playwright, installed and
  driven for this unit — see Session Notes) against `vite preview`: the
  login screen renders with no console errors; submitting against the
  unconfigured `.env.example` shows the "Dashboard is not configured"
  message rather than a blank crash. A second, temporary harness
  (`dev-preview.tsx`/`.html`, deleted before this entry was written — not
  part of the app) rendered `AppointmentCard`, `EscalationCard`,
  `Sidebar` and `TopBar` against fixture data: the scheduled/no-show
  status badges, the warning-left-border escalation cards, the
  live-call/background-scan source badges, and the per-appointment
  activity toggle (expanding to show "reminder sent") all matched
  `ui-context.md`. Fixed the opacity-modifier bug this same pass caught.
  **Not verified, and cannot be yet**: a real Cognito sign-in, a real
  `dashboard_api.py` response, and the resolve-escalation write path
  against a live queue — all wait on the same blocked `cdk deploy` plus
  Next Up #3's seeding that every other not-yet-verified item in this
  tracker is blocked on (Session Notes).

- **The patient-facing guest-identity Cognito identity pool**
  (Next Up #2b, the last piece of the old "build the staff dashboard"
  item). `api_stack.py` gained one new method,
  `_build_patient_guest_identity`, and one new constructor parameter,
  `agent_runtime`, wired from `app.py` as `agent.runtime` — the `Runtime`
  object `agent_stack.py` already builds and returns.
  **Assigned to `api_stack.py`, not `frontend_stack.py`** — the second
  candidate `agent_stack.py`'s own docstring had left open. The deciding
  fact: this identity pool's whole point is granting a role permission to
  invoke the AgentCore Runtime, so it needs that runtime's ARN;
  `api_stack.py` already carries a stack dependency on `agent_stack.py`
  (`app.py`: `api.add_stack_dependency(agent)`, added when the dashboard
  API was built, justified then as "voice bridge targets the agent
  runtime"), while `frontend_stack.py` is still an empty skeleton with no
  reason yet to depend on the agent stack at all.
  **Guest identities only — no user pool attached.** `CfnIdentityPool`
  is built with `allow_unauthenticated_identities=True` and no
  `cognito_identity_providers`, since a patient never signs in
  (`architecture.md` -> Auth and Access Model). This is a deliberate
  departure from the vendored sample's own `auth-stack.ts`, which pairs
  its identity pool with an authenticated Cognito user pool — read as
  reference, not copied, because `project-overview.md` explicitly wants a
  no-login patient flow. It is also a second, separate identity pool from
  `StaffUserPool`/`DashboardClient` in this same stack: an anonymous
  visitor's credential path must never cross with a staff login
  (`architecture.md` -> Invariants #5), so this is its own
  `CfnIdentityPool` and its own `CfnIdentityPoolRoleAttachment`
  (`unauthenticated` role only — no `authenticated` entry), not a second
  client added to the staff pool.
  **The guest role's one grant is `Runtime.grant_invoke_runtime`**, the
  `aws_bedrockagentcore.Runtime` L2 construct's own method — used instead
  of hand-writing an `iam.PolicyStatement` with guessed action names
  (the vendored TypeScript sample's own `auth-stack.ts` grants four
  `bedrock-agentcore:Invoke*` actions against `resources: ['*']`, with a
  comment that it "will be restricted... in production": exactly the
  blanket grant `code-standards.md` -> AWS CDK forbids). `grant_invoke_runtime`
  grants only `bedrock-agentcore:InvokeAgentRuntime`, scoped to this one
  runtime's ARN — confirmed by reading the synthesized template, not
  assumed: the resulting policy names the runtime ARN via
  `Fn::ImportValue` from the agent stack's own `CfnOutput`, plus its
  `/*` sub-resource. The broader `grant_invoke` (which also grants
  `InvokeAgentRuntimeForUser`) was deliberately not used: that second
  permission is for a per-user on-behalf-of header
  (`X-Amzn-Bedrock-AgentCore-Runtime-User-Id`) this build never sets.
  **No other grant was added.** `architecture.md` -> Invariants #5: a
  role handed to every anonymous visitor must reach nothing but the
  agent runtime — no DynamoDB, S3, or Bedrock-foundation-model policy
  statement belongs on this role, unlike the runtime's own execution
  role in `agent_stack.py`, which needs exactly those.
  `agent_stack.py`'s and `api_stack.py`'s own docstrings, which both
  named this as an open placement decision, are updated to point at
  where it landed.
  Verified: `cdk synth` exits 0 for the `Api` stack alone and for all
  five stacks together (`cdk list` still shows all five, in the same
  dependency order). Read the synthesized `ClinicPilot-Dev-Api` template
  directly to confirm the shape rather than assuming it from the CDK
  call: `PatientGuestIdentityPool` (`AllowUnauthenticatedIdentities:
  true`, no providers), `PatientGuestRole`'s policy naming exactly the
  imported runtime ARN and its `/*` child, and
  `PatientGuestIdentityPoolRoleAttachment` carrying only the
  `unauthenticated` key. No `backend/tools/`, `backend/agents/`, or
  `backend/lambda/` file was touched, so the existing pytest suite is
  unaffected by this unit (infra-only, per `ai-workflow-rules.md` ->
  When to Split Work).
  **Not verified, and cannot be yet**: an actual browser exchanging a
  guest identity for AWS credentials and presigning a real WebSocket
  connection — that needs `frontend/src/voice/` (not yet built) and the
  same blocked `cdk deploy` as Next Up #1.

- **Phone country-code reconciliation, in `backend/tools/`** (part of
  Next Up #2 — old #2 said "settle the phone-number country-code question
  first," so this unit settled it *and* wrote the code, rather than
  leaving the resolution as a paper decision the seed scripts would have
  to reinterpret). Confirmed with the user first (see Open Questions,
  resolved): one country code per clinic, over leaving it unresolved or
  matching on a digit suffix.
  **`Clinics` gains one optional attribute.** `schema.ClinicAttrs.COUNTRY_CODE`
  ("country_code", digits only, no leading `+`) is documented as a
  separate concern from the four availability-config attributes it sits
  beside — a clinic with none set leaves phone handling exactly as it was,
  so this is additive and does not touch `data_stack.py` (DynamoDB enforces
  no non-key attributes; nothing CDK-side to change).
  **`validation.normalise_phone` takes it as an optional third argument.**
  A value with no explicit `+`/`00` international marker is assumed
  dialled from inside that country and gets the code prepended; a value
  that already carries the marker is left as the international number it
  is — the marker is stripped, never the digits after it. Skipped when
  `digits` already starts with the code, which does two jobs at once: it
  makes the function idempotent on its own output (needed because
  `patients.find_patient` re-normalises a value `find_patients_by_phone`
  is about to normalise again with the same `country_code` — without the
  guard the second pass would double the code on), and it is the accepted
  cost for a national number that happens to start with the same digits as
  the code (left unprefixed rather than risking a wrong double-prepend).
  **Every call site threads it from a clinic it already holds, never from
  an extra read.** `booking.book_appointment` re-orders its own
  validation: `patient_phone` is still shape-checked before any table read
  (the existing `clinics.requested == []` tests for a bad name/phone still
  hold), then re-normalised with `country_code` once the clinic has been
  read anyway for `timezone`/services. `appointments._resolve_appointment`
  already held the clinic and needed one line.
  `appointments.find_upcoming_appointments` did not previously read the
  clinic at all; it now does, purely for this — a deliberate, documented
  behaviour change (a new `NotFoundError` for an unknown `clinic_id`,
  matching the precedent `list_appointments_for_clinic` already set, and
  one that cannot fire in practice since `ClinicSession.start` already
  validates `clinic_id` before any tool runs).
  Verified: `pytest` from `backend/` — **730 passed** (719 before, 11
  new), the pre-existing 719 unchanged. New coverage: `normalise_phone`
  converging every marker/no-marker/`00`-prefix spelling of one number
  under a given `country_code`, its idempotency on its own output, and
  that omitting `country_code` leaves the old two-key behaviour exactly as
  it was; `lookup_or_create_patient` finding a patient seeded in the
  international form from a nationally-spoken call, and *not* finding them
  when `country_code` is omitted; `book_appointment` and
  `find_upcoming_appointments` doing the same end to end through a clinic
  fixture carrying `country_code`.
  **Not yet touched**: `seed/` itself, which does not exist. This unit
  fixes the number *format* the seed scripts need to agree on; writing
  them is the rest of Next Up #2.

- **`seed/`: the code half of seeding the two demo clinics** (Next Up
  #2, code half — superseded by the split recorded above). Five modules
  plus a 43-test suite: `clinic_data.py` (the two `Clinics` items —
  Bright Smile Dental and Lumiere Aesthetics, the exact shapes
  `architecture.md` -> Storage Model and `test_scheduling.py`'s fixtures
  already fixed, now both carrying `country_code: "44"` since that
  attribute exists), `sample_data.py` (specs for six sample appointments,
  three per clinic), `faq_content.py` (three FAQ documents per clinic —
  pricing, preparation, policies, `project-overview.md`'s own list),
  `aws_io.py` (the S3 / Bedrock Agent / Cognito calls beyond
  `tools.dynamo`), and `run_seed.py` (the CLI tying them together).
  `seed/` sits outside `backend/` (`architecture.md` -> System
  Boundaries already named it top-level), so `seed/__init__.py` adds
  `backend/` to `sys.path` once on import, and `backend/pytest.ini`
  gained a second `pythonpath` entry (the repository root) so
  `backend/tests/test_seed_*.py` still runs from the one existing suite
  and venv rather than a third one.
  **Every write goes through the layer that already has the rule.**
  `seed_sample_appointments` calls `tools.scheduling.check_availability`
  then `tools.booking.book_appointment` for each spec — it never composes
  an `Appointments` item by hand — so a seeded appointment cannot be a
  shape the live agent could not have produced itself
  (`architecture.md` -> Invariants #3's spirit, applied to a script). No
  tool function creates a `Clinics` row (a clinic's config is fixed data,
  never agent-created), so `seed_clinics` is the one place in this
  package that writes DynamoDB directly, through
  `tools.dynamo.clinics_table`.
  **Every AWS client is reached through an accessor, monkeypatchable the
  same way `clinics_table()` already is** — `aws_io.s3_client()`,
  `.bedrock_agent_client()`, `.cognito_client()`, each `lru_cache`d and
  lazily importing `boto3` — rather than passed in as a parameter. A
  first draft of this unit took the client as an argument instead
  (mirroring `tools.automation._send_reminder_email`'s shape); rewritten
  to match `tools.scheduling`/`tools.booking`'s accessor-function shape
  once the inconsistency was noticed, since that is the pattern the rest
  of this codebase's tests already monkeypatch.
  **Three names are duplicated from `backend/infra/`, guarded the same
  way `test_schema_matches_infra.py` already guards the other two**:
  `aws_io.KB_BUCKET_PREFIX`/`kb_source_prefix` against `data_stack.py`'s;
  `aws_io.kb_bucket_name()`'s derived default against
  `config.resource_name("kb")`. The Cognito `custom:clinic_id` attribute
  name is deliberately *not* a third copy — `ensure_staff_account` reads
  `dashboard_api.CLINIC_ID_CLAIM` via the same `importlib.import_module`
  route `test_background_scan.py` already uses for the `lambda` package,
  since `lambda` is a Python keyword.
  **Two ids cannot be derived and are required, not defaulted**: the
  staff user pool id (`$CLINICPILOT_STAFF_USER_POOL_ID`, from
  `api_stack.py`'s `StaffUserPoolId` output — Cognito assigns it, no
  naming scheme predicts it) and the demo password
  (`$CLINICPILOT_STAFF_DEMO_PASSWORD` — never hardcoded, since a password
  in source is a password in version control). Each clinic's Knowledge
  Base id is read the same way `tools.faq.query_faq` will read it at call
  time (`tools.faq.knowledge_base_id_env_var`), so seeding and querying
  can never disagree about which environment variable to check.
  **`ensure_staff_account` is idempotent on purpose**: an existing
  account's password and `custom:clinic_id` are left untouched, so a
  staff member who changed their password at the demo does not have it
  silently reset by a second seed run. `seed_clinics` is idempotent for
  the ordinary reason (`put_item` overwrites); `seed_sample_appointments`
  is not, and its own docstring says so — it is meant to run once against
  a freshly deployed, empty environment.
  **A real ingestion job is triggered, not assumed.** `agent_stack.py`
  wires an S3 data source with no auto-sync trigger, so
  `start_kb_ingestion` looks up the clinic's one data source
  (`list_data_sources`) and starts it after `upload_faq_documents` writes
  under that clinic's `kb/{clinic_id}/` prefix — otherwise the uploaded
  documents would sit in S3, invisible to `query_faq`, until someone
  noticed.
  **`run_seed.main` keeps going past a failed step.** Its four steps
  (clinics, appointments, faq, staff) are independent enough that one
  failing — most likely faq, before a Knowledge Base id is set — should
  not stop the others from seeding; every exception is caught, not just
  `tools.errors.ToolError`, since a step can just as easily fail on a
  botocore credentials/region error, the same distinction
  `agents/cli.py`'s `main` already draws. `--dry-run` prints what every
  requested step would do and calls no AWS client at all — pinned by a
  test that makes every client accessor raise if called — which is the
  only mode this environment can actually run (see Session Notes);
  `--skip STEP` (repeatable) leaves one out.
  **A real gap surfaced and was deliberately routed around, not fixed
  here**: `validation.normalise_phone`'s `country_code` reconciliation
  only *prepends* the code when no international marker is present — it
  does not strip a national trunk prefix first, so a UK number's natural
  national form (`"07700 900002"`) would prepend to `"4407700…"` while
  its international form produces `"447700…"`, and the two would not
  converge. `sample_data.py`'s two "national form" sample numbers write
  the number without the leading trunk `0` instead, documented inline as
  a deliberate workaround rather than a demonstration that reconciliation
  works for every country's dialling plan. Not fixed here —
  `tools/validation.py` is a foundational module several other tools
  import, and fixing it is a separate, scoped change
  (`ai-workflow-rules.md` -> When to Split Work) — see Open Questions.
  Verified: `pytest` from `backend/` — **773 passed** (730 before, 43
  new), the pre-existing 730 unchanged. Offline throughout: `clinic_data`
  is fed through the real `tools.scheduling.check_availability` against a
  fake table (not just shape-asserted) so a config that merely *looks*
  right cannot pass; `seed_sample_appointments` is driven end to end
  through the real `scheduling`/`booking`/`patients` functions against
  the same fakes `test_booking.py`'s `tables` fixture uses, booking all
  six sample specs for both clinics against a fixed reference date so the
  suite does not depend on which day it happens to run; `aws_io`'s S3,
  Bedrock Agent, and Cognito calls are each exercised against a
  hand-rolled fake client, including the "already exists" Cognito path
  and the "no data source configured" ingestion failure. Also run for
  real from the repository root: `python -m seed.run_seed --dry-run`
  (prints every step's plan, confirmed no AWS client is constructed) and
  the real steps against an unconfigured shell, which produced the same
  `NoRegionError`, named and exit code 1, `agents/cli.py` already
  produces for the same reason.
  **Not verified, and cannot be yet, in this environment**: an actual
  seed run against deployed tables/bucket/pool/Knowledge Bases. No AWS
  credentials are usable here — see Session Notes — so this needs the
  same `cdk deploy` Next Up #1 does, plus the pool id, password, and
  per-clinic Knowledge Base ids that deploy's outputs provide.

## In Progress

- **Knowledge Base embedding model swap: Titan v2 -> Cohere Embed English
  v3.** Code change is done and synthesises; the deploy is **not** run, and
  **AWS is mid-swap** — read this before touching the Agent stack.

  *Why:* this account has zero on-demand quota for
  `amazon.titan-embed-text-v2:0` (confirmed by AWS Support), so every
  ingestion `InvokeModel` fails with `ThrottlingException`. Raising it is a
  2-4 week Service Quotas request. `cohere.embed-english-v3` has working
  quota here — verified by a direct `invoke-model` returning a real
  1024-float embedding, while the same call against Titan v2 still
  throttles. Both models are 1024-wide, so `EMBEDDING_DIMENSIONS` and both
  `s3vectors.CfnIndex` dimensions are unchanged (`cdk diff` confirmed the
  indexes are untouched).

  *Changed:* `backend/infra/agent_stack.py` only — `EMBEDDING_MODEL_ID`
  plus the two comment blocks explaining it. Nothing outside CDK ever
  names an embedding model (Bedrock embeds internally during ingestion),
  so `seed/` and `backend/tools/` needed no change.

  *Live AWS state — the part that matters:* `ClinicPilot-Dev-Agent` is
  `UPDATE_ROLLBACK_COMPLETE` and **both Knowledge Bases have been deleted
  out-of-band**, so the deployed template references two resources that no
  longer exist. The first deploy attempt failed because
  `VectorKnowledgeBaseConfiguration` is in the CFN resource's
  `createOnlyProperties` (see Session Notes) — changing the embedding model
  replaces the KB, and the deterministic name collided with the live one
  (409 `AlreadyExists`). Deleting the old KBs was safe and deliberate: both
  were verifiably empty (0 vectors in each S3 Vectors index, zero ingestion
  jobs ever), and the S3 source documents were untouched.

  *To resume, in order:*
  1. `cdk deploy ClinicPilot-Dev-Agent --exclusively` from
     `backend/infra` (needs Docker running — the run also picks up a
     container asset rebuild for commit `7fcd5d5`, which the deployed
     runtime predates). This recreates both KBs on Cohere under their
     original names.
  2. Copy the new `DentalKnowledgeBaseId` / `CosmeticKnowledgeBaseId`
     outputs into `.env` — replacement mints **new** ids, so the two
     `CLINICPILOT_KB_ID_*` values there are now dead. The runtime's own
     copies are CFN references and update themselves.
  3. `python -m seed.run_seed --skip clinics --skip appointments --skip
     staff` to run only the FAQ step, then poll
     `get-ingestion-job` — the step only *starts* a job, so a clean exit
     is not yet proof that embedding worked.

  *Status note (2026-09-12): the user reports the full CDK deploy and
  seed have since been run and the frontend tested locally. Whether
  these resume steps were executed as part of that is unconfirmed —
  check the Agent stack's current status and the two
  `DentalKnowledgeBaseId` / `CosmeticKnowledgeBaseId` outputs before
  touching anything here.*

## Next Up

Both halves of the old "drive the voice agent" item are in Completed:
`voice.py` builds the speech agent and `mic.py` drives it from a
microphone. The old "deploy to AgentCore Runtime" item has now had the
same split applied to it twice over (`ai-workflow-rules.md` -> When to
Split Work: Python logic and its CDK deployment are separate steps): the
code half, `agents/agentcore_app.py`, and the CDK-resources-plus-
Dockerfile half, `agent_stack.py`'s AgentCore Runtime, are both in
Completed below. What remains of #1 is now purely the deploy action
itself — a `cdk deploy` needing Docker and AWS credentials this
environment has neither of — and the real call that follows it, which is
why **#2 (seed) unblocks more than its position suggests**: it is what
turns either interface, and soon the deployed one, from a program that
runs into a call someone can listen to, and it is where the greeting,
voice and text-model questions get answered.

The old #2 ("KB bucket plus the Bedrock Knowledge Base, `faq_agent.py`,
and its Orchestrator wiring") has been completed in full, across three
units split by `ai-workflow-rules.md` -> When to Split Work: the
infrastructure half (the KB source bucket and one Bedrock Knowledge Base
per demo clinic), the tool half (`backend/tools/faq.py`), and now the
agent half (`faq_agent.py` plus its wiring into `orchestrator.py`). All
three are in Completed below. The agent tree — Orchestrator over
Scheduling, FAQ and Escalation — is therefore finished; everything left
in this list is infrastructure, background automation, dashboard, or
content, not agent code.

The old #2 ("Build the staff dashboard") has now been completed in full,
across four units split by `ai-workflow-rules.md` -> When to Split Work:
its Python half (`tools/appointments.list_appointments_for_clinic` plus
`lambda/dashboard_api.py`'s four routes over it and the three existing
escalation reads/write), its CDK half (`api_stack.py`'s staff Cognito
user pool, REST API Gateway, and Lambda), its UI half
(`frontend/src/dashboard/`, plus the Vite/React/Tailwind/shadcn
scaffolding under `frontend/` that was its first thing to need), and now
2b, its last remaining piece: the patient-facing guest-identity Cognito
**identity pool**, also landed in `api_stack.py`
(`_build_patient_guest_identity`) rather than `frontend_stack.py` (the
other candidate Next Up #1's own docstring had named) — it needs the
AgentCore Runtime's ARN, which `api_stack.py` already takes a stack
dependency on `agent_stack.py` for, and `frontend_stack.py` is still an
empty skeleton. The guest role gets exactly one grant,
`runtime.grant_invoke_runtime`, and nothing else — no DynamoDB, S3, or
Bedrock-model access, per `architecture.md` -> Invariants #5. All four
are in Completed below; the numbered list is renumbered accordingly.

The old #2 ("Seed the two demo clinics with config, sample appointments,
staff Cognito accounts, and FAQ documents") has now had the same
code/deploy split applied to it that Next Up #1 already had
(`ai-workflow-rules.md` -> When to Split Work): `seed/` — `clinic_data.py`,
`sample_data.py`, `faq_content.py`, `aws_io.py`, `run_seed.py` — is
written, offline-tested, and runnable (`--dry-run` proves it end to end
with no AWS client touched at all); what remains is running it for real,
which needs the same credentials and deployed stacks Next Up #1's actual
`cdk deploy` does. See Completed. The numbered list is renumbered
accordingly.

1. **Patient voice UI** — `frontend/src/voice/`: clinic picker, presigned
   WebSocket to the deployed `/ws` (guest identity-pool credentials),
   mic capture + audio playback, live transcript, voice orb.
   Plan: `docs/superpowers/plans/2026-09-12-patient-voice-ui.md`.
   Frontend-only unit (`ai-workflow-rules.md` -> When to Split Work).
   **Status (2026-09-13): code complete and unit-tested** (27 Vitest
   tests, `npm run build` clean) — `voice/` picker/orb/transcript/hook
   plus all connection modules, and `App.tsx` now routes `#/voice`.
   Two deploy-blocking facts were discovered and fixed while verifying
   end-to-end, both in `api_stack.py` (deployed live, see Session
   Notes): the guest role needed the
   `bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream` action
   (the L2's `grant_invoke_runtime` covers only plain
   `InvokeAgentRuntime`), and the browser must use the Cognito
   **basic (classic) auth flow** (`GetOpenIdToken` + STS
   `AssumeRoleWithWebIdentity`), because enhanced-flow
   `GetCredentialsForIdentity` applies an unauthenticated scope-down
   session policy whose service allow-list excludes bedrock-agentcore
   entirely — no role policy can override it.
   **The tenant-selection decision is made (2026-09-13): the first
   WebSocket message.** The browser sends `{"clinic_id": ...}` as its
   first frame; `agentcore_app.py` reads and validates it after
   `accept()`. Implemented on both ends (`agentcore_app.py` +
   `test_agentcore_app.py`; `agentSocket.ts`), the Agent stack was
   redeployed, and the live probe proved the whole wire chain:
   basic-flow credentials, presign, socket open, handshake accepted,
   and a real Nova Sonic connection (`bidi_connection_start`,
   input tokens growing).
   **What remains is one live bug: the agent never speaks.** No
   transcript or audio comes back within 45s (output tokens pinned at
   0). Diagnosed locally against real Nova Sonic — see the Session
   Note "The greeting silence" for the full state and how to resume.
   Then the real browser session, cleanup of the two scratch probes,
   and this item is done.
2. **Escalation email notifications** — when the agent creates an
   escalation, notify clinic staff by email (SES) so an escalation is
   actionable without watching the dashboard.
3. **Frontend hosting stack** — fill the empty `frontend_stack.py`: S3 +
   CloudFront for the built SPA, producing the public demo link item #6
   needs.
4. **AgentCore Memory** — session state per `architecture.md`, so the
   voice agent remembers context across a call (and optionally across
   calls) without process-level state.
5. **Settings tab** — editable hours and services (user decision,
   2026-09-12): staff edit hours/closures/services in the dashboard,
   writing to the Clinics table. Needs a new authenticated write route
   plus validation — backend unit first, then its frontend half.
6. Deploy `agentcore_app.py` to the AgentCore Runtime and verify one
   voice session end-to-end. **Status note (2026-09-12): the user
   reports the CDK deploy and seed have now been run and the frontend
   tested locally** — the "blocked in this environment" caveats that
   used to sit on this item predate that report. What it still needs is
   the real voice-session verification (a browser pointed at the
   deployed `/ws` with a seeded clinic behind it), which item #1's UI is
   what makes possible. Whether the KB-swap resume steps in "In
   Progress" were part of the reported deploy is unconfirmed; read that
   section before touching the Agent stack.
7. **Demo video, live demo link, AWS Builder ID / builder.aws.com
   post.** The architecture diagram and README half of the old #2 is
   done (see Completed) — a root `LICENSE` (MIT) and
   `docs/architecture.md` (a Mermaid system diagram plus a reading
   guide tying it back to `architecture.md` -> Invariants) now exist
   too, alongside a rewritten root `README.md` covering status, stack,
   repo layout, local run instructions for every piece that *can* run
   here (tests, `cdk synth`, frontend build, seed `--dry-run`), and a
   submission checklist. What remains of this item needs #3's hosting
   stack for the live demo link and #6's verified deployment for
   something real to film/link; an AWS Builder ID is an account signup
   only the user can do.

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
  `days=1` is the behaviour already built and tested. Shipped.

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
- **Which text model do the sub-agents reason with?**
  `architecture.md` -> Stack names Nova Sonic for the *voice* layer and
  says nothing about the model behind the Orchestrator and its
  sub-agents, which are ordinary text agents. Not invented here:
  `build_scheduling_agent` and `build_escalation_agent` each take an
  optional `model` and pass `None` by default, which leaves the Strands
  default (today `global.anthropic.claude-sonnet-4-6` on Bedrock). That
  is a working default, not a decision — it needs one row in
  `architecture.md` -> Stack and one place to configure it.
  **The one place now exists**: `build_orchestrator` threads a single
  `model` into both sub-agents and `start_call` takes it, so all three
  agents in a session run on whatever that one argument says, and there
  is exactly one line to change when it is settled. What is still
  undecided is the *value*, and whether the Orchestrator should run on
  a cheaper/faster model than the sub-agents — a router that only picks
  between two tools is a different job from one that sequences a
  booking, and it is the one in the patient's latency path.
  **Narrowed to a value, not a mechanism.** `agents/cli.py` now selects
  the model — `--model`, defaulting to `$CLINICPILOT_TEXT_MODEL` — and
  hands it to `start_call`, which threads it into all three agents. So
  choosing it is the interface layer's job (the voice bridge will make
  the same call), there is exactly one place to change it, and no agent
  definition names a model. What is still open is which id to put there,
  and whether the Orchestrator should run on a cheaper/faster one than
  its sub-agents — a question that wants a session typed at a real
  model, which needs seeded clinics (Next Up #5). Nothing is
  blocked meanwhile: unset leaves the Strands default.
  **The voice layer narrows it further, and shrinks it.** Over a
  microphone the Orchestrator is Nova Sonic, so this question is no
  longer about the router at all — `build_voice_agent` takes
  `voice_model` and `text_model` separately, and only the *sub-agents*
  read the text one. What is left to decide is one id for the two
  assistants, plus (for the typed interface only) whether the text
  Orchestrator runs on something cheaper than they do.
  **Both interfaces now read one variable.** `mic.py --model` selects
  the sub-agents' model exactly as `cli.py --model` does, and the name
  they read — `TEXT_MODEL_ENV` — moved to `orchestrator.py` so it is
  spelled once. Deciding the value is still one line in one place; what
  it now also needs is a spoken call, because latency behind a
  microphone is the half of the question a typed session cannot show.

- **Who speaks the greeting — the interface or the model?**
  `project-overview.md` -> Core User Flow step 2 says the Orchestrator
  greets the patient, and it does: the system prompt tells it to open
  with the clinic's name and ask what it can do. But a Strands `Agent`
  says nothing until it is spoken to, so *something* has to prompt the
  first turn, and the two candidates behave differently. A fixed
  greeting string composed by the interface layer is instant and cannot
  hallucinate the clinic's name; a model-generated one costs a round
  trip of silence before the patient hears anything. Not decided here,
  because it is genuinely the voice layer's question: Nova Sonic's
  `BidiAgent` may open a session with agent audio of its own, which
  would make an interface-composed greeting either redundant or the
  only option. No greeting helper was added to `orchestrator.py` rather
  than adding one that turns out to be the wrong shape.
  **The experiment now exists.** `agents/cli.py` opens a call with
  `OPENING_TURN`, a stage direction ("the patient has just been
  connected and is waiting for you to speak") rather than a greeting of
  our own — so the words are the model's and the prompt's instruction is
  what gets judged. `--no-greeting` runs the other arm, where the
  operator speaks first and the agent never greets anyone. Still
  undecided, because the deciding fact is what `BidiAgent` does at the
  start of a voice session: settle it against a live one.
  **Half answered by the code, not yet by a call.** A `BidiAgent` does
  not open with audio of its own: it holds the connection open in
  silence until something is sent to it (`agent/loop.py` — the model
  task only forwards what arrives). So the interface-composed greeting
  is not made redundant by the library, and the same stage direction
  works over a microphone: `voice.greet` sends `OPENING_TURN`, and
  `OPENING_TURN` moved to `orchestrator.py` so both interfaces send one
  string. What is still open is the *cost* — how long a patient hears
  nothing while a speech model composes a greeting — and that is
  audible only against a live session. `mic.py` now *prints* that
  number every turn (`greeting: first audio after 1.4s`), so what the
  question waits on is no longer an interface but credentials and a
  seeded clinic (Next Up #5).

- **How does a voice call end?** `project-overview.md` describes a
  session that begins and a patient who is told staff will follow up,
  but nothing about hanging up. Over a keyboard it does not arise: the
  operator types `exit` and a patient's "goodbye" is an ordinary turn.
  Over a microphone there is a live Bedrock connection, and it does not
  close itself: Nova Sonic caps a connection at eight minutes, but
  `BidiAgentLoop` catches that timeout and *restarts* it so the patient
  hears nothing (`agent/loop.py`). A session nobody ends therefore runs
  until the browser tab does. The vendored sample gives its agent a
  `stop_conversation` tool; that tool is deprecated in Strands
  (superseded by `request_state["stop_event_loop"]`) and its own
  docstring says it is *not* for "goodbye" or "bye". So nothing was
  wired: a third tool on the front desk needs deciding, not guessing.
  The candidates are a hang-up tool the model calls when the patient
  says goodbye, and a browser control that closes the connection —
  possibly both, since a patient who walks away never says goodbye. It
  matters before Next Up #1, since a deployed session that never closes
  is a meter left running.
  **`mic.py` deliberately does not answer it.** Locally the operator
  presses Ctrl-C, exactly as they type `exit` over the keyboard, and
  `BidiAgent.run` closes the connection and both devices on its way out.
  A patient saying "goodbye" is still an ordinary turn. That works
  because a person is sitting at the process; nothing about it carries
  to a browser tab that was closed, which is the case the question is
  actually about. What the interface *does* add is that a closed or
  restarted connection now prints a line, so whichever answer is chosen
  can be watched working.

- **Which Nova Sonic voice does each clinic answer in?** Nova Sonic
  offers a small set (`matthew`, `tiffany`); `$CLINICPILOT_VOICE_ID`
  selects one and unset leaves the library's default. Nothing in
  `ui-context.md` or `project-overview.md` says whether the dental and
  cosmetic demo clinics should sound different — `ui-context.md`
  deliberately gives them one token set and differentiates by name and
  content, which argues for one voice too, but a voice is per *session*
  and could just as well be a clinic config field like `timezone`. Not
  invented: today both would sound identical. Worth one line either way
  before the demo is recorded.

- ~~**Does the FAQ tool call Bedrock's `retrieve` or
  `retrieve_and_generate`?**~~ **Resolved** — `retrieve`, settled while
  writing `backend/tools/faq.py` (Next Up #2, tool half) rather than
  deferred further, since the item explicitly named this as blocking.
  `retrieve` returns raw passages and leaves *composing* the spoken
  answer to the sub-agent's own model — consistent with every other tool
  in `backend/tools/`, which return facts for an agent to phrase, never a
  phrased answer themselves (`code-standards.md` -> General, "business
  logic ... never inline inside an agent definition" cuts the other way
  for a tool that already contains an LLM call). `retrieve_and_generate`
  would have done the composing inside the tool, in one Bedrock call,
  with no sub-agent judgement over the wording — cheaper in round trips,
  but a second, hidden model choice (which one generates?) and a second
  place an answer could drift from `ORCHESTRATOR_SYSTEM_PROMPT`'s honesty
  rules. See Completed for what this decided in code: `query_faq` returns
  `{"passages": [...], "found": bool}`, never a composed sentence.

- ~~**What is the background job's no-show/reschedule heuristic?**~~
  **Resolved** — put to the user rather than invented
  (`ai-workflow-rules.md` -> Handling Missing Requirements), since
  reminders are one-way SES email and there is no confirmation channel a
  "did they mean to come?" signal could be read from. Three answers: (a)
  the signal is a patient's own count of past `no_show` appointments at
  this clinic — the only signal actually available; (b) a flagged
  appointment is escalated to staff outright, **not** auto-rescheduled,
  so `project-overview.md`'s middle option is deliberately unimplemented
  and `architecture.md` -> Invariants #6 holds by construction; (c) one
  reminder, sent once, for anything starting within 24 hours of the scan
  running. Implemented in `tools/automation.py`
  (`NO_SHOW_RISK_THRESHOLD = 1`, flagged as a boundary decision rather
  than a product rule, the same way `escalations.DEFAULT_ESCALATION_LIMIT`
  is). See Completed.

- **Can a patient ask what they already have booked?**
  `project-overview.md` lists check availability, book, reschedule,
  cancel and FAQ — not "when is my appointment?". So the Scheduling
  sub-agent was not given one, even though the tool exists
  (`find_upcoming_appointments`) and `reschedule_appointment` already
  names a caller's appointments when it refuses. A patient who phones
  only to check the time of their visit therefore gets an answer only
  as a side effect of trying to move it. Deliberately not invented:
  adding a read tool is one wrapper if the answer is yes.

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
  rather have it idempotent, say so before Next Up #4 is built.

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

- ~~**Does a spoken phone number need a default country code?**~~
  **Resolved** — option (a): one country code per clinic, put to the user
  rather than defaulted (`ai-workflow-rules.md` → Handling Missing
  Requirements) ahead of option (b) (leave it, seed scripts/prompt use one
  consistent form) and option (c) (match on a digit suffix, rejected here
  too as collision-prone). `Clinics` gains an optional `country_code`
  (`schema.ClinicAttrs.COUNTRY_CODE`, digits only, no leading `+`,
  alongside `timezone`); `validation.normalise_phone` takes it as an
  optional third argument and, when given, prepends it to a number with no
  explicit `+`/`00` marker rather than leaving national and international
  spellings as two keys. `None` (a clinic with nothing set) is the old
  behaviour, unchanged. Implemented in `backend/tools/`: `booking.py`
  reorders its own validation so the tenant-boundary/no-read-before-
  validation shape check still runs first, then re-normalises with the
  clinic's code once it has been read anyway for its other config;
  `appointments.find_upcoming_appointments` now reads the clinic for the
  same reason (a new, documented `NotFoundError` case, matching
  `list_appointments_for_clinic`'s existing one); `_resolve_appointment`
  already held the clinic and needed only the one extra line.
  `patients.py`'s three functions take `country_code` as an optional
  keyword and thread it into their own `normalise_phone` calls — this is
  also where the idempotency guard earned its keep: `find_patient` calls
  `find_patients_by_phone` with an *already-normalised* phone and the same
  `country_code`, so `normalise_phone` had to not double-prepend on a
  second pass over its own output. See Completed.

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

- **`validation.normalise_phone`'s `country_code` reconciliation does
  not handle a national trunk prefix.** Surfaced while writing `seed/`'s
  sample data (`ai-workflow-rules.md` -> Handling Missing Requirements),
  not by a test failure: the function only *prepends* `country_code` when
  no `+`/`00` marker is present, so a UK number written the way a caller
  would naturally say it nationally — `"07700 900002"`, leading trunk
  `0` — prepends to `"4407700900002"`, while the same number's
  international form (`"+44 7700 900002"`) normalises to
  `"447700900002"`. The two do not converge, which defeats the whole
  point of `country_code` for exactly the numbers most likely to exercise
  it: most dialling plans outside the US (UK, and most of Europe,
  Australia, and elsewhere) use a trunk prefix like this one, dropped
  when the country code is added and present otherwise. `seed/sample_data.py`
  routes around it — its "national form" sample numbers omit the leading
  `0` rather than demonstrate a reconciliation that would silently fail
  — but the underlying gap is still live for a real UK caller speaking
  their number the ordinary way. Not fixed in the `seed/` unit that found
  it: `tools/validation.py` is foundational (imported by `patients.py`,
  `booking.py`, `appointments.py`, and their test suites), so a fix is
  its own scoped unit, not something to fold into a seed script
  (`ai-workflow-rules.md` -> When to Split Work). Needs a decision, not
  just a fix: whether to strip a single leading `0` unconditionally when
  `country_code` is set (simple, but wrong for the handful of countries
  whose national numbers can legitimately start with `0` after the trunk
  digit is removed) or something more deliberate.

- **Public clinic-listing route?** The patient voice UI needs the list
  of clinics before a call, but the dashboard API is staff-auth-only.
  Interim answer (2026-09-12): a static registry in
  `frontend/src/voice/lib/clinics.ts` holding the two seeded demo
  clinics — fine for a two-clinic demo, wrong the moment clinics are
  added in DynamoDB. Should a public, read-only, unauthenticated
  `/clinics` route exist instead?

- ~~**Does AgentCore's presigned-URL proxy forward extra query parameters
  (`clinic_id`) to `/ws`?**~~ **Answered (2026-09-13, definitively):
  no.** A live probe — guest credentials via the Cognito basic flow,
  SigV4-presigned `/ws` URL with `clinic_id` in the signed query —
  reached the deployed runtime and was rejected by *our own app*,
  whose CloudWatch log shows `a call arrived with no clinic_id`
  followed by `WebSocket /ws 403`. The IAM layer passed (the 403 came
  from the app, not the edge), so the socket genuinely arrived at
  `agentcore_app.py` without the parameter: the AgentCore gateway
  consumes the presigned URL's query string itself and forwards only
  its own recognized parameters (qualifier, session id) to the agent,
  not arbitrary ones. **The tenant-selection channel must therefore
  change** — see the new Open Question below. Not decided inline, per
  `ai-workflow-rules.md` -> Handling Missing Requirements.

- ~~**How does the browser tell the deployed `/ws` which clinic the call
  is for, now that the query-string channel is known not to work?**~~
  **Resolved (2026-09-13): the first WebSocket message.** The browser
  sends `{"clinic_id": ...}` as its first frame and
  `agentcore_app.py` reads-and-validates it after `accept()` —
  implemented on both ends, deployed, and proven live by the probe
  (the handshake is accepted and the call connects). The choice is
  still the browser's, never spoken, and still fixed once read; the
  read moved from before `accept()` to after it, which the module
  docstring now explains.

- **SES sandbox recipients** — seeded patient addresses are
  `@example.com`, so reminder emails will be `MessageRejected` until
  the recipients are verified or the account leaves the SES sandbox.
  Blocks end-to-end reminder testing, not reminder code.

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

- **A staff member's clinic reaches the dashboard API as a Cognito
  custom attribute, `custom:clinic_id`, never as a request parameter.**
  `architecture.md` -> Auth and Access Model said routes are "scoped to
  the authenticated staff member's clinic" without saying how the token
  carries that. One user pool with one demo account per clinic
  (`architecture.md` -> Stack) means each seeded account can simply carry
  its own clinic as a custom attribute; API Gateway's Cognito authorizer
  puts every verified claim on `requestContext.authorizer.claims` before
  the Lambda runs, so `dashboard_api._clinic_id_from` reads it from
  there and `backend/tools/` is called with exactly that value — a path
  parameter or query string never supplies or overrides it. The
  alternative (a `clinic_id` request parameter, checked against the
  token) would make a cross-tenant request *expressible* and rely on a
  check to refuse it, the same shape of hole
  `architecture.md` -> Invariants #1 already rules out for the query
  layer. Seeding that attribute onto each demo account is now part of
  Next Up #3.
- **The dashboard Lambda routes on a plain `(method, resource)` dict, not
  a framework.** `dashboard_api.py` is a single Lambda behind API Gateway
  proxy integration; four routes did not justify a router dependency, and
  `resource` (API Gateway's route *template*, e.g.
  `/escalations/{escalation_id}`) keeps the table's size fixed rather
  than growing with every id ever requested.

- **Creating the two demo Cognito accounts is a seed-script job, not a
  CDK one.** `api_stack.py`'s user pool declares the `clinic_id` custom
  attribute and turns off self-sign-up and password recovery, but
  provisions no users. A CDK-managed Cognito user (`CfnUserPoolUser`)
  needs a password strategy — a temporary password, force-change flow,
  or a custom resource calling `admin-set-user-password` — that is a
  credential decision, not a resource-naming one, and Next Up #3's seed
  script already scripts `boto3` calls for sample data; adding
  `admin-create-user`/`admin-set-user-password` there for both demo
  clinics is one script owning every piece of demo-account setup instead
  of splitting it between CDK and a script.

- **The staff user pool and the patient-facing guest identity pool are
  two different things, deliberately kept apart.** `api_stack.py` built
  in this unit is the *staff* pool only — Cognito **user pool**
  authentication, one demo account per clinic, gating the dashboard API.
  The **identity pool** with unauthenticated (guest) identities
  (`architecture.md` -> Auth and Access Model) is what an anonymous
  browser needs to presign the AgentCore WebSocket, and remains entirely
  unbuilt — a separate credential path on purpose
  (`architecture.md` -> Invariants #5: staff auth must not share a path
  with anonymous visitors), so it is not a sub-item of this unit and is
  still open in Next Up.

- **CORS on the dashboard API is wide open for now, not scoped to a
  domain.** `frontend_stack.py` has no CloudFront distribution yet, so
  there is no origin to allowlist. `default_cors_preflight_options` on
  the whole API accepts every origin/method — an engineering default for
  an unbuilt frontend, not a product decision, and the fix is one
  parameter change once Next Up #2's UI item picks a domain.

## Session Notes

- **The greeting silence: Nova Sonic does not answer the opening text
  turn (2026-09-13, diagnosis in progress).** After the handshake
  protocol was deployed, the end-to-end probe (`frontend/
  probe-handshake.mjs`) proved the whole wire chain — credentials,
  presign, socket, handshake, a real Nova Sonic connection — but no
  transcript or audio ever came back (output tokens pinned at 0 over
  45s). Reproduced **locally** with `backend/scratch_text_turn.py`
  against the real model (no container involved), so the deployed
  container is healthy and the bug is in what we send:
  1. A bare interactive text turn (`OPENING_TURN` →
     `contentStart(TEXT, USER, interactive=true)` + `textInput` +
     `contentEnd`) is *accepted* — input tokens grow — but the model
     never responds. This exactly matches the deployed behavior.
  2. A 200ms silence audio chunk followed by closing the audio
     container (turn end) *also* produced no output (150 speech
     input tokens, output still 0) — though only silence was sent, so
     endpointing on zero speech may legitimately see no turn to
     answer.
  **Not the cause:** the two `Traceback` events in the runtime log
  group are an `awscrt` `InvalidStateError` fired during teardown
  when the probe's timeout closed the socket — a red herring.
  **Where to resume:** the open question is what provokes Nova
  Sonic's first output turn. Candidates: real speech audio (test with
  an actual spoken utterance, not silence); a longer/real audio turn
  followed by text; or dropping the proactive greeting and letting
  the browser play a canned greeting while the agent waits for the
  patient's first speech (the vendored sample never greets — the
  caller speaks first, and `Greeting` was only ever tested against
  the fake model). Nova 2 docs describe interactive text as
  "cross-modal input … during an active voice session", which hints
  text may not provoke output before any audio exists. Test by
  editing `backend/scratch_text_turn.py` (scratch, untracked — not
  app code) and rerunning; verify the deployed path with
  `frontend/probe-handshake.mjs` (also scratch, untracked) after any
  `agentcore_app.py`/`voice.py` change and Agent-stack redeploy.

- **Two live-deploy facts about the patient guest voice path
  (2026-09-13), both verified against the deployed stacks, both fixed
  in `api_stack.py` and deployed:**
  1. *`grant_invoke_runtime` does not cover the WebSocket action.* The
     browser voice path presigns the runtime's `wss` `/ws` URL, which
     the service authorizes as
     `bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream` — a
     separate action the AgentCore L2 has no grant method for. The
     presigned URL returned 403 "no identity-based policy allows
     InvokeAgentRuntimeWithWebSocketStream" until an explicit
     `iam.PolicyStatement` was added to the guest role. Note the
     service rewrites the resource to `<runtime-arn>/runtime-endpoint/
     <qualifier>` when authorizing, so the statement must cover the
     runtime's subtree (`<arn>` + `<arn>/*`), the same shape the L2's
     own grant uses.
  2. *Enhanced-flow Cognito credentials can never invoke AgentCore.*
     `GetCredentialsForIdentity` (enhanced flow) applies an
     unauthenticated **scope-down session policy** whose service
     allow-list (lambda, dynamodb, s3, polly, lex, execute-api, …)
     does not include bedrock-agentcore — the effective permissions
     are the intersection of role policy and session policy, so no
     role policy can grant it (Amazon Cognito Developer Guide ->
     IAM roles -> "Services that unauthenticated users can access").
     Observed live as 403 "no session policy allows
     InvokeAgentRuntimeWithWebSocketStream" *with a correct role
     policy attached*. The fix is the **basic (classic) auth flow**:
     the browser calls `GetOpenIdToken` (anonymous) then STS
     `AssumeRoleWithWebIdentity` against the guest role itself, which
     applies only the role's own policy. `api_stack.py` now exports
     `PatientGuestRoleArn` for exactly that call, and
     `frontend/src/voice/lib/guestCredentials.ts` implements the flow
     with `@aws-sdk/client-sts`.

- **A Bedrock Knowledge Base's embedding model cannot be changed in
  place.** `AWS::Bedrock::KnowledgeBase` lists
  `/properties/KnowledgeBaseConfiguration/VectorKnowledgeBaseConfiguration`
  (the whole property, not just its `Type`) in `createOnlyProperties`, so
  editing `EmbeddingModelArn` **replaces** the Knowledge Base. Because
  `agent_stack.py` names each KB deterministically via
  `config.resource_name`, the replacement's create collides with the live
  resource and the update fails with a 409 `AlreadyExists` — the stack
  rolls back cleanly, but the swap cannot proceed without either freeing
  the name (delete the old KB first) or changing it. Verify with
  `aws cloudformation describe-type --type RESOURCE --type-name
  AWS::Bedrock::KnowledgeBase`. Two traps worth remembering: `cdk diff`
  rendered this as a plain `[~]` in-place update and did **not** flag the
  replacement, so the diff is not trustworthy for create-only properties;
  and the S3 Vectors index is a separate CFN resource that survives the
  KB's replacement, so an index still attached to the outgoing KB is a
  second possible conflict if you rename instead of deleting.

- **`cmd > log 2>&1; echo "EXIT=$?"` reports the `echo`'s status, not the
  command's.** A failed `cdk deploy` was read as exit 0 that way — the
  rollback was only visible in the log body. Capture the code immediately
  (`cmd; rc=$?`) or `tee` the deploy log and read it.

- **Strands passes a tool's return value through `json.dumps`**, and
  falls back to `repr` when that fails — so a `Decimal` reaching a tool
  result is read out to a patient as `Decimal('15')`. The tool layer
  already coerces durations, and a test now pins that a
  `check_availability` result survives the dump. Worth remembering for
  every tool the remaining sub-agents wrap.

- **A `@tool` function's return is marked `success` unless it carries
  `status` and `content` itself** (`strands/tools/decorator.py` ->
  `_wrap_tool_result`), in which case it is passed through verbatim.
  That is why `agents/results.py` returns that shape rather than an
  `{"error": ...}` payload: the alternative tells the model a refusal
  went fine. An exception that escapes a tool is caught by Strands and
  handed to the model as `Error: {type} - {message}` built from the
  traceback, which is the other reason that module catches broadly.

- **`KeyboardInterrupt` is not an `Exception`.** A broad
  `except Exception` around a model call — which is what keeps a
  throttled turn from ending a call in `agents/cli.py` — does not catch
  Ctrl-C, and must not: the two mean opposite things (retry vs hang up).
  Both are handled separately there, and the test fake that stands in for
  a failing agent has to raise `BaseException`-typed values for the same
  reason. Worth remembering for the voice loop, which will have the same
  shape.

- **`Agent(model=None)` is not "no model"** — it constructs a
  `BedrockModel` on the Strands default id, with no credentials needed
  at construction time. Convenient for tests, and the reason the model
  choice can be left open (see Open Questions) without blocking
  anything.

- **`strands-agents` installed into `backend/.venv`** (1.54.0, plus
  ~35 transitive packages including `mcp`, `pydantic`, `opentelemetry`).
  Added to `backend/requirements.txt`, not `requirements-dev.txt`: the
  agents are runtime code. `backend/tools/` must still import neither it
  nor `bedrock_agentcore`, so a Lambda that only mutates data installs
  without them — `test_scheduling_agent.py` scans the package and fails
  if that stops being true.


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
- **`aws-cdk-lib` 2.266 ships real AgentCore Runtime constructs** —
  `aws_cdk.aws_bedrockagentcore`, both an L1 (`CfnRuntime`) and an L2
  (`Runtime`, with `AgentRuntimeArtifact.from_asset` building the
  container as an ordinary CDK asset and an auto-created execution role
  exposed as `.role`). Confirmed by importing and introspecting it in
  `backend/infra/.venv`, not assumed from memory — this is a very new
  service and worth re-checking the installed version's surface before
  assuming a construct exists or has the same shape. AgentCore Runtime
  names reject hyphens (letters/digits/underscores only); every other
  `ProjectConfig`-derived name uses them, which is why `agent_stack.py`
  needed its own `_runtime_name` rather than reusing `resource_name`.
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

- **This environment has no AWS credentials it can act with, and that
  is enforced two ways, not one.** `aws sts get-caller-identity` against
  the default profile fails with `NoCredentials`; a named profile
  (`Hanzala`) exists in `~/.aws/config` but invoking it — even a
  read-only identity check — is refused by this session's own auto-mode
  permission classifier before it reaches AWS at all. So Next Up #1's
  remaining half (building and pushing `agent_stack.py`'s container,
  `cdk deploy`) cannot be attempted from this environment even with
  `--profile Hanzala` supplied; it needs a session, or a person, with
  standing permission to take real AWS actions. Confirmed still true when
  the AgentCore Runtime CDK resources landed (below) — checked again
  rather than assumed, per this note's own advice — and worth checking
  again at the start of whatever session actually attempts the deploy.
  **This environment also has no Docker** (`docker version` fails,
  command not found), which blocks the same deploy a second, independent
  way even if credentials arrived: `AgentRuntimeArtifact.from_asset`'s
  image is only built and pushed during `cdk deploy`'s asset-publishing
  step, never at `synth`, so `cdk synth` was unaffected and is how this
  session verified the CDK resources at all.
- **`fastapi.testclient.TestClient`'s WebSocket support has no timeout
  of its own** (`starlette.testclient.WebSocketTestSession.receive`
  blocks on a cross-thread queue with nothing bounding the wait), unlike
  every other live-call suite in this package, which wraps its own
  `asyncio.wait_for`. `test_agentcore_app.py` reproduces the same safety
  net with a one-shot `concurrent.futures.ThreadPoolExecutor` around the
  whole synchronous drive function. Worth reusing rather than
  rediscovering if another suite ever drives a FastAPI WebSocket route
  this way.

- **Unlike the backend, this environment is not blocked on frontend
  work.** Node 22 / npm 11 are present, `npm install` and `npm run build`
  both reach the real npm registry with no proxy trouble
  (`frontend/`'s first build, Next Up #2a), and Playwright's Chromium
  could be downloaded and driven headless
  (`npx playwright install chromium`, ~300 MB, then a local `npm install
  playwright` — `chromium-cli` itself is not on this machine's `PATH`, so
  a small Playwright script under the scratchpad directory was the
  fallback the `run` skill's own playwright.md example names). That is
  how the dashboard login screen and its components were actually
  screenshotted rather than only type-checked. Worth reusing directly for
  any future frontend unit instead of re-discovering the same fallback:
  `npm run preview`/`npm run dev` in the background, poll the port, drive
  it from a `.mjs` script with `chromium.launch()`, screenshot, read the
  PNG back with the `Read` tool. Chromium's download persists at
  `C:\Users\<user>\AppData\Local\ms-playwright\`, so only a fresh
  `npm install playwright` in whatever scratchpad is current is needed
  next time, not a re-download.

- **Tailwind's opacity modifier does nothing on a bare `var()` arbitrary
  value.** `bg-[var(--state-success)]/15` compiles with no error and
  emits no CSS rule at all — Tailwind needs a color function it can
  inject an alpha channel into, and a raw custom-property reference isn't
  one. Silent, not a build failure, so it only surfaced by screenshotting
  and noticing a badge had no background. Fixed in `frontend/src/index.css`
  by precomputing light "wash" tint tokens instead
  (`--bg-state-success-wash` etc.) and a separate `rgba()`-valued
  `--overlay-scrim` for the one case (the modal backdrop) that has to
  stay translucent over arbitrary content rather than a flat mixed color.
  Worth checking for again if a future component reaches for `/NN` on a
  `var(--...)` class.
- **A `TypedEvent` (every Bidi event class) is a `dict` subclass**
  (`strands/types/_events.py`), which is what lets `agentcore_app.py`
  pass `websocket.send_json` directly as a `BidiAgent.run` output the
  same way the vendored sample does — no `.to_dict()`, no adapter. It
  also means an event serialises with a `type` field already spelled
  the way the vendored frontend's `websocket-presigned.ts` expects
  (`bidi_transcript_stream`, `bidi_connection_close`, ...): the wire
  protocol was designed to match, not merely made to work. Confirmed by
  reading one back through `json.dumps`, not assumed.
- **`BidiAgent.send` reconstructs a plain dict into a typed event itself**
  when it carries a `"type"` key (`agent.py` -> `send`), which is what
  lets `websocket.receive_json` feed it directly. Its own docstring
  example is wrong, though (`"bidirectional_text_input"`); the type
  string the code actually matches is `"bidi_text_input"` — used in
  `test_agentcore_app.py` and worth not copying the docstring's version
  if this is touched again.
