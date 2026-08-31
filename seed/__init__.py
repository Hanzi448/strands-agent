"""Scripts that seed the two demo clinics into a deployed environment.

`architecture.md` -> System Boundaries: "Scripts to seed the two demo
clinics (config, sample appointments, sample FAQ documents for the
Knowledge Base)." `progress-tracker.md` -> Next Up folded the two staff
Cognito accounts in here too, since they are demo data exactly as the
clinic rows are.

Modules:
    clinic_data: the two `Clinics` items, matching `architecture.md` ->
        Storage Model ("Clinic availability config") exactly -- the same
        shapes `backend/tests/test_scheduling.py` fixtures use.
    sample_data: sample patients and appointments, booked through
        `tools.booking.book_appointment` rather than written directly, so
        seeded data can never drift from what the live agent would produce
        (`architecture.md` -> Invariants #3's spirit, applied to a script
        instead of a Lambda).
    faq_content: sample FAQ documents (pricing, prep, policies) for each
        clinic's Knowledge Base, per `project-overview.md` -> Core
        Features.
    aws_io: the boto3 calls this package needs beyond
        `tools.dynamo` -- S3 upload, Bedrock ingestion, Cognito account
        creation -- each taking an injected client so it is testable
        without credentials, the same shape as every fake in
        `backend/tests/`.
    run_seed: the CLI entry point tying the above together.

This package is not part of `backend/tools/`: it writes `Clinics` rows and
creates Cognito accounts, neither of which any tool function does (a
clinic's config is fixed data, not something the agent or the background
job ever creates). It reuses `backend/tools/` for everything that already
has a rule -- booking, patient identity -- rather than restating any of
it, per `architecture.md` -> Invariants #3.

Run from the repository root:

    python -m seed.run_seed --dry-run

`backend/tools/` has no AgentCore or Strands dependency
(`backend/tools/__init__.py`), so it is importable here with no agent
runtime present. Since `seed/` lives outside `backend/`, this package adds
`backend/` to `sys.path` on import -- once, guarded -- so every submodule
can `from tools import ...` the same way a test in `backend/tests/` does.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
