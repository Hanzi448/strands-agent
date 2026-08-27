# ClinicPilot (working name — rename freely)

## Overview

ClinicPilot is a multi-tenant, voice-first AI front desk agent for
dental and cosmetic clinics, built for the AWS "Agents for Humans"
hackathon (Strands Agents SDK, Professional Agents track). A patient
talks to the agent through a browser microphone; the agent checks
availability, books or reschedules appointments, and answers clinic
FAQs using retrieval-augmented generation scoped to that specific
clinic. Separately, the agent runs autonomously in the background —
scanning upcoming appointments daily, sending reminders, attempting
reschedules for likely no-shows, and escalating to clinic staff by
email and a staff dashboard only when a real decision is needed. The
architecture is multi-tenant from the data layer up (every record is
scoped by `clinic_id`), demonstrated in the hackathon submission with
two seeded clinics — one dental, one cosmetic — to prove the
SaaS-capable claim without building a full tenant-onboarding system.

## Goals

1. A patient can complete a full voice conversation (check
   availability, book an appointment, ask a clinic-specific FAQ) with
   the deployed agent, browser-only, no phone line required.
2. The same deployed agent correctly serves two different clinics
   (dental and cosmetic) with different hours, services, and FAQ
   content, proving the multi-tenant architecture.
3. The agent takes autonomous action on a schedule (not just in
   response to a user) and only escalates to a human when the
   situation genuinely requires a judgment call.
4. The full stack (voice agent, background automation, staff
   dashboard) is deployed on AWS via Bedrock AgentCore, is publicly
   reachable for a live demo link, and is fully reproducible via CDK.

## Core User Flow

### Patient (voice)

1. Patient opens the web app, selects/enters their clinic context
   (demo: dental or cosmetic), and starts a voice session.
2. Orchestrator agent greets the patient and determines intent
   (book, reschedule, ask a question, other).
3. Orchestrator routes to the relevant sub-agent tool (Scheduling or
   FAQ) to fulfill the request against that clinic's data.
4. If the request can't be safely resolved by the agent (e.g.
   conflicting appointment, refund question), the Escalation
   sub-agent is invoked and the session ends with a clear
   "staff will follow up" message to the patient.
5. AgentCore Memory persists enough session state that a returning
   patient's context carries across calls.

### Staff (dashboard)

1. Staff logs into the dashboard (Cognito-authenticated).
2. Dashboard shows: today's appointments, any auto-sent reminders,
   any auto-attempted reschedules, and any items flagged by the
   agent for a decision.
3. Staff can view an emailed escalation and mark it resolved.

### Background (autonomous)

1. A scheduled job runs daily per clinic.
2. For each upcoming appointment, the agent decides: send a
   reminder, attempt an automatic reschedule (for a
   likely-no-show pattern), or flag it for staff — and acts on that
   decision without being prompted by a person.

## Features

### Patient-Facing Voice Agent

- Real-time voice conversation (Amazon Nova Sonic + Strands
  BidiAgent)
- Check appointment availability
- Book a new appointment
- Reschedule or cancel an existing appointment
- Answer clinic-specific FAQs via RAG (pricing, prep instructions,
  policies — content differs per clinic)

### Autonomous Background Agent

- Daily scan of upcoming appointments per clinic
- Automatic reminder sending
- Automatic reschedule attempts for likely no-shows
- Escalation to staff (email + dashboard) when a decision is needed,
  not a routine action

### Staff Dashboard

- Cognito-authenticated login (one account per clinic for the demo)
- View today's/upcoming appointments
- View agent-flagged escalations and mark them resolved
- View a simple log of autonomous actions the agent has taken

## Scope

### In Scope

- Two seeded demo clinics (dental, cosmetic) with distinct config,
  hours, services, and FAQ knowledge base content
- Multi-agent orchestration via Strands (Agent-as-Tool pattern):
  Orchestrator, Scheduling, FAQ, Escalation
- Browser-based voice interface (no telephony)
- AgentCore Runtime + AgentCore Memory deployment
- EventBridge + Lambda autonomous background loop
- DynamoDB data layer, partitioned by `clinic_id`
- Bedrock Knowledge Base per clinic for FAQ RAG
- SES email escalation (sandboxed to a personal Gmail for the demo)
- Cognito-gated staff dashboard
- CDK (Python) infrastructure, fully reproducible

### Out of Scope

- Real telephone number / Amazon Connect integration
- Self-serve clinic onboarding or a tenant admin/signup portal
- Payment processing or billing
- Multi-language support (English only for the demo)
- Native mobile app

## Success Criteria

1. A full voice conversation — availability check, booking, one
   FAQ question — completes successfully against a deployed agent.
2. The same deployed agent gives correct, different answers for
   the dental clinic vs. the cosmetic clinic in the same demo.
3. The background job successfully sends at least one reminder and
   one staff escalation (email + dashboard) without a human
   triggering it.
4. Staff can log into the dashboard and see agent-flagged items.
5. `cdk deploy` reproduces the full stack from a clean AWS account
   (aside from manually-verified SES identity).
