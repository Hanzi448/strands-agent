"""Data stack: the four DynamoDB tables.

Every table is partitioned by `clinic_id`, and every secondary index
carries `clinic_id` in its own partition key -- `architecture.md` ->
Invariants #1 permits no access pattern that omits it, and an index
keyed on anything else would be exactly such a path. See
`architecture.md` -> Storage Model for the item shapes and the access
patterns each index serves.

The Knowledge Base source bucket named in `architecture.md` -> Storage
Model also belongs to this stack but is not defined yet -- it is its own
tracker item, since it is provisioned together with the Bedrock
Knowledge Base that reads it.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

from config import ProjectConfig

# Key attribute names. Defined once here because the tool layer and the
# seed scripts must spell them identically -- a typo in a key name is a
# silent empty query, not an error.
CLINIC_ID = "clinic_id"
APPOINTMENT_ID = "appointment_id"
PATIENT_ID = "patient_id"
ESCALATION_ID = "escalation_id"
STARTS_AT = "starts_at"
CREATED_AT = "created_at"
PHONE = "phone"
# Composite `{clinic_id}#{patient_id}`, written by the tool layer. It
# exists so "this patient's appointments" is a single clinic-scoped
# query key rather than a `patient_id`-only index that could, in
# principle, be queried across clinics.
CLINIC_PATIENT = "clinic_patient"

# Index names. Referenced by the tool layer and passed to Lambdas as
# environment variables alongside the table names.
APPOINTMENTS_BY_START_TIME_INDEX = "by-start-time"
APPOINTMENTS_BY_PATIENT_INDEX = "by-patient"
PATIENTS_BY_PHONE_INDEX = "by-phone"
ESCALATIONS_BY_CREATED_AT_INDEX = "by-created-at"


def _key(name: str) -> dynamodb.Attribute:
    """A string-typed key attribute. Every key in this stack is a string."""
    return dynamodb.Attribute(name=name, type=dynamodb.AttributeType.STRING)


class DataStack(Stack):
    """The `Clinics`, `Patients`, `Appointments`, and `Escalations` tables."""

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

        # The hackathon only ever deploys `dev`, which must be teardown-able
        # in one command; a real `prod` keeps its data and its backups.
        self._ephemeral = config.environment != "prod"

        self.clinics_table = self._table(
            "Clinics",
            "clinics",
            partition_key=_key(CLINIC_ID),
        )

        self.patients_table = self._table(
            "Patients",
            "patients",
            partition_key=_key(CLINIC_ID),
            sort_key=_key(PATIENT_ID),
            global_secondary_indexes=[
                # A voice caller identifies themselves by phone number, not
                # by id: look the patient up before touching appointments.
                dynamodb.GlobalSecondaryIndexPropsV2(
                    index_name=PATIENTS_BY_PHONE_INDEX,
                    partition_key=_key(CLINIC_ID),
                    sort_key=_key(PHONE),
                ),
            ],
        )

        self.appointments_table = self._table(
            "Appointments",
            "appointments",
            partition_key=_key(CLINIC_ID),
            sort_key=_key(APPOINTMENT_ID),
            global_secondary_indexes=[
                # Availability checks, the staff dashboard's day view, and
                # the daily background scan are all "this clinic, this time
                # range" queries.
                dynamodb.GlobalSecondaryIndexPropsV2(
                    index_name=APPOINTMENTS_BY_START_TIME_INDEX,
                    partition_key=_key(CLINIC_ID),
                    sort_key=_key(STARTS_AT),
                ),
                # Reschedule and cancel need the caller's existing
                # appointments, in time order.
                dynamodb.GlobalSecondaryIndexPropsV2(
                    index_name=APPOINTMENTS_BY_PATIENT_INDEX,
                    partition_key=_key(CLINIC_PATIENT),
                    sort_key=_key(STARTS_AT),
                ),
            ],
        )

        self.escalations_table = self._table(
            "Escalations",
            "escalations",
            partition_key=_key(CLINIC_ID),
            sort_key=_key(ESCALATION_ID),
            global_secondary_indexes=[
                # The dashboard's escalation queue: newest first for one
                # clinic. `status` is a filter rather than a key -- an
                # escalation queue is small enough that a filtered read
                # beats maintaining a composite status key.
                dynamodb.GlobalSecondaryIndexPropsV2(
                    index_name=ESCALATIONS_BY_CREATED_AT_INDEX,
                    partition_key=_key(CLINIC_ID),
                    sort_key=_key(CREATED_AT),
                ),
            ],
        )

        self._export_table_names()

    def _table(
        self,
        construct_id: str,
        name: str,
        *,
        partition_key: dynamodb.Attribute,
        sort_key: dynamodb.Attribute | None = None,
        global_secondary_indexes: list[dynamodb.GlobalSecondaryIndexPropsV2] | None = None,
    ) -> dynamodb.TableV2:
        """Create one table with this project's shared table settings.

        On-demand billing (demo traffic is bursty and near zero between
        runs), and physical names from `ProjectConfig` so no name is
        written twice.

        Args:
            construct_id: CloudFormation logical id for the table.
            name: Resource-name suffix, e.g. ``appointments``.
            partition_key: Always `clinic_id` in this stack.
            sort_key: The per-table entity id, or None for `Clinics`.
            global_secondary_indexes: Indexes for this table's non-key
                access patterns. Each projects ALL attributes: these
                tables are small, and the tool layer reads whole items.
        """
        return dynamodb.TableV2(
            self,
            construct_id,
            table_name=self.config.resource_name(name),
            partition_key=partition_key,
            sort_key=sort_key,
            billing=dynamodb.Billing.on_demand(),
            global_secondary_indexes=global_secondary_indexes,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=not self._ephemeral,
            ),
            deletion_protection=not self._ephemeral,
            removal_policy=(
                RemovalPolicy.DESTROY if self._ephemeral else RemovalPolicy.RETAIN
            ),
        )

    def _export_table_names(self) -> None:
        """Export each table name so other stacks and `seed/` can resolve it.

        Other stacks in this app take the table objects directly; the
        exports exist for the seed scripts and for CLI lookups, which run
        outside CDK.
        """
        for concern, table in (
            ("clinics", self.clinics_table),
            ("patients", self.patients_table),
            ("appointments", self.appointments_table),
            ("escalations", self.escalations_table),
        ):
            CfnOutput(
                self,
                f"{concern.capitalize()}TableName",
                value=table.table_name,
                description=f"DynamoDB table holding {concern}.",
                export_name=f"{self.config.resource_name(concern)}-table-name",
            )
