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
    clinics: the staff-editable availability config -- the Settings tab's
        read and write. Validation is eager here, because a malformed
        config written to the table would fail lazily inside
        `scheduling`, with a patient on the line.
    patients: the phone-number lookup a voice caller arrives by, and the
        rule for when two calls are the same person.
    booking: `book_appointment` -- the first write. Decides nothing about
        availability itself; it re-asks `scheduling` at write time.
    appointments: changing a booking that already exists --
        `reschedule_appointment` and `cancel_appointment`. Works out which
        of a caller's appointments is meant, and re-asks `scheduling` the
        same way `booking` does.
    escalations: what the agent could not safely do itself -- raising an
        item for staff, reading the open queue, and marking one handled.
        The one module here whose items exist to be read by a person.
    faq: `query_faq` -- passages from the clinic's own Bedrock Knowledge
        Base, for a sub-agent's model to phrase. The only module here that
        reads from something other than DynamoDB.
    automation: `run_daily_scan` -- the background job's whole decision,
        per appointment: escalate a patient's own no-show history, or send
        a reminder. The only module here `backend/lambda/background_scan.py`
        calls into.

Nothing here imports Strands or AgentCore. The `@tool`-decorated agent
surface lives in `backend/agents/`; this layer stays callable from a
Lambda, a seed script, or a test with no agent runtime present.
"""
