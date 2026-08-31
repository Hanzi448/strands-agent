"""Automation stack: the EventBridge schedule and the background Lambda.

`progress-tracker.md` Next Up #2, the CDK half of the background job --
the same "code first, deploy second" split `agentcore_app.py`/
`agent_stack.py` went through (`ai-workflow-rules.md` -> When to Split
Work). `tools/automation.py` (`run_daily_scan`) and
`lambda/background_scan.py` are done and tested (see
`progress-tracker.md` -> Completed); this stack only wires them up:

  - One `Lambda` running `lambda.background_scan.handler`, packaged from
    `backend/`'s own `lambda/` and `tools/` directories -- the same
    functions the live voice agent calls for any mutation
    (`architecture.md` -> Invariants #3), never a Lambda-local copy.
  - One EventBridge Scheduler schedule per seeded clinic
    (`config.DEMO_CLINIC_IDS`), each with its own
    ``{"clinic_id": ...}`` input (`architecture.md` -> Invariants #1: one
    invocation is one clinic, never a fan-out inside a single run).
  - An execution role scoped to exactly what `tools/automation.py` and
    the modules it calls reach: `GetItem` on `Clinics`, `Query` +
    `UpdateItem` on `Appointments` (the `by-patient` and `by-start-time`
    indexes, plus the reminder-list write), `GetItem` on `Patients`,
    `PutItem` on `Escalations`, and `ses:SendEmail` scoped to this
    account/region's verified identities (`code-standards.md` -> AWS CDK
    forbids a blanket resource/action grant; the identity itself is
    verified manually outside CDK, so its ARN cannot be pinned here --
    see `progress-tracker.md` -> Open Questions).
"""

from __future__ import annotations

import json
from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct

from config import DEMO_CLINIC_IDS, ProjectConfig

# Where the Lambda's code comes from -- one directory up from this stack's
# own file, since `backend/` (not `backend/infra/`) is where `lambda/` and
# `tools/` actually live, mirroring `agent_stack.py`'s `_BACKEND_DIR`.
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)

# Only `lambda/` and `tools/` are ever imported by the handler
# (`architecture.md` -> System Boundaries: this package must not depend on
# Strands or AgentCore) -- everything else in `backend/` is excluded from
# the zip asset, the same restriction `Dockerfile` already applies via
# `COPY agents/ tools/` for the AgentCore container.
_LAMBDA_ASSET_EXCLUDES = [
    "agents",
    "infra",
    "tests",
    ".venv",
    "**/__pycache__",
    "**/*.pyc",
    ".pytest_cache",
    ".git",
    "requirements-dev.txt",
    "pytest.ini",
    "Dockerfile",
    ".dockerignore",
]

# `lambda` is a Python keyword, so the handler string is the only place
# this package's name is ever written down here -- resolved by the Lambda
# runtime's own importlib-based loader, never parsed as Python source
# (`backend/lambda/background_scan.py`'s own module docstring).
_HANDLER = "lambda.background_scan.handler"


def _clinic_slug(clinic_id: str) -> str:
    """`clinic-dental` -> `Dental`, for CDK construct ids.

    Duplicated from `agent_stack.py` rather than imported: that helper is
    module-private, and this is a two-line naming rule, not shared logic
    (the same tradeoff `agent_stack.py`'s own `KB_ID_ENV_PREFIX` comment
    makes for a duplicated constant).
    """
    return clinic_id.removeprefix("clinic-").replace("-", " ").title().replace(" ", "")


class AutomationStack(Stack):
    """Daily autonomous appointment scan: EventBridge schedule + Lambda."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: ProjectConfig,
        clinics_table: dynamodb.ITableV2,
        patients_table: dynamodb.ITableV2,
        appointments_table: dynamodb.ITableV2,
        escalations_table: dynamodb.ITableV2,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.config = config

        self.function = self._build_scan_function(
            clinics_table=clinics_table,
            patients_table=patients_table,
            appointments_table=appointments_table,
            escalations_table=escalations_table,
        )
        self._build_schedules()

    def _build_scan_function(
        self,
        *,
        clinics_table: dynamodb.ITableV2,
        patients_table: dynamodb.ITableV2,
        appointments_table: dynamodb.ITableV2,
        escalations_table: dynamodb.ITableV2,
    ) -> lambda_.Function:
        """The Lambda running `tools.automation.run_daily_scan`, via `lambda/`.

        No dependency bundling step: `tools/automation.py` reaches only
        `boto3` (already in the Lambda Python runtime) and the standard
        library, so the plain source asset is the whole deployment unit --
        the same reasoning `dynamo.py`'s lazy `boto3` import already
        documents for keeping this package installable without the AWS SDK
        present.
        """
        function = lambda_.Function(
            self,
            "BackgroundScanFunction",
            function_name=self.config.resource_name("background-scan"),
            description=(
                "ClinicPilot daily scan: one clinic's due appointments, "
                "escalated on no-show risk or reminded otherwise."
            ),
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler=_HANDLER,
            code=lambda_.Code.from_asset(_BACKEND_DIR, exclude=_LAMBDA_ASSET_EXCLUDES),
            timeout=Duration.minutes(2),
            environment={
                # `tools/dynamo.table_name`'s fallback naming scheme, the
                # same two variables `agent_stack.py`'s runtime sets.
                "CLINICPILOT_PROJECT_PREFIX": self.config.project_prefix,
                "CLINICPILOT_ENV": self.config.environment,
                # Deliberately absent: `tools.automation.REMINDER_SENDER_ENV`
                # (`CLINICPILOT_REMINDER_SENDER_EMAIL`). No SES sender
                # identity is verified yet (`progress-tracker.md` -> Open
                # Questions) -- set once one exists, not invented here.
            },
        )

        # Scoped to exactly the calls each module makes (verified against
        # the modules themselves, not assumed) -- the same style
        # `agent_stack.py._build_agent_runtime` already documents.
        for sid, table, actions in (
            # `scheduling.get_clinic`.
            ("ReadClinicsTable", clinics_table, ["dynamodb:GetItem"]),
            # `patients.get_patient` -- a `patient_id` off an appointment,
            # never a `by-phone` lookup, so no `Query` grant here.
            ("ReadPatientsTable", patients_table, ["dynamodb:GetItem"]),
            # `appointments.appointment_history_for_patient` (`by-patient`)
            # and `automation._scheduled_starting_within`
            # (`by-start-time`) query; `automation._record_reminder`
            # writes the `reminders` list back onto the same item.
            (
                "ReadWriteAppointmentsTable",
                appointments_table,
                ["dynamodb:Query", "dynamodb:UpdateItem"],
            ),
            # `escalations.create_escalation` -- a write-only path, exactly
            # as `agent_stack.py`'s runtime role is for the same function.
            ("CreateEscalations", escalations_table, ["dynamodb:PutItem"]),
        ):
            resources = [table.table_arn]
            if "dynamodb:Query" in actions:
                resources.append(f"{table.table_arn}/index/*")
            function.add_to_role_policy(
                iam.PolicyStatement(sid=sid, actions=actions, resources=resources)
            )

        # `automation._send_reminder_email`. Scoped to the identity
        # resource type in this account/region, not to `*` -- the same
        # "resource type, not one ARN" tradeoff `agent_stack.py` documents
        # for `foundation-model/*`, since the verified sender identity is
        # created manually outside CDK and its ARN cannot be pinned here.
        function.add_to_role_policy(
            iam.PolicyStatement(
                sid="SendReminderEmail",
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[f"arn:aws:ses:{self.region}:{self.account}:identity/*"],
            )
        )

        CfnOutput(
            self,
            "BackgroundScanFunctionArn",
            value=function.function_arn,
            description="Lambda running the daily per-clinic background scan.",
            export_name=f"{self.config.resource_name('background-scan')}-arn",
        )

        return function

    def _build_schedules(self) -> None:
        """One EventBridge Scheduler schedule per demo clinic.

        Each invokes `self.function` once a day with its own
        `{"clinic_id": ...}` input -- `architecture.md` -> Invariants #1 --
        rather than one schedule fanning out over every clinic inside a
        single run.
        """
        role = iam.Role(
            self,
            "SchedulerExecutionRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeBackgroundScanFunction",
                actions=["lambda:InvokeFunction"],
                resources=[self.function.function_arn],
            )
        )

        for clinic_id in DEMO_CLINIC_IDS:
            slug = _clinic_slug(clinic_id)
            scheduler.CfnSchedule(
                self,
                f"{slug}DailyScanSchedule",
                description=f"Daily background scan for {clinic_id}.",
                schedule_expression="rate(1 day)",
                flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                    mode="OFF",
                ),
                target=scheduler.CfnSchedule.TargetProperty(
                    arn=self.function.function_arn,
                    role_arn=role.role_arn,
                    input=json.dumps({"clinic_id": clinic_id}),
                ),
            )
