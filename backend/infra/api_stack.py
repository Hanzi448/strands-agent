"""API stack: staff dashboard REST API, its Cognito user pool, and its Lambda.

`progress-tracker.md` Next Up #2a, the CDK half of the staff dashboard --
the same "code first, deploy second" split `agent_stack.py`'s AgentCore
Runtime and `automation_stack.py`'s background scan already went through
(`ai-workflow-rules.md` -> When to Split Work). `dashboard_api.py`'s four
routes and its read/write surface over `tools/appointments.py` and
`tools/escalations.py` are done and tested (see `progress-tracker.md` ->
Completed); this stack only wires them up:

  - One Cognito user pool for staff, carrying a `clinic_id` custom
    attribute (`architecture.md` -> Auth and Access Model) that
    `dashboard_api._clinic_id_from` reads off the verified token's claims
    as `custom:clinic_id` -- Cognito adds that prefix to every custom
    attribute's claim name itself, so the attribute is declared here
    without it and read there with it. This pool is entirely separate
    from the patient-facing Cognito *identity* pool (guest credentials
    for the voice endpoint, provisioned alongside `frontend_stack.py`):
    staff authentication must not share a credential path with anonymous
    visitors (`architecture.md` -> Invariants #5).
    **Seeding the two demo accounts themselves is Next Up #3, not this
    unit** (`progress-tracker.md` -> Architecture Decisions, "Seeding
    that attribute onto each demo account is now part of Next Up #3"): a
    CDK-managed Cognito user needs a password strategy that is not a
    resource-naming decision, and a seed script that already writes
    sample appointments is the natural place to script
    `admin-create-user` / `admin-set-user-password` calls instead of a
    one-off CDK custom resource.
  - One REST API Gateway, its resources matching
    `dashboard_api._ROUTES` exactly -- `/appointments` (GET),
    `/escalations` (GET), `/escalations/{escalation_id}` (GET),
    `/escalations/{escalation_id}/resolve` (POST) -- each behind a
    Cognito user-pool authorizer, so an unauthenticated or wrong-pool
    token never reaches the Lambda at all (`architecture.md` ->
    Invariants #5). Explicit resources rather than one `{proxy+}`
    catch-all, since the route table is fixed and small
    (`code-standards.md` -> AWS CDK: every route defined in CDK).
  - One Lambda running `lambda.dashboard_api.handler`, packaged the same
    way `automation_stack.py`'s background-scan function is: just
    `backend/`'s own `lambda/` and `tools/` directories, so it calls the
    same `backend/tools/` functions the voice agent and the background
    job do, never a duplicate copy (`architecture.md` -> Invariants #3).
  - An execution role scoped to exactly what `tools/appointments.py` and
    `tools/escalations.py` call for this Lambda (verified against those
    modules, not assumed): `Query` on `Appointments`' `by-start-time`
    index for `list_appointments_for_clinic`; `Query` on `Escalations`'
    `by-created-at` index for `list_open_escalations`, plus `GetItem` and
    `UpdateItem` for `get_escalation`/`resolve_escalation`
    (`code-standards.md` -> AWS CDK forbids a blanket resource/action
    grant).

CORS is wide open (`default_cors_preflight_options`, all origins/methods)
because the frontend's own origin does not exist yet
(`frontend_stack.py` is still a skeleton) -- narrowing it to the deployed
CloudFront domain is a `frontend_stack.py`-time change, not a product
decision to escalate now.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

from config import ProjectConfig

# Mirrors `automation_stack.py`'s own `_BACKEND_DIR`/`_LAMBDA_ASSET_EXCLUDES`:
# `backend/` (not `backend/infra/`) is where `lambda/` and `tools/` live,
# and only those two packages ever need to reach this Lambda's runtime.
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)

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

# `lambda` is a Python keyword -- see `automation_stack.py`'s own
# `_HANDLER` comment for why this is a plain string the Lambda runtime
# resolves via its own importlib-based loader, never parsed as Python
# source by anything in this stack.
_HANDLER = "lambda.dashboard_api.handler"

# `dashboard_api.CLINIC_ID_CLAIM` is `"custom:clinic_id"` -- the prefix
# Cognito adds to every custom attribute's claim name. The attribute
# itself is declared here without that prefix.
CLINIC_ID_ATTRIBUTE = "clinic_id"


class ApiStack(Stack):
    """Staff dashboard: Cognito user pool, REST API, and its Lambda."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: ProjectConfig,
        appointments_table: dynamodb.ITableV2,
        escalations_table: dynamodb.ITableV2,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.config = config
        self.appointments_table = appointments_table
        self.escalations_table = escalations_table

        self.user_pool, self.user_pool_client = self._build_user_pool()
        self.function = self._build_dashboard_function(
            appointments_table=appointments_table,
            escalations_table=escalations_table,
        )
        self.api = self._build_api()

    def _build_user_pool(self) -> tuple[cognito.UserPool, cognito.UserPoolClient]:
        """Staff-only user pool, `custom:clinic_id` scoping every account.

        No self-sign-up and no password recovery: the only two accounts
        this pool will ever hold are the demo clinics' own, created by
        Next Up #3's seed script -- not a public registration flow.
        """
        ephemeral = self.config.environment != "prod"

        user_pool = cognito.UserPool(
            self,
            "StaffUserPool",
            user_pool_name=self.config.resource_name("staff-users"),
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True, username=False),
            custom_attributes={
                CLINIC_ID_ATTRIBUTE: cognito.StringAttribute(mutable=False),
            },
            account_recovery=cognito.AccountRecovery.NONE,
            removal_policy=RemovalPolicy.DESTROY if ephemeral else RemovalPolicy.RETAIN,
        )

        client = user_pool.add_client(
            "DashboardClient",
            user_pool_client_name=self.config.resource_name("dashboard-client"),
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
        )

        CfnOutput(
            self,
            "StaffUserPoolId",
            value=user_pool.user_pool_id,
            description="Cognito user pool id for staff dashboard login.",
            export_name=f"{self.config.resource_name('staff-users')}-id",
        )
        CfnOutput(
            self,
            "StaffUserPoolClientId",
            value=client.user_pool_client_id,
            description="Cognito app client id the dashboard SPA authenticates with.",
            export_name=f"{self.config.resource_name('dashboard-client')}-id",
        )

        return user_pool, client

    def _build_dashboard_function(
        self,
        *,
        appointments_table: dynamodb.ITableV2,
        escalations_table: dynamodb.ITableV2,
    ) -> lambda_.Function:
        """The Lambda running `lambda.dashboard_api.handler`.

        No dependency-bundling step: `dashboard_api.py` and the
        `backend/tools/` functions it calls reach only `boto3` (already in
        the Lambda Python runtime) and the standard library, the same
        reasoning `automation_stack.py`'s function build documents.
        """
        function = lambda_.Function(
            self,
            "DashboardApiFunction",
            function_name=self.config.resource_name("dashboard-api"),
            description=(
                "ClinicPilot staff dashboard: appointment list and "
                "escalation queue, Cognito-scoped to one clinic per request."
            ),
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler=_HANDLER,
            code=lambda_.Code.from_asset(_BACKEND_DIR, exclude=_LAMBDA_ASSET_EXCLUDES),
            timeout=Duration.seconds(10),
            environment={
                # `tools/dynamo.table_name`'s fallback naming scheme --
                # the same two variables `automation_stack.py` and
                # `agent_stack.py` set for their own functions.
                "CLINICPILOT_PROJECT_PREFIX": self.config.project_prefix,
                "CLINICPILOT_ENV": self.config.environment,
            },
        )
        return function

    def _build_api(self) -> apigateway.RestApi:
        """The four dashboard routes, each behind a Cognito authorizer.

        `LambdaIntegration(..., proxy=True)` (the default) is what gives
        `dashboard_api.handler` the full proxy-integration event shape it
        expects: `httpMethod`, `resource`, `pathParameters`,
        `queryStringParameters`, and -- once the Cognito authorizer has
        verified the token -- `requestContext.authorizer.claims`.
        """
        api = apigateway.RestApi(
            self,
            "DashboardApi",
            rest_api_name=self.config.resource_name("dashboard-api"),
            description="ClinicPilot staff dashboard API.",
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=["Authorization", "Content-Type"],
            ),
        )

        authorizer = apigateway.CognitoUserPoolsAuthorizer(
            self, "DashboardAuthorizer", cognito_user_pools=[self.user_pool]
        )
        integration = apigateway.LambdaIntegration(self.function)
        secured = {
            "authorization_type": apigateway.AuthorizationType.COGNITO,
            "authorizer": authorizer,
        }

        appointments = api.root.add_resource("appointments")
        appointments.add_method("GET", integration, **secured)

        escalations = api.root.add_resource("escalations")
        escalations.add_method("GET", integration, **secured)

        escalation = escalations.add_resource("{escalation_id}")
        escalation.add_method("GET", integration, **secured)

        resolve = escalation.add_resource("resolve")
        resolve.add_method("POST", integration, **secured)

        # Scoped to exactly the calls `dashboard_api.py`'s routes make
        # (verified against `tools/appointments.py` and
        # `tools/escalations.py`, not assumed) -- the same style
        # `automation_stack.py`'s and `agent_stack.py`'s roles document.
        for sid, table, actions in (
            (
                "ReadAppointmentsTable",
                self.appointments_table,
                ["dynamodb:Query"],
            ),
            (
                "ReadWriteEscalationsTable",
                self.escalations_table,
                ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"],
            ),
        ):
            resources = [table.table_arn]
            if "dynamodb:Query" in actions:
                resources.append(f"{table.table_arn}/index/*")
            self.function.add_to_role_policy(
                iam.PolicyStatement(sid=sid, actions=actions, resources=resources)
            )

        CfnOutput(
            self,
            "DashboardApiUrl",
            value=api.url,
            description="Base URL of the staff dashboard REST API.",
            export_name=f"{self.config.resource_name('dashboard-api')}-url",
        )

        return api
