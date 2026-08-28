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
    orchestrator: the patient-facing agent -- greeting, intent, routing --
        and `start_call`, the one entry point anything driving a
        conversation should use. It holds the two sub-agents and no tool
        of its own, and it is the only agent here that keeps a
        conversation across turns.
    results: turning a `tools.errors.ToolError` into something a model can
        act on -- and keeping a broken deployment out of a patient's ear.
    scheduling_agent: the Scheduling sub-agent -- availability, booking,
        rescheduling, cancellation -- and its Agent-as-Tool wrapper.
    escalation_agent: the Escalation sub-agent -- the handover to a human
        (Invariants #6) -- and its Agent-as-Tool wrapper. It holds
        `create_escalation` alone: the escalation *reads* are staff-only
        and belong to the dashboard, not to a patient-facing agent.
    voice: the same Orchestrator as a `BidiAgent` over Nova Sonic --
        speech in, speech out, the same two assistants. It holds no
        routing rule of its own: the prompt and the tools come from
        `orchestrator`, and only what the microphone adds is written
        there. `start_voice_call` is its entry point.
    cli: the local text interface -- `python -m agents.cli <clinic-id>`,
        a keyboard loop over `start_call`. The one module here that is
        not model-facing at all: it is where a real model first reads
        these prompts, and where the text model is chosen.
    mic: the local microphone interface -- `python -m agents.mic
        <clinic-id>`, `BidiAgent.run` over a sound card. A development
        entry point, like `cli`, over `start_voice_call` instead.
    agentcore_app: the deployed voice entrypoint -- a FastAPI `/ws` and
        `/ping` over `start_voice_call`, shaped for Bedrock AgentCore
        Runtime. The one interface here a patient's own browser reaches;
        `cli` and `mic` are for development only.

Still to land: `faq_agent`, which waits on the Knowledge Base. Until the
FAQ sub-agent exists, a question about prices or preparation routes to a
member of staff rather than to an answer.
"""
