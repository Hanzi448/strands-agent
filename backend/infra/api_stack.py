"""API stack: API Gateway, the API Lambdas, and Cognito.

Skeleton only -- no resources yet. Populated alongside the staff
dashboard (`progress-tracker.md` Next Up #8).

Planned contents, per `architecture.md` -> Stack and System Boundaries:
  - Cognito user pool for staff only, one demo account per clinic.
    Patients are unauthenticated (`architecture.md` -> Auth and Access
    Model); how an unauthenticated patient reaches the voice endpoint is
    still an open question in `progress-tracker.md` and may add an
    identity pool here, or a WebSocket API in front of `voice_bridge.py`.
  - REST API for the staff dashboard, backed by
    `backend/lambda/dashboard_api.py`, every route Cognito-authorised and
    clinic-scoped (`architecture.md` -> Invariants #5).
  - IAM grants scoped to the specific tables and actions each handler
    needs -- no `*` resource grants (`code-standards.md`).
"""

from __future__ import annotations

from aws_cdk import Stack
from constructs import Construct

from config import ProjectConfig


class ApiStack(Stack):
    """Staff dashboard API, the voice session bridge, and Cognito."""

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
