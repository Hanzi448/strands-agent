"""The boto3 calls this package needs beyond `tools.dynamo`.

`tools.dynamo` already resolves the four table handles; this module is
its counterpart for the three other AWS surfaces seeding touches --
S3 (FAQ source documents), Bedrock Agent (Knowledge Base ingestion), and
Cognito (staff demo accounts) -- none of which any `backend/tools/`
module needs, so none of them belong there.

Every function that actually calls AWS reaches its client through one of
this module's own `*_client()` accessors -- `s3_client()`,
`bedrock_agent_client()`, `cognito_client()` -- exactly as
`tools.scheduling`/`tools.booking` reach `Clinics`/`Appointments` through
`clinics_table()`/`appointments_table()` rather than building a boto3
resource inline. That is what `backend/tests/test_seed_aws_io.py`
monkeypatches: `monkeypatch.setattr(aws_io, "s3_client", lambda: fake)`,
the same shape `test_booking.py`'s `tables` fixture uses for
`scheduling.clinics_table` -- no credentials, no moto, no network.

`KB_BUCKET_PREFIX`/`kb_source_prefix` duplicate
`backend/infra/data_stack.py`'s, for the reason
`backend/tests/test_schema_matches_infra.py` already documents for
`tools/schema.py`: this package cannot import `aws_cdk` (a different
virtual environment), so the string is written twice and a test guards
the two copies from drifting apart.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Final

from tools.errors import ConfigurationError
from tools.faq import knowledge_base_id_env_var

# --------------------------------------------------------------------------
# Client builders
# --------------------------------------------------------------------------
#
# Cached and lazily imported, exactly as `dynamo._dynamodb_resource` and
# `faq._bedrock_agent_runtime_client` are: building a boto3 client isn't
# free, and importing `boto3` at module top would make this whole package
# (including the pure-data modules that import it transitively through
# `seed/__init__.py`) require the AWS SDK just to read a docstring.


@lru_cache(maxsize=1)
def s3_client():  # noqa: ANN202 - boto3 clients have no public type
    """The process-wide `s3` client, for `upload_faq_documents`."""
    import boto3  # noqa: PLC0415 - deliberate lazy import, see section docstring

    return boto3.client("s3")


@lru_cache(maxsize=1)
def bedrock_agent_client():  # noqa: ANN202 - boto3 clients have no public type
    """The process-wide `bedrock-agent` control-plane client.

    Distinct from `tools.faq`'s `bedrock-agent-runtime` client: that one
    queries a Knowledge Base, this one manages it (`start_kb_ingestion`).
    """
    import boto3  # noqa: PLC0415 - deliberate lazy import, see section docstring

    return boto3.client("bedrock-agent")


@lru_cache(maxsize=1)
def cognito_client():  # noqa: ANN202 - boto3 clients have no public type
    """The process-wide `cognito-idp` client, for `ensure_staff_account`."""
    import boto3  # noqa: PLC0415 - deliberate lazy import, see section docstring

    return boto3.client("cognito-idp")


# --------------------------------------------------------------------------
# Naming: the KB source bucket
# --------------------------------------------------------------------------

# Must match `backend/infra/data_stack.py`'s `KB_BUCKET_PREFIX` --
# see the module docstring.
KB_BUCKET_PREFIX: Final[str] = "kb"


def kb_source_prefix(clinic_id: str) -> str:
    """The S3 prefix holding one clinic's knowledge base source documents.

    Must match `backend/infra/data_stack.py`'s `kb_source_prefix` exactly:
    it is what scopes a clinic's Bedrock data source to only that clinic's
    documents (`architecture.md` -> Invariants #1).
    """
    return f"{KB_BUCKET_PREFIX}/{clinic_id}/"


KB_BUCKET_ENV: Final[str] = "CLINICPILOT_KB_BUCKET"
# Mirrors `tools.dynamo`'s fallback scheme so a script needs at most
# `CLINICPILOT_ENV` set, exactly as `dynamo.table_name` does for the four
# tables -- `backend/infra/config.py`'s `resource_name("kb")`.
_PROJECT_PREFIX_ENV: Final[str] = "CLINICPILOT_PROJECT_PREFIX"
_ENVIRONMENT_ENV: Final[str] = "CLINICPILOT_ENV"
_DEFAULT_PROJECT_PREFIX: Final[str] = "clinicpilot"
_DEFAULT_ENVIRONMENT: Final[str] = "dev"


def kb_bucket_name() -> str:
    """Resolve the KB source bucket's physical name for this deployment.

    Returns:
        `$CLINICPILOT_KB_BUCKET` if set, otherwise
        `{project_prefix}-{environment}-kb` -- the same derivation
        `dynamo.table_name` uses for the four tables, and what
        `backend/infra/config.py`'s `resource_name("kb")` physically
        deploys.
    """
    configured = os.environ.get(KB_BUCKET_ENV, "").strip()
    if configured:
        return configured
    prefix = os.environ.get(_PROJECT_PREFIX_ENV, "").strip() or _DEFAULT_PROJECT_PREFIX
    environment = os.environ.get(_ENVIRONMENT_ENV, "").strip() or _DEFAULT_ENVIRONMENT
    return f"{prefix}-{environment}-kb"


# --------------------------------------------------------------------------
# Naming: the staff Cognito user pool
# --------------------------------------------------------------------------

# Unlike a table or bucket name, a Cognito user pool id
# (`us-east-1_AbCdEfGhI`) is assigned by AWS at creation and cannot be
# derived from `backend/infra/config.py`'s naming scheme -- it must come
# from `api_stack.py`'s `StaffUserPoolId` CfnOutput.
STAFF_USER_POOL_ID_ENV: Final[str] = "CLINICPILOT_STAFF_USER_POOL_ID"

# Never hardcoded: a password baked into source is a password in version
# control. Required, not defaulted -- printed back at the end of a real
# run so whoever seeded the environment can hand it to a demo presenter.
STAFF_DEMO_PASSWORD_ENV: Final[str] = "CLINICPILOT_STAFF_DEMO_PASSWORD"


def staff_user_pool_id() -> str:
    """The staff Cognito user pool id, or a `ConfigurationError` naming why.

    Raises:
        ConfigurationError: If `$CLINICPILOT_STAFF_USER_POOL_ID` is unset.
            A deployment fault -- there is no default to derive.
    """
    configured = os.environ.get(STAFF_USER_POOL_ID_ENV, "").strip()
    if not configured:
        raise ConfigurationError(
            f"{STAFF_USER_POOL_ID_ENV} is not set; copy the 'StaffUserPoolId'"
            " output from the Api stack's `cdk deploy`."
        )
    return configured


def staff_demo_password() -> str:
    """The password every seeded staff account is given.

    Raises:
        ConfigurationError: If `$CLINICPILOT_STAFF_DEMO_PASSWORD` is
            unset. Never defaulted -- see the constant's docstring.
    """
    configured = os.environ.get(STAFF_DEMO_PASSWORD_ENV, "").strip()
    if not configured:
        raise ConfigurationError(
            f"{STAFF_DEMO_PASSWORD_ENV} is not set; choose a password that"
            " meets the staff user pool's policy."
        )
    return configured


# --------------------------------------------------------------------------
# S3: FAQ source documents
# --------------------------------------------------------------------------


def upload_faq_documents(bucket: str, clinic_id: str, documents: dict[str, str]) -> list[str]:
    """Write one clinic's sample FAQ documents to its own KB source prefix.

    Args:
        bucket: The KB source bucket's physical name (`kb_bucket_name`).
        clinic_id: The clinic these documents belong to -- scopes every
            key under `kb_source_prefix(clinic_id)`, so a Bedrock data
            source restricted to that prefix can only ever ingest this
            clinic's documents.
        documents: `{filename: text}`, e.g. `faq_content.DENTAL_DOCUMENTS`.

    Returns:
        The S3 keys written, in the same order as `documents`.
    """
    prefix = kb_source_prefix(clinic_id)
    client = s3_client()
    written: list[str] = []
    for filename, text in documents.items():
        key = f"{prefix}{filename}"
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )
        written.append(key)
    return written


# --------------------------------------------------------------------------
# Bedrock Agent: Knowledge Base ingestion
# --------------------------------------------------------------------------


def start_kb_ingestion(knowledge_base_id: str) -> str:
    """Start an ingestion job so newly uploaded documents become retrievable.

    `agent_stack.py` wires an S3 data source with no auto-sync trigger, so
    uploading a document alone does not make `tools.faq.query_faq` see it
    -- an ingestion job has to run first. There is exactly one data source
    per clinic Knowledge Base (`agent_stack.py`'s `_build_clinic_knowledge_base`),
    so this looks it up rather than taking a second id as an argument --
    one less id for a caller of this function to get from a CDK output.

    Args:
        knowledge_base_id: The clinic's Knowledge Base id, from
            `$CLINICPILOT_KB_ID_...` (`tools.faq.knowledge_base_id_env_var`).

    Returns:
        The started ingestion job's id.

    Raises:
        ConfigurationError: If the Knowledge Base has no data source --
            it would mean `agent_stack.py` was not deployed as expected.
    """
    client = bedrock_agent_client()
    sources = client.list_data_sources(knowledgeBaseId=knowledge_base_id).get(
        "dataSourceSummaries", []
    )
    if not sources:
        raise ConfigurationError(
            f"Knowledge Base {knowledge_base_id!r} has no data source configured."
        )
    data_source_id = sources[0]["dataSourceId"]
    response = client.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id
    )
    return response["ingestionJob"]["ingestionJobId"]


def resolve_knowledge_base_id(clinic_id: str) -> str:
    """One clinic's deployed Knowledge Base id, or a `ConfigurationError`.

    Thin wrapper over `tools.faq.knowledge_base_id_env_var` so `run_seed.py`
    reads the same environment variable `query_faq` will at call time,
    rather than deriving a second version of the same name.
    """
    env_var = knowledge_base_id_env_var(clinic_id)
    configured = os.environ.get(env_var, "").strip()
    if not configured:
        raise ConfigurationError(
            f"{env_var} is not set; copy the matching 'KnowledgeBaseId'"
            " output from the Agent stack's `cdk deploy`."
        )
    return configured


# --------------------------------------------------------------------------
# Cognito: staff demo accounts
# --------------------------------------------------------------------------

# Read from `backend/lambda/dashboard_api.py` via `importlib` rather than
# hardcoded a third time: that module already carries the one true spelling
# `custom:clinic_id`, and `lambda` is a Python keyword so it cannot be
# imported with an ordinary `import` statement (`architecture.md` ->
# System Boundaries).
@lru_cache(maxsize=1)
def _clinic_id_claim() -> str:
    import importlib  # noqa: PLC0415 - deliberate lazy import, see docstring

    dashboard_api = importlib.import_module("lambda.dashboard_api")
    return dashboard_api.CLINIC_ID_CLAIM


def ensure_staff_account(
    user_pool_id: str, *, email: str, password: str, clinic_id: str
) -> str:
    """Create one staff demo account, or leave an existing one as it is.

    Idempotent by design -- re-running the seed script against an
    environment that already has this account must not fail the whole
    run. An existing account's `custom:clinic_id` and password are left
    untouched: a staff member who changed their password at the demo must
    not have it silently reset by a second seed run.

    Args:
        user_pool_id: The staff user pool id (`staff_user_pool_id`).
        email: The account's email, and its Cognito username.
        password: The permanent password to set on a newly created
            account (`staff_demo_password`).
        clinic_id: Written to the account's `custom:clinic_id` attribute
            -- what every dashboard API route scopes the caller to
            (`architecture.md` -> Auth and Access Model).

    Returns:
        `"created"` or `"already_exists"`.
    """
    client = cognito_client()
    try:
        client.admin_create_user(
            UserPoolId=user_pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                # `_clinic_id_claim()` is already `"custom:clinic_id"` --
                # `AdminCreateUser` takes a custom attribute's name with
                # the same `custom:` prefix the token claim carries, so
                # this is the one spelling used both here and by
                # `dashboard_api._clinic_id_from` reading it back.
                {"Name": _clinic_id_claim(), "Value": clinic_id},
            ],
            MessageAction="SUPPRESS",
        )
    except client.exceptions.UsernameExistsException:
        return "already_exists"

    client.admin_set_user_password(
        UserPoolId=user_pool_id, Username=email, Password=password, Permanent=True
    )
    return "created"
