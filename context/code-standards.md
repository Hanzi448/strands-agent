# Code Standards

## General

- Keep modules small and single-purpose — one agent, one tool
  module, one Lambda handler per file.
- Fix root causes, do not layer workarounds; if a Strands or
  AgentCore quirk (e.g. Nova Sonic's experimental client swallowing
  credential errors) needs a workaround, document why in a comment
  and in `progress-tracker.md`, don't silently patch around it.
- Do not mix unrelated concerns — voice session handling, business
  logic, and infrastructure code stay in their own layers
  (`agents/`, `tools/`, `infra/`).
- Business logic (appointment rules, escalation rules) lives in
  `backend/tools/`, never inline inside an agent definition or a
  Lambda handler — both the live agent and the background job must
  call the same functions.

## Python (Backend / Agents)

- Python 3.12+ required (Nova Sonic / BidiAgent dependency).
- Type hints required on all function signatures; no bare `Any`
  without a comment explaining why.
- Every tool function (`@tool`) must validate its `clinic_id`
  argument is present and non-empty before doing anything else —
  this is the tenant-isolation boundary and it is not optional.
- Every tool function has a docstring describing what it does, its
  arguments, and what a Strands agent should expect back — this
  docstring is what the model sees, so write it for the model as
  much as for a human reader.
- No global mutable state shared across agent invocations; each
  session's state goes through AgentCore Memory or DynamoDB, not a
  Python-process-level variable.
- Validate all external input (patient speech-derived requests,
  dashboard API payloads) at the boundary before it reaches business
  logic — don't trust that the model always produces well-formed
  tool arguments.

## AWS CDK (Python)

- One `Stack` per concern (data, agent, api, automation, frontend) —
  do not put unrelated resources in the same stack.
- All resource names/IDs are derived from a single config
  (environment, project prefix) — no hardcoded ARNs or resource
  names duplicated across stacks.
- Every DynamoDB table, Lambda, and API route defined in CDK, not
  created manually in the console — the whole stack must be
  reproducible via `cdk deploy`.
- IAM policies are scoped to the specific resource and action needed
  (no `*` resource/action grants), especially for anything touching
  DynamoDB or SES.

## TypeScript / React (Frontend)

- Strict mode required throughout.
- Avoid `any` — use explicit interfaces for API responses and voice
  session state.
- Function components with hooks only; no class components.
- `voice/` components own the WebSocket/audio lifecycle;
  `dashboard/` components own REST calls to the dashboard API — do
  not cross-import session/audio logic into dashboard components or
  vice versa.
- Validate/parse unknown API responses before trusting their shape.

## Styling

- Use the CSS custom property tokens defined in `ui-context.md` —
  no hardcoded hex values in components.
- Follow the border radius scale defined in `ui-context.md`.
- Tailwind utility classes for layout/spacing; shadcn/ui for
  interactive primitives (buttons, dialogs, forms) rather than
  hand-rolled equivalents.

## API Routes (Lambda handlers)

- Validate and parse the request body/auth token before any business
  logic runs.
- Dashboard routes: enforce Cognito auth and clinic-scoping before
  any read or mutation.
- Return a consistent response shape: `{ data, error }` — never a
  bare object or bare array at the top level.

## Data and Storage

- Structured/queryable data (appointments, patients, clinic config,
  escalations) belongs in DynamoDB.
- Documents and large content (KB source files, frontend build
  artifacts) belong in S3, referenced by key — never inlined into
  DynamoDB items.
- Every DynamoDB item includes `clinic_id` as (part of) its key —
  no table or access pattern that omits it.

## File Organization

- `backend/agents/` — Strands agent + sub-agent definitions
- `backend/tools/` — shared business logic, the single source of
  truth for mutations
- `backend/lambda/` — Lambda entrypoints (background job, dashboard
  API, voice bridge)
- `backend/infra/` — CDK app and stacks
- `frontend/src/voice/` — patient voice UI
- `frontend/src/dashboard/` — staff dashboard UI
- `frontend/src/shared/` — shared components, tokens, API client
- `seed/` — demo clinic seed scripts and sample data
- `docs/` — architecture diagram, README, submission assets
