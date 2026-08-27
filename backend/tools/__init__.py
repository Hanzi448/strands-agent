"""Shared business logic — the single source of truth for data access.

`architecture.md` -> System Boundaries makes this package the only place
appointment/patient/escalation data is read or mutated: the live voice
agent and the background Lambda both call in here rather than each
holding their own copy of the rules (Invariants #3).

Modules:
    schema: item attribute names, status vocabularies, key/time helpers.
    validation: boundary checks every tool runs before touching data.
    dynamo: table handles, resolved from the CDK-provided environment.
    errors: the exception vocabulary tools raise.
    scheduling: availability -- and the only place clinic-local wall-clock
        time is converted to and from the UTC everything else stores.

Nothing here imports Strands or AgentCore. The `@tool`-decorated agent
surface lives in `backend/agents/`; this layer stays callable from a
Lambda, a seed script, or a test with no agent runtime present.
"""
