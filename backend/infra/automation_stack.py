"""Automation stack: the EventBridge schedule and the background Lambda.

Skeleton only -- no resources yet. Populated by `progress-tracker.md`
Next Up #7.

Planned contents, per `architecture.md` -> Stack:
  - EventBridge Scheduler rule firing the daily per-clinic appointment
    scan.
  - Lambda running `backend/lambda/background_scan.py`, which must call
    the same `backend/tools/` functions the live voice agent calls for
    any mutation (`architecture.md` -> Invariants #3) -- so this stack
    packages that shared code rather than a Lambda-local copy of it.
  - SES send permission for escalation email, scoped to the verified
    sender identity (verified manually outside CDK -- see
    `progress-tracker.md` -> Open Questions).
"""

from __future__ import annotations

from aws_cdk import Stack
from constructs import Construct

from config import ProjectConfig


class AutomationStack(Stack):
    """Daily autonomous appointment scan: EventBridge schedule + Lambda."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: ProjectConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.config = config
