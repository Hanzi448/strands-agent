"""EventBridge Scheduler entrypoint: one clinic's daily scan.

`architecture.md` -> Storage Model and Invariants #3: the whole decision --
whether an upcoming appointment gets a reminder or an escalation -- lives
in `tools.automation.run_daily_scan`. This handler does nothing but read
`clinic_id` off the triggering event and hand it there; it holds no rule
of its own, for the same reason `agents/cli.py` holds none of the agent
tree's routing logic.

**One invocation is one clinic.** `architecture.md` -> Invariants #1
forbids a query that spans more than one tenant, and `project-overview.md`
already describes the job as running "daily per clinic" -- so the
EventBridge Scheduler infrastructure (not yet built; see
`progress-tracker.md` -> Next Up) is expected to define one schedule per
seeded clinic, each invoking this same function with a different
``{"clinic_id": ...}`` payload, rather than one schedule that fans out
inside a single run.
"""

from __future__ import annotations

import logging
from typing import Any

from tools.automation import run_daily_scan
from tools.errors import ToolError

logger = logging.getLogger(__name__)


def handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """Run the daily scan for the clinic named in `event`.

    Args:
        event: The EventBridge Scheduler payload, ``{"clinic_id": "..."}"``.
        context: The Lambda context object. Unused; accepted so this
            matches the shape the Lambda runtime calls.

    Returns:
        `tools.automation.run_daily_scan`'s summary dict.

    Raises:
        ToolError: If `clinic_id` is missing/malformed (a misconfigured
            schedule) or the clinic's stored config is unusable (a
            deployment fault). Logged here and re-raised rather than
            swallowed, so a broken schedule shows up as a failed Lambda
            invocation in CloudWatch rather than a silent no-op.
    """
    clinic_id = event.get("clinic_id")
    try:
        return run_daily_scan(clinic_id)
    except ToolError:
        logger.exception("Daily scan failed for clinic_id=%r", clinic_id)
        raise
