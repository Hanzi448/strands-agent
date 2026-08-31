# Architecture Diagram

Source of truth for the design decisions behind this diagram is
[`context/architecture.md`](../context/architecture.md). This page is the
visual submission asset; if the two ever disagree, the context file wins and
this one should be updated to match.

## System diagram

```mermaid
flowchart TB
    subgraph Patient["Patient (browser, no login)"]
        VoiceUI["Voice UI\nfrontend/src/voice/"]
    end

    subgraph Staff["Staff (browser, Cognito login)"]
        DashUI["Dashboard UI\nfrontend/src/dashboard/"]
    end

    GuestPool["Cognito Identity Pool\n(guest, invoke-only role)"]
    StaffPool["Cognito User Pool\n(one account per clinic)"]

    VoiceUI -- "SigV4-signed WebSocket" --> GuestPool
    GuestPool --> AgentCore
    DashUI -- "Cognito-authorizer token" --> StaffPool
    DashUI -- "REST" --> ApiGw["API Gateway (REST)"]

    subgraph Runtime["Bedrock AgentCore Runtime"]
        AgentCore["agentcore_app.py\n/ws"]
        Orchestrator["Orchestrator\n(BidiAgent over Nova Sonic)"]
        Scheduling["Scheduling sub-agent"]
        FAQ["FAQ sub-agent"]
        Escalation["Escalation sub-agent"]
        AgentCore --> Orchestrator
        Orchestrator -- "Agent-as-Tool" --> Scheduling
        Orchestrator -- "Agent-as-Tool" --> FAQ
        Orchestrator -- "Agent-as-Tool" --> Escalation
    end

    NovaSonic["Amazon Nova Sonic\n(speech-to-speech)"]
    Orchestrator <--> NovaSonic

    Tools["backend/tools/\n(scheduling, booking, patients,\nappointments, escalations, faq)"]
    Scheduling --> Tools
    FAQ --> Tools
    Escalation --> Tools

    KB["Bedrock Knowledge Base\n(one per clinic)"]
    S3Vectors["S3 Vectors\n(embeddings)"]
    KBSource["S3: kb/{clinic_id}/...\n(source docs)"]
    Tools -- "query_faq" --> KB
    KB --> S3Vectors
    KBSource --> KB

    DDB[("DynamoDB\nClinics / Patients /\nAppointments / Escalations")]
    Tools --> DDB

    Memory["AgentCore Memory\n(per-patient session state)"]
    Orchestrator --> Memory

    ApiGw -- "Cognito authorizer" --> DashLambda["Lambda\ndashboard_api.py"]
    DashLambda --> DDB

    Scheduler["EventBridge Scheduler\n(one schedule per clinic)"]
    BgLambda["Lambda\nbackground_scan.py"]
    Scheduler -- "{clinic_id}" --> BgLambda
    BgLambda -- "run_daily_scan()" --> Tools
    BgLambda -- "reminder email" --> SES["Amazon SES\n(sandboxed)"]
    SES --> StaffInbox["Staff inbox\n(verified Gmail, demo)"]

    DDB -.-> DashUI
```

## Reading the diagram

- **Everything is `clinic_id`-scoped.** DynamoDB partition keys, the
  Knowledge Base chosen per clinic, and the guest role's single permission
  (invoke the AgentCore runtime, nothing else) are the three structural
  reasons no request can cross a clinic boundary — see
  `context/architecture.md` → Invariants.
- **Sub-agents are never reachable directly.** The only caller of
  Scheduling, FAQ, and Escalation is the Orchestrator, wired in as
  Strands Agent-as-Tool. Nothing in the frontend or the API layer holds a
  reference to a sub-agent.
- **`backend/tools/` is the single source of truth for mutations.** Both
  the live Orchestrator (via its sub-agents) and the background Lambda
  (`background_scan.py`, via `automation.py`) call into this same layer —
  there is no second copy of the booking or escalation rules.
- **Two independent trust boundaries reach AWS**: a patient never
  authenticates and is issued a Cognito guest credential scoped to
  invoking the agent only; staff authenticate against a separate Cognito
  user pool whose claims gate every dashboard API route.

## Status

This diagram describes the architecture as designed and as built in code
and CDK (`backend/infra/`, verified via `cdk synth`). The stack has not yet
been deployed to a live AWS account from this environment — see
`context/progress-tracker.md` → Next Up and Session Notes for why (no
Docker, no usable AWS credentials, here specifically).
