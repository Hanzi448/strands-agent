"""Data stack: DynamoDB tables and S3 buckets.

Skeleton only -- no resources yet. Populated by `progress-tracker.md`
Next Up #2 (DynamoDB table schemas).

Planned contents, per `architecture.md` -> Storage Model:
  - DynamoDB `Clinics`      (PK `clinic_id`)
  - DynamoDB `Appointments` (PK `clinic_id`, SK `appointment_id`)
  - DynamoDB `Patients`     (PK `clinic_id`, SK `patient_id`)
  - DynamoDB `Escalations`  (PK `clinic_id`, SK `escalation_id`)
  - S3 bucket for Knowledge Base source documents, one `kb/{clinic_id}/`
    prefix per clinic.

Every table is `clinic_id`-partitioned -- `architecture.md` -> Invariants #1
allows no access pattern that omits it.
"""

from __future__ import annotations

from aws_cdk import Stack
from constructs import Construct

from config import ProjectConfig


class DataStack(Stack):
    """DynamoDB tables and the Knowledge Base source bucket."""

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
