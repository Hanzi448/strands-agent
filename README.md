# ClinicPilot

A multi-tenant, voice-first AI front desk agent for dental and cosmetic
clinics, built for the AWS "Agents for Humans" hackathon (Strands Agents
SDK, Professional Agents track).

A patient talks to the agent through a browser microphone; it checks
availability, books or reschedules appointments, and answers clinic-specific
FAQs over a per-clinic knowledge base. Separately, a background job scans
upcoming appointments daily, sends reminders, and escalates to clinic staff
by email and a dashboard only when a real decision is needed. The
architecture is multi-tenant from the data layer up — every record is
scoped by `clinic_id` — demonstrated with two seeded clinics, one dental
and one cosmetic, with different hours, services, and FAQ content.

See [`context/project-overview.md`](context/project-overview.md) for the
full product spec and [`docs/architecture.md`](docs/architecture.md) for a
diagram of how the pieces fit together.

## Status

The full agent tree, tool layer, background job, staff dashboard, and CDK
infrastructure are built and verified offline (unit tests, `cdk synth`,
headless-browser screenshots). **The stack has not yet been deployed to a
live AWS account** — that needs Docker (to build/push the AgentCore
container image) and AWS credentials, neither of which the environment this
was built in has. See
[`context/progress-tracker.md`](context/progress-tracker.md) for the
authoritative, up-to-date state of every unit and what remains.

## Architecture

| Layer | Technology |
| --- | --- |
| Agent framework | Strands Agents SDK (Python) — Orchestrator + Scheduling/FAQ/Escalation sub-agents, Agent-as-Tool |
| Voice | Amazon Nova Sonic (via Bedrock) + Strands `BidiAgent` |
| Agent hosting | Bedrock AgentCore Runtime + AgentCore Memory |
| RAG | Bedrock Knowledge Base over Amazon S3 Vectors, one per clinic |
| Background automation | Amazon EventBridge Scheduler + AWS Lambda |
| API | Amazon API Gateway (REST + WebSocket) + Lambda |
| Database | Amazon DynamoDB, partitioned by `clinic_id` |
| Auth (staff only) | Amazon Cognito |
| Email escalation | Amazon SES (sandbox) |
| Frontend | Vite + React + TypeScript + Tailwind + shadcn/ui |
| Infrastructure | AWS CDK (Python), `us-east-1` |

Full stack detail, storage model, and the tenant-isolation invariants live
in [`context/architecture.md`](context/architecture.md).

## Repository layout

```
backend/
  agents/    Strands agent definitions (Orchestrator, Scheduling, FAQ,
             Escalation) + the voice/text/CLI/mic entry points
  tools/     Shared business logic — the single source of truth for every
             mutation, called by both the live agent and the background job
  lambda/    Lambda entrypoints (background scan, dashboard API)
  infra/     AWS CDK (Python) app — one stack per concern
  tests/     Pytest suite for tools/, agents/, lambda/, and infra parity
frontend/
  src/voice/      Patient voice UI
  src/dashboard/  Staff dashboard UI
  src/shared/     Shared components, design tokens, API client
seed/        Demo clinic seed scripts (config, sample appointments, FAQ docs)
docs/        Architecture diagram and other submission assets
context/     The spec this project is built against (read this first)
vendor/      Vendored AWS sample repo, kept as reference code
```

## Running it locally

### Backend tests

```
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

### Infrastructure (`cdk synth`, no AWS credentials required)

```
cd backend/infra
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
npx aws-cdk@2 synth --app ".venv\Scripts\python.exe app.py"
```

### Frontend

```
cd frontend
npm install
npm run build   # or: npm run dev
```

### Seed scripts (dry run, no AWS client touched)

```
cd backend
.venv\Scripts\python -m seed.run_seed --dry-run
```

Running any of these for real (a live text/voice call, a real `cdk deploy`,
a real seed run) needs AWS credentials and, for the deploy, Docker — see
`context/progress-tracker.md` → Session Notes for the exact commands and
why they're currently blocked in the build environment.

## Hackathon submission

- **Track**: AWS "Agents for Humans", Strands Agents SDK, Professional
  Agents track.
- **License**: MIT — see [`LICENSE`](LICENSE). (`vendor/` keeps the
  original MIT-0 license of the code vendored into it.)
- **Architecture diagram**: [`docs/architecture.md`](docs/architecture.md).
- **Demo video / live demo link**: pending deployment — see Status above.

## Context files

This project is built against a fixed spec, read in this order every
session:

1. [`context/progress-tracker.md`](context/progress-tracker.md) — current
   state and what's next.
2. [`context/project-overview.md`](context/project-overview.md),
   [`context/architecture.md`](context/architecture.md),
   [`context/code-standards.md`](context/code-standards.md),
   [`context/ui-context.md`](context/ui-context.md).
3. [`context/ai-workflow-rules.md`](context/ai-workflow-rules.md) — how
   work is scoped and split.
