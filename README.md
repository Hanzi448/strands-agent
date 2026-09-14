# ClinicPilot

**The AI receptionist that answers every call and lands every booking.**

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

- **Live demo**: https://d16aixkgixx5o6.cloudfront.net
- **Demo video**: recorded alongside the live demo (see the submission form).
- **Pitch sheet**: [`docs/demo-pitch.html`](docs/demo-pitch.html) — the
  problem, the audience, and why it matters, printable to PDF.
- **Architecture diagram**: [`docs/architecture.md`](docs/architecture.md).

## Status: deployed and live

The full stack is deployed to a live AWS account (`us-east-1`) and was
verified end to end: agent runtime on Bedrock AgentCore, Nova Sonic voice,
per-clinic knowledge bases, AgentCore Memory, DynamoDB, Cognito staff
auth, SES escalation email, EventBridge daily scans, and the CloudFront
frontend. The staff dashboard shows the seeded clinics' appointments and
escalations; the patient voice UI takes real calls.

Two demo tenants are seeded — same login password for both: `ClinicPilot123!`

| Clinic | Staff dashboard login | Patient voice UI |
| --- | --- | --- |
| Bright Smile Dental | `staff+clinic-dental@clinicpilot.demo` / `ClinicPilot123!` | [Voice link](https://d16aixkgixx5o6.cloudfront.net/#/voice) |
| Lumiere Aesthetics | `staff+clinic-cosmetic@clinicpilot.demo` / `ClinicPilot123!` | [Voice link](https://d16aixkgixx5o6.cloudfront.net/#/voice) |

**Try the full loop as a judge:**

1. Open the **patient voice UI** ([#/voice](https://d16aixkgixx5o6.cloudfront.net/#/voice))
   — no login needed. Allow microphone access, pick a clinic, and talk
   to the agent; ask "do you do whitening?" or try to book an
   appointment.
2. Open the **staff dashboard**
   ([https://d16aixkgixx5o6.cloudfront.net](https://d16aixkgixx5o6.cloudfront.net))
   and log in with a clinic's email + password from the table.
3. You'll see the voice call's result on the dashboard: appointments
   land on the calendar, and anything the agent escalated appears in the
   escalation queue (staff also get an email the moment it's created).
   The Settings tab shows the schedule configuration the voice agent
   books against.

> **Demo note**: the deployment runs on an AWS account with default
> on-demand Bedrock quotas. Under heavy same-day use the live link may
> rate-limit; the agent degrades gracefully (it says so) rather than
> failing silently. Deploying your own stack (below) gets a fresh quota.

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

Patient speaks → Nova Sonic real-time voice → Orchestrator agent routes to
a specialist sub-agent (Scheduling / FAQ / Escalation) → tools read &
write the clinic's real data → agent answers by voice, staff see the
result instantly. Sub-agents are only ever called as tools by the
Orchestrator, and all business logic lives in one shared tools layer used
by both the live agent and the background job — so tenancy isolation is an
invariant, not a feature flag.

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
docs/        Architecture diagram, pitch sheet, design docs
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

Run from the **repository root**, not `backend/` — `seed/` lives next to
`backend/`, not inside it, and its `__init__.py` puts `backend/` on
`sys.path` itself once it's found:

```
backend\.venv\Scripts\python -m seed.run_seed --dry-run
```

## Deploying your own stack

Prerequisites: AWS credentials for the target account, Docker running
(for the AgentCore container image build/push), Node.js, and Python 3.11+.

The SPA reads its config (`VITE_*`) from `frontend/.env` at **build**
time — see `frontend/.env.example` for the mapping from each variable
to the stack output it comes from. So the deploy order is:

1. `cdk deploy` the data / agent / api / automation stacks
   (from `backend/infra`; the agent stack needs Docker running).
2. `python -m seed.run_seed` to seed the two demo clinics (set
   `CLINICPILOT_STAFF_DEMO_PASSWORD` first — it becomes the staff
   dashboard login).
3. Copy the stack outputs into `frontend/.env`
   (`DashboardApiUrl`, `StaffUserPoolId`, `StaffUserPoolClientId`,
   `PatientGuestIdentityPoolId`, `PatientGuestRoleArn`,
   `AgentRuntimeArn`, and the region).
4. `npm run build` in `frontend/`.
5. `cdk deploy ClinicPilot-Dev-Frontend` — this uploads
   `frontend/dist/` to the private S3 bucket behind CloudFront and
   invalidates the cache. The stack's `FrontendUrl` output is the
   public demo link.

A rebuild + redeploy of the frontend is just steps 4 and 5.

## License

MIT — see [`LICENSE`](LICENSE). (`vendor/` keeps the original MIT-0
license of the code vendored into it.)

## Hackathon submission

- **Track**: AWS "Agents for Humans", Strands Agents SDK, Professional
  Agents track.
- **Public repo**: this repository (MIT, license visible in the repo
  About section).
- **Demo video**: recorded — live voice call, staff dashboard
  (appointments, escalations, settings), and the booking flow.
- **Live demo**: https://d16aixkgixx5o6.cloudfront.net (credentials above).
- **Pitch sheet**: [`docs/demo-pitch.html`](docs/demo-pitch.html).
- **Architecture diagram**: [`docs/architecture.md`](docs/architecture.md).
