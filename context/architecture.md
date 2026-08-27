# Architecture Context

## Stack

| Layer                  | Technology                                              | Role                                                            |
| ----------------------- | -------------------------------------------------------- | ---------------------------------------------------------------- |
| Agent Framework         | Strands Agents SDK (Python)                              | Orchestrator + sub-agents, tool definitions                     |
| Voice Model             | Amazon Nova Sonic (via Bedrock)                          | Speech-to-speech, real-time voice understanding + generation    |
| Voice Streaming         | Strands `BidiAgent`                                      | Bidirectional WebSocket audio streaming to Nova Sonic            |
| Agent Hosting           | Bedrock AgentCore Runtime                                | Deploys and runs the agent(s)                                    |
| Session Continuity      | Bedrock AgentCore Memory                                 | Per-patient conversation state across calls                      |
| Orchestration Pattern   | Strands Agent-as-Tool                                    | Scheduling, FAQ, Escalation sub-agents wrapped as in-process tools, invoked by the Orchestrator agent |
| RAG / Knowledge Base    | Amazon Bedrock Knowledge Base (S3-backed)                | Per-clinic FAQ retrieval, filtered/scoped by `clinic_id`         |
| Background Automation   | Amazon EventBridge (Scheduler) + AWS Lambda              | Daily autonomous appointment scan and action                     |
| API Layer               | Amazon API Gateway (REST + WebSocket) + Lambda           | Dashboard API, voice session bridge                              |
| Database                | Amazon DynamoDB                                          | Clinics, patients, appointments, escalations — all `clinic_id`-partitioned |
| File/Doc Storage        | Amazon S3                                                | Knowledge base source docs, frontend static build                |
| Auth (staff only)       | Amazon Cognito                                            | Staff dashboard login, one user pool, one demo account per clinic |
| Email Escalation        | Amazon SES (sandbox mode)                                | Staff notification email, sandboxed to a verified personal Gmail |
| Frontend                | Vite + React + TypeScript + Tailwind + shadcn/ui         | Voice UI (forked/adapted from AWS's `sample-nova-sonic-websocket-agentcore`) + staff dashboard |
| Frontend Hosting        | Amazon S3 + CloudFront                                    | Static SPA hosting, served over HTTPS                            |
| Infrastructure as Code  | AWS CDK (Python)                                          | All AWS resources defined and deployed as code                   |
| Region                  | `us-east-1` (default — confirm before first deploy; Nova Sonic is also available in us-west-2, eu-north-1, ap-northeast-1) | Single region for all resources |

Everything in this stack is serverless/managed — no EC2 instances or
containers to operate. AgentCore Runtime, Lambda, DynamoDB,
EventBridge, Bedrock, and SES are all pay-per-use managed services.

## System Boundaries

- `backend/agents/` — Strands agent definitions: `orchestrator.py`
  (patient-facing voice agent), `scheduling_agent.py`, `faq_agent.py`,
  `escalation_agent.py`. Each sub-agent is wrapped as a `@tool` and
  registered on the orchestrator — sub-agents are never invoked
  directly by the client.
- `backend/tools/` — Shared business-logic functions used by the
  agents (appointment CRUD, KB query, notification dispatch). These
  are the **single source of truth** for mutating data — both the
  live agent and the background Lambda call into this layer, never
  duplicate logic. Its foundation modules: `schema.py` (item attribute
  names, status vocabularies, key/timestamp encodings — see Storage
  Model), `validation.py` (the boundary checks every tool runs first,
  including the `clinic_id` guard), `dynamo.py` (table handles,
  resolved from environment variables the CDK sets), `errors.py` (the
  exception vocabulary tools raise). Nothing here imports Strands or
  AgentCore, so the layer stays callable from a Lambda, a seed script,
  or a test with no agent runtime present.
- `backend/tests/` — Pytest suite for `backend/tools/`. Run from
  `backend/` (`pytest.ini` puts the package on the path); dependencies
  in `backend/requirements-dev.txt`. Not a runtime boundary, listed
  here because it is the verification step for every tool unit.
- `backend/lambda/` — Lambda handlers: `background_scan.py`
  (EventBridge-triggered autonomous loop), `dashboard_api.py`
  (Cognito-protected REST handlers for the staff dashboard),
  `voice_bridge.py` (WebSocket handler bridging the frontend to
  AgentCore Runtime, if not connecting directly).
- `backend/infra/` — AWS CDK (Python) app. One stack per concern:
  `data_stack.py` (DynamoDB, S3), `agent_stack.py` (AgentCore,
  Bedrock KB), `api_stack.py` (API Gateway, Lambda, Cognito),
  `automation_stack.py` (EventBridge, background Lambda),
  `frontend_stack.py` (S3 + CloudFront).
- `frontend/src/voice/` — Voice session UI (mic capture, audio
  playback, WebSocket connection to the agent). Adapted from the AWS
  sample repo.
- `frontend/src/dashboard/` — Staff dashboard UI (Cognito login,
  appointment list, escalation queue).
- `frontend/src/shared/` — Shared components, design tokens, API
  client.
- `seed/` — Scripts to seed the two demo clinics (config, sample
  appointments, sample FAQ documents for the Knowledge Base).
- `docs/` — Architecture diagram, README, submission assets.

## Storage Model

- **DynamoDB** (defined in `backend/infra/data_stack.py`; on-demand
  billing, all keys string-typed, all timestamps ISO-8601 UTC):
  - `Clinics` — clinic config: name, type (dental/cosmetic), timezone,
    hours, closures, services, slot granularity, contact info (the
    availability fields are specified in full below). Partition key
    `clinic_id`. No secondary index: a clinic is only ever fetched by
    its own id.
  - `Appointments` — partition key `clinic_id`, sort key
    `appointment_id`. Holds patient reference, time, status,
    reminder/reschedule history. Two indexes:
    - `by-start-time` (`clinic_id` / `starts_at`) — availability
      checks, the dashboard day view, and the daily background scan
      are all "this clinic, this time range".
    - `by-patient` (`clinic_patient` / `starts_at`) — the caller's
      own appointments, time-ordered, for reschedule and cancel.
      `clinic_patient` is a composite `{clinic_id}#{patient_id}`
      attribute written by the tool layer, so the index key is itself
      clinic-scoped (see Invariants #1); a `patient_id`-only index
      would be a queryable cross-clinic path and is not allowed.
  - `Patients` — partition key `clinic_id`, sort key `patient_id`.
    Minimal demo profile (name, contact). One index:
    - `by-phone` (`clinic_id` / `phone`) — a voice caller identifies
      themselves by phone number, not by id.
  - `Escalations` — partition key `clinic_id`, sort key
    `escalation_id`. What was flagged, why, resolved status. One index:
    - `by-created-at` (`clinic_id` / `created_at`) — the dashboard
      escalation queue, newest first. `status` is a read filter rather
      than a key: the queue is small enough that filtering beats
      maintaining a composite status key.
  - Every index projects ALL attributes — these tables are small and
    the tool layer reads whole items.
  - Non-key attribute names and the appointment/escalation status
    vocabularies are fixed in `backend/tools/schema.py`, not here;
    DynamoDB only enforces the keys above. That module is also where
    the timestamp encoding is fixed — one format
    (`2026-08-27T14:30:00Z`: UTC, second precision, `Z` suffix),
    because `starts_at` and `created_at` are sort keys and DynamoDB
    compares strings bytewise, so mixed offsets or precisions would
    order items wrongly with no error. Appointment statuses:
    `scheduled`, `cancelled`, `completed`, `no_show` — a reschedule is
    not a status, it moves `starts_at` and appends to the appointment's
    reschedule history. Escalation statuses: `open`, `resolved`.
    The key attribute and index names are necessarily written in both
    `schema.py` and `data_stack.py` (business logic must not depend on
    `aws-cdk-lib`); `backend/tests/test_schema_matches_infra.py` fails
    if the two ever disagree.
  - **Clinic availability config** — four `Clinics` attributes carry every
    rule the availability calculation needs: `timezone`, `hours`,
    `closures`, `services`, plus `slot_minutes`. Nothing else may be
    consulted to decide whether a time is bookable, so a clinic's
    behaviour is fully described by its own item.
    - `timezone` — IANA name (`"Europe/London"`). `hours` and `closures`
      are expressed in **clinic-local wall-clock time**; every stored
      timestamp stays UTC (`starts_at`, `ends_at`, `created_at`). The
      conversion happens inside the scheduling tools and nowhere else —
      no other layer may hold a local-time value.
    - `hours` — map of weekday key (`mon`,`tue`,`wed`,`thu`,`fri`,`sat`,
      `sun`) to a **list of open intervals**, each `{"open": "HH:MM",
      "close": "HH:MM"}` in 24-hour local time. All seven keys are
      always present; an empty list means closed that day. Intervals are
      non-overlapping, ascending, and `close` is strictly after `open`.
      A list (rather than one open/close pair) is what expresses a lunch
      break or a split shift, at no cost to the availability loop, which
      walks intervals either way.
    - `closures` — list of `{"date": "YYYY-MM-DD", "label": str}`,
      whole-day only. A matching date removes the day entirely regardless
      of `hours`. Partial-day closures are deliberately out of scope:
      they multiply branches in the availability logic for a case the
      demo does not need.
    - `services` — list of `{"id": str, "name": str,
      "duration_minutes": int}`. `id` is the stable machine key written
      to an appointment's `service` attribute and never spoken; `name` is
      what the agent says and hears. `duration_minutes` is a positive
      integer and is what sets an appointment's `ends_at` — so a 60-minute
      consult blocks a different span than a 15-minute check-up. A
      booking request naming a service not in this list is a validation
      error, not a default.
    - `slot_minutes` — positive integer, the interval the *start times*
      of candidate slots are offered on, counted from each opening
      interval's `open`. Per clinic rather than global: it is a second
      axis on which the two demo clinics genuinely differ.
    - **How the pieces compose**: candidate starts are generated on the
      `slot_minutes` grid from each interval's `open`; a candidate is
      offered only if `start + duration_minutes` fits **entirely within
      that same opening interval** (an appointment never spans a lunch
      break or closing time) and overlaps no existing appointment in
      `ACTIVE_APPOINTMENT_STATUSES`. `duration_minutes` therefore need
      not be a multiple of `slot_minutes`.
    - The attribute *names* are fixed in `backend/tools/schema.py`
      (`ClinicAttrs`); the nested key names above land there as constants
      with the first tool that reads them, per `code-standards.md`
      (attribute names are never inline literals).
    - **The two demo clinics differ in all four**, which is how
      `project-overview.md` Goal 2 is demonstrated rather than asserted:
      the dental clinic runs `mon`–`fri` `09:00`–`13:00` and
      `14:00`–`17:30` (a real lunch break) plus a short `sat` morning,
      `slot_minutes` 15, short services (`checkup` 15, `cleaning` 30);
      the cosmetic clinic runs `tue`–`sat` `10:00`–`18:00` unbroken,
      `slot_minutes` 30, long services (`consult` 60, `treatment` 90).
      Any availability bug that assumes one clinic's rules shows up
      immediately on the other. The seed scripts (`seed/`) write exactly
      these shapes.
  - The autonomous-action log the staff dashboard shows is derived from
    appointment reminder/reschedule history plus `Escalations` — there
    is no separate actions table.
  - Tables are destroyed with the stack in non-`prod` environments and
    retained (with point-in-time recovery and deletion protection) in
    `prod`.
- **S3**:
  - Knowledge base source documents, one prefix per clinic
    (`kb/{clinic_id}/...`), feeding the per-clinic Bedrock Knowledge
    Base.
  - Frontend static build artifacts (served via CloudFront).
- **AgentCore Memory**: per-patient conversation state/history across
  voice sessions — not duplicated in DynamoDB.

## Auth and Access Model

- **Patients**: no authentication. The voice endpoint is publicly
  reachable for the demo; the active clinic context is selected at
  session start (demo picker: dental or cosmetic) rather than via
  patient login.
- **Staff**: authenticate via Amazon Cognito. One user pool, one
  demo account seeded per clinic. Dashboard API routes require a
  valid Cognito-issued token.
- **Tenant isolation**: every tool function requires `clinic_id` as
  an explicit argument (derived from the active session, never
  inferred or optional) and every DynamoDB query/Bedrock KB query is
  scoped to that `clinic_id`. There is no code path that queries
  across clinics.

## Invariants

1. All data access — reads and writes — must be scoped by
   `clinic_id`. No query, mutation, or KB retrieval may span more
   than one clinic.
2. Sub-agents (Scheduling, FAQ, Escalation) are invoked only as tools
   by the Orchestrator agent. They are never exposed directly to the
   frontend or callable outside the agent process.
3. The background Lambda (`background_scan.py`) must call the same
   `backend/tools/` functions the live voice agent uses for any
   mutation — it must never duplicate booking/rescheduling logic.
4. Raw audio is never persisted. Only transcripts/session state (via
   AgentCore Memory) and structured appointment/escalation data (via
   DynamoDB) are stored.
5. Staff-facing API routes require Cognito authentication and are
   scoped to the authenticated staff member's clinic. The
   patient-facing voice endpoint requires no authentication.
6. The agent may only take an autonomous action (reminder, auto-
   reschedule) within rules defined in `backend/tools/` — anything
   outside those rules must go through `escalation_agent` instead of
   being improvised by the model.
