# AI Workflow Rules

## Approach

Build this project incrementally using a spec-driven workflow.
`project-overview.md`, `architecture.md`, `code-standards.md`, and
`ui-context.md` define what to build and how to build it;
`progress-tracker.md` defines the current state. Always implement
against these specs — do not infer or invent product behavior,
agent tool names, data shapes, or UI patterns not defined in these
files. If something needed isn't defined here, stop and add it as an
open question rather than guessing.

## Scoping Rules

- Work on one feature unit at a time (e.g. "implement the
  `book_appointment` tool," not "build scheduling and FAQ and the
  dashboard").
- Prefer small, verifiable increments over large speculative changes
  — this project has a hard 2-3 week deadline, so unverified,
  half-finished breadth is worse than a smaller set of fully working
  units.
- Do not combine unrelated system boundaries in a single
  implementation step (see `architecture.md` → System Boundaries).

## When to Split Work

Split an implementation step if it combines:

- Agent/tool logic (`backend/agents/`, `backend/tools/`) and
  infrastructure changes (`backend/infra/`) — implement the
  Python logic and its CDK deployment as separate steps.
- Backend changes and frontend changes (voice UI or dashboard) —
  these are separate steps even when they're for the same feature.
- Multiple unrelated tools or agents (e.g. don't implement
  `book_appointment` and `answer_faq` in the same step).
- Behavior not clearly defined in `project-overview.md` or
  `architecture.md` — e.g. exact no-show/reschedule heuristics for
  the background job, if not yet specified, is its own
  spec-then-implement step, not something to invent inline.

If a change cannot be verified end to end quickly (a tool tested
locally, a Lambda tested with a sample event, a UI change checked in
the browser), the scope is too broad — split it.

## Handling Missing Requirements

- Do not invent product behavior not defined in the context files
  (e.g. don't invent new escalation rules, new clinic config fields,
  or new UI screens beyond what `ui-context.md` and
  `project-overview.md` describe).
- If a requirement is ambiguous (e.g. exact no-show detection logic,
  exact reminder timing), resolve it in `project-overview.md` or
  `architecture.md` before implementing — don't pick a default
  silently.
- If a requirement is missing, add it as an open question in
  `progress-tracker.md` before continuing.

## Protected Files

Do not modify the following unless explicitly instructed:

- `frontend/src/shared/components/ui/*` — shadcn-generated UI
  library components (regenerate via the shadcn CLI, don't hand-edit)
- Anything under a vendored/forked copy of
  `sample-nova-sonic-websocket-agentcore` until it has been
  reviewed and intentionally adapted — treat the initial fork as
  reference code, not final code, and call out changes explicitly
  rather than silently rewriting it wholesale
- `backend/infra/cdk.out/` and other CDK-generated output
- Any third-party library internals (`node_modules`, installed
  Python packages)

## Keeping Docs in Sync

Update the relevant context file whenever implementation changes:

- System architecture or boundaries → `architecture.md`
- Storage model or DynamoDB schema decisions → `architecture.md`
- Code conventions or standards → `code-standards.md`
- Feature scope or user-facing flow → `project-overview.md`
- Visual/design decisions → `ui-context.md`

## Before Moving to the Next Unit

1. The current unit works end to end within its defined scope
   (e.g. a tool function has a passing local test call, a deployed
   Lambda has been invoked with a sample event, a UI change renders
   and functions in the browser).
2. No invariant defined in `architecture.md` was violated
   (tenant isolation, single-source-of-truth business logic,
   sub-agents never exposed directly, etc.).
3. `progress-tracker.md` reflects the completed work — move the
   item from "Next Up" to "Completed," update "Current Goal," add
   any new open questions or architecture decisions surfaced.
4. Relevant build/deploy check passes: `npm run build` for the
   frontend, `cdk synth` (or `cdk deploy` where appropriate) for
   infrastructure changes.
