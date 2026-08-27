# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- Phase 2: business logic. The AWS sample is vendored as reference
  code, `backend/infra/` synthesises with the four DynamoDB tables
  defined (the other four stacks are still empty), and `backend/tools/`
  now exists as a tested foundation — item schema, status vocabularies,
  validation, table handles — with no tool functions on it yet. The
  clinic availability config shape is specified in `architecture.md`.
  `frontend/`, `backend/agents/`, `backend/lambda/`, and `seed/` do not
  exist yet.

## Current Goal

- Build the tool functions on the `backend/tools/` foundation, one at a
  time, starting with scheduling. The spec decision that blocked
  availability — the `Clinics` config shape — is now made and written
  into `architecture.md`, so `check_availability` is unblocked and is
  the next item. The agents, the KB bucket, the frontend adapted from
  the vendored AWS Nova Sonic sample, and the seed scripts follow.

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

## In Progress

- None.

## Next Up

The old item 1 ("implement `backend/tools/`") bundled five unrelated
tool families, which `ai-workflow-rules.md` -> When to Split Work
forbids in one step. Its foundation and the spec decision that blocked
the first tool are done (see Completed); the remaining tools are split
out below, one per unit.

1. `check_availability` in `backend/tools/scheduling.py` — read-only,
   queries the `by-start-time` index, subtracts appointments in
   `ACTIVE_APPOINTMENT_STATUSES` from the clinic's configured hours.
   Now unblocked: `architecture.md` -> Storage Model specifies the
   config shape and the slot-composition rule exactly. This is the tool
   that lands the nested config key names in `schema.py` and the
   `zoneinfo` local/UTC conversion.
2. `book_appointment` — plus the patient lookup-or-create by phone
   (the `by-phone` index) that booking needs to resolve a caller.
3. `reschedule_appointment` and `cancel_appointment` — the two writes
   that share the reschedule-history append.
4. Escalation tools — create, list open, mark resolved.
5. Build the Orchestrator agent + Scheduling/FAQ/Escalation
   sub-agents (Agent-as-Tool pattern), test locally with a text
   interface before wiring voice.
6. Wire Nova Sonic + BidiAgent voice on top of the working
   text-agent logic.
7. Deploy to AgentCore Runtime, verify voice session end-to-end.
8. Add the Knowledge Base source S3 bucket to the data stack
   (`kb/{clinic_id}/` prefixes) and the Bedrock Knowledge Base over it
   in the agent stack — these deploy together, so they are one unit.
   The FAQ query tool lands with them, since it has nothing to query
   until the KB exists.
9. Build the background Lambda + EventBridge schedule, reusing
   `backend/tools/` functions.
10. Build the staff dashboard (Cognito auth, appointment list,
    escalation queue).
11. Seed the two demo clinics (dental, cosmetic) with config,
    sample appointments, and FAQ documents for the Knowledge Base.
12. Architecture diagram, README, demo video, submission assets.

## Open Questions

- ~~**What is the shape of a clinic's `hours` and `services`
  config?**~~ **Resolved** — specified in `architecture.md` ->
  Storage Model, "Clinic availability config". All four sub-questions
  answered by the user: (a) per-weekday **list** of `{open, close}`
  intervals, so a lunch break or split shift is expressible;
  (b) whole-day `closures` entries `{date, label}`, no partial-day
  case; (c) per-service `duration_minutes`; (d) per-clinic
  `slot_minutes`. See Completed.

- **What does one entry in an appointment's `reminders` /
  `reschedule_history` list contain?** Deferred, not blocking: the
  attribute names exist, and the tools that write them (reminder
  dispatch, auto-reschedule) are the ones that decide the entry shape.
  Worth settling before the dashboard reads them, since
  `architecture.md` -> Storage Model derives the autonomous-action log
  from exactly these two lists plus `Escalations`.

- **AWS region**: defaulting to `us-east-1` in `architecture.md` —
  confirm before first deploy (Nova Sonic also available in
  us-west-2, eu-north-1, ap-northeast-1).
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
- **How does an unauthenticated patient reach the voice endpoint?**
  Surfaced by vendoring the sample. `architecture.md` → Auth and
  Access Model says patients are unauthenticated and Cognito is
  staff-only, but the sample connects to AgentCore via a
  **SigV4-presigned WebSocket** built from Cognito **identity-pool**
  credentials (`frontend/src/aws-credentials.ts`,
  `websocket-presigned.ts`). SigV4 requires *some* AWS credential, so
  "no auth" cannot mean "no credential". Options to decide before
  item 4 (voice wiring): (a) Cognito identity pool with
  **unauthenticated/guest** identities enabled — keeps the sample's
  presigning path intact, patients never see a login, still no
  patient accounts; (b) put our own Lambda/API Gateway WebSocket in
  front and let the backend hold the credentials
  (`voice_bridge.py`, already contemplated in `architecture.md` →
  System Boundaries); (c) require patient login — contradicts the
  spec, listed only for completeness. Leaning (a) as the smallest
  change from working sample code, but this needs an explicit
  decision and an `architecture.md` update, not a silent default.

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

- **Phone numbers are normalised at the boundary, not at read time.**
  The `by-phone` index is an equality match, so "555 123 4567" from
  speech and "+15551234567" from a seed script have to converge before
  either is stored, or the caller lookup silently misses.

## Session Notes

- **Second venv: `backend/.venv`**, on 3.12 like the infra one, with
  `boto3` + `pytest` from `backend/requirements-dev.txt` (runtime deps
  stay in `requirements.txt` so a Lambda bundle never ships the test
  runner). Run the suite as `.venv\Scripts\python.exe -m pytest` from
  `backend/` — `backend/pytest.ini` sets `pythonpath = .` so `tools`
  imports as a package. Two venvs rather than one because the CDK app
  pulls `aws-cdk-lib` and the tool layer must not.

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
