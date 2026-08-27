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
  duplicate logic.
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

- **DynamoDB**:
  - `Clinics` — clinic config: name, type (dental/cosmetic), hours,
    services, contact info. Partition key `clinic_id`.
  - `Appointments` — partition key `clinic_id`, sort key
    `appointment_id`. Holds patient reference, time, status,
    reminder/reschedule history.
  - `Patients` — partition key `clinic_id`, sort key `patient_id`.
    Minimal demo profile (name, contact).
  - `Escalations` — partition key `clinic_id`, sort key
    `escalation_id`. What was flagged, why, resolved status.
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
