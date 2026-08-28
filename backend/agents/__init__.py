"""Strands agent definitions: the model-facing surface over `backend/tools/`.

`architecture.md` -> System Boundaries puts the Orchestrator and its
sub-agents here, wired with the Agent-as-Tool pattern: each sub-agent is
an `Agent` in its own right, exposed to the Orchestrator as a single
`@tool` and to nothing else (Invariants #2).

Everything in this package is deliberately thin. `backend/tools/` decides
what may be booked, moved, cancelled and escalated; the modules here
decide only what the model is *shown* -- which arguments it may choose,
what a refusal reads like, and what a sub-agent is told about the clinic
it is answering for. Nothing that the background Lambda would also need
belongs in here (Invariants #3).

Modules:
    session: the per-session `ClinicSession`. The only route a `clinic_id`
        takes into a tool call, and the reason no tool here has one as a
        parameter.
    results: turning a `tools.errors.ToolError` into something a model can
        act on -- and keeping a broken deployment out of a patient's ear.
    scheduling_agent: the Scheduling sub-agent -- availability, booking,
        rescheduling, cancellation -- and its Agent-as-Tool wrapper.

Still to land: `escalation_agent`, `orchestrator`, and `faq_agent` (which
waits on the Knowledge Base).
"""
