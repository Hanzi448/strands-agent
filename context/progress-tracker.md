# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- Phase 1: project skeleton. The AWS sample is vendored as reference
  code; our own `backend/` and `frontend/` trees do not exist yet.

## Current Goal

- Stand up the project skeleton: CDK app with empty stacks, backend
  package structure, frontend adapted from the vendored AWS Nova Sonic
  sample, seed script stubs.

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

## In Progress

- None yet.

## Next Up

1. Stand up `backend/infra/` CDK app with stack skeletons
   (data, agent, api, automation, frontend) — no resources yet,
   just the structure.
2. Define DynamoDB table schemas (`Clinics`, `Appointments`,
   `Patients`, `Escalations`) in the data stack.
3. Implement `backend/tools/` business logic functions
   (availability check, booking, reschedule, FAQ query, escalate)
   against the DynamoDB tables.
4. Build the Orchestrator agent + Scheduling/FAQ/Escalation
   sub-agents (Agent-as-Tool pattern), test locally with a text
   interface before wiring voice.
5. Wire Nova Sonic + BidiAgent voice on top of the working
   text-agent logic.
6. Deploy to AgentCore Runtime, verify voice session end-to-end.
7. Build the background Lambda + EventBridge schedule, reusing
   `backend/tools/` functions.
8. Build the staff dashboard (Cognito auth, appointment list,
   escalation queue).
9. Seed the two demo clinics (dental, cosmetic) with config,
   sample appointments, and FAQ documents for the Knowledge Base.
10. Architecture diagram, README, demo video, submission assets.

## Open Questions

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
  item 5 (voice wiring): (a) Cognito identity pool with
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
- **Sample's TypeScript CDK is reference-only; our CDK stays Python**
  — the sample ships five TS stacks. Re-implementing in Python CDK
  costs more than copying them, but `architecture.md` → Stack and
  `code-standards.md` both mandate Python CDK for a single-language
  deployment story, and mixing two CDK toolchains in one repo would
  be worse. The TS stacks are read as AgentCore wiring references.

## Session Notes

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
  budgeting for when item 5 comes up.
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
