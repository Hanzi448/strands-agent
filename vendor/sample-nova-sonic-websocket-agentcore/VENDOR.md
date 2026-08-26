# Vendored: sample-nova-sonic-websocket-agentcore

This directory is a **pinned, unmodified copy** of an AWS sample repo,
vendored as the starting point for ClinicPilot's voice UI and
AgentCore deployment scaffold (`progress-tracker.md` → Next Up #1).

## Provenance

| Field | Value |
| ----- | ----- |
| Source | https://github.com/aws-samples/sample-nova-sonic-websocket-agentcore |
| Commit | `ef6e81b7965fc7922b0999f7c63685f72f92a44c` |
| Commit date | 2026-02-24 |
| Commit subject | `chore(frontend): refactor debug configuration to use .env.local` |
| Clone method | `git clone --depth 1`, nested `.git` removed |
| License | MIT No Attribution (MIT-0) — see `LICENSE` |

MIT-0 permits use, modification, and redistribution without an
attribution requirement, and is compatible with the hackathon's
MIT/Apache submission requirement. This file is retained as
attribution anyway, as a matter of provenance hygiene.

## Status: reference code, not final code

Per `ai-workflow-rules.md` → Protected Files, nothing in this
directory is edited in place. Code moves **out** of here into
`frontend/` and `backend/` one reviewed piece at a time, in later
tracker items. Treat this tree as read-only.

## What's here

| Path | Contents |
| ---- | -------- |
| `agent/strands_agent.py` | Strands `BidiAgent` + Nova Sonic agent, with demo calculator/weather tools |
| `agent/Dockerfile`, `requirements.txt` | AgentCore Runtime container build |
| `cdk/bin/app.ts`, `cdk/lib/*.ts` | CDK app — `infra-stack`, `auth-stack`, `runtime-stack`, `frontend-stack`, `build-trigger-stack` |
| `frontend/src/hooks/useVoiceAgent.ts` | Voice session lifecycle hook |
| `frontend/src/websocket-presigned.ts` | SigV4-presigned WebSocket connection to AgentCore |
| `frontend/src/audio-processor.worklet.js` | Mic capture / audio worklet |
| `frontend/src/components/` | `AudioVisualizer`, `VoiceControls`, `VoiceModeToggle` |
| `frontend/src/auth.ts`, `AuthModal.tsx`, `aws-credentials.ts` | Cognito sign-in + identity-pool credential exchange |
| `docs/` | Sample's own ARCHITECTURE / DEPLOYMENT / CUSTOMIZATION / TROUBLESHOOTING |
| `deploy-all.*`, `dev-local.*`, `scripts/` | One-command deploy and local-dev helpers |

## Reusability assessment vs. our specs

Recorded here because it determines how later items adapt this code.

**Directly reusable** — the audio/WebSocket plumbing is the reason we
vendored this: `audio-processor.worklet.js`, `websocket-presigned.ts`,
and `useVoiceAgent.ts` solve mic capture, barge-in, and presigned
AgentCore streaming, which are the fiddliest parts of the build.

**Reference-only, must be rewritten:**

- **CDK is TypeScript here; ours is Python** (`architecture.md` →
  Stack, `code-standards.md` → AWS CDK). The five `cdk/lib/*.ts`
  stacks are read as a reference for AgentCore wiring, then
  re-implemented in Python CDK. No TS CDK code ships in our stacks.
- **Stack decomposition differs.** Sample: Infrastructure / Auth /
  Runtime / Frontend (4). Ours: data / agent / api / automation /
  frontend (5). Not a 1:1 mapping.
- **Styling is AWS Cloudscape Design System**, not Tailwind +
  shadcn/ui (`ui-context.md` → Component Library). The voice screen
  needs genuine re-styling to the ClinicPilot token set, not a
  light adaptation. Only the *behavioral* hooks/worklet carry over;
  the presentational components largely do not.
- **The sample authenticates the voice user via Cognito**, which
  conflicts with our access model (`architecture.md` → Auth and
  Access Model: patients unauthenticated, Cognito for staff only).
  See the corresponding Open Question in `progress-tracker.md` —
  the presigned-WebSocket mechanism appears to *depend* on
  identity-pool credentials, so this is not a matter of deleting the
  login modal.
- **The sample's agent is single-agent with demo tools.** Our
  Orchestrator + Scheduling/FAQ/Escalation Agent-as-Tool structure
  (`architecture.md` → Invariants #2) replaces `strands_agent.py`
  wholesale; it is useful only as a BidiAgent configuration example.
