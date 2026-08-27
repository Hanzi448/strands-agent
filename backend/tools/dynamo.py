"""Table handles for the four DynamoDB tables.

The one place in the tool layer that knows a table's physical name. Every
other module asks for `appointments_table()` and never builds a name or a
boto3 client itself, so a rename is a change here and in
`backend/infra/config.py` -- nowhere else.

Names are read from the environment, which is how a Lambda, the AgentCore
Runtime container, and a `seed/` script all get told which deployment
they are pointed at. If a variable is unset the name is derived from the
same `{project_prefix}-{environment}-{concern}` scheme
`backend/infra/config.py` uses, so a local script needs at most
``CLINICPILOT_ENV`` set rather than four separate table names.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from .errors import ConfigurationError

if TYPE_CHECKING:  # pragma: no cover - import cost avoided at runtime
    from mypy_boto3_dynamodb.service_resource import Table
else:  # boto3 resources are dynamically generated and have no importable type.
    Table = object

# Table-name environment variables. The CDK stacks set these on every
# Lambda and on the agent runtime; `backend/infra/` reads the same names
# when it wires them, so this tuple is the contract between the two.
CLINICS_TABLE_ENV: Final[str] = "CLINICPILOT_CLINICS_TABLE"
PATIENTS_TABLE_ENV: Final[str] = "CLINICPILOT_PATIENTS_TABLE"
APPOINTMENTS_TABLE_ENV: Final[str] = "CLINICPILOT_APPOINTMENTS_TABLE"
ESCALATIONS_TABLE_ENV: Final[str] = "CLINICPILOT_ESCALATIONS_TABLE"

# Fallback name construction, mirroring `backend/infra/config.py`. Kept in
# sync by `backend/tests/test_schema_matches_infra.py`.
PROJECT_PREFIX_ENV: Final[str] = "CLINICPILOT_PROJECT_PREFIX"
ENVIRONMENT_ENV: Final[str] = "CLINICPILOT_ENV"
DEFAULT_PROJECT_PREFIX: Final[str] = "clinicpilot"
DEFAULT_ENVIRONMENT: Final[str] = "dev"

# The four tables, by their resource-name suffix, mapped to the
# environment variable that can override the derived name. Also the
# allow-list: `table_name` accepts nothing outside these keys.
_TABLE_ENV_BY_CONCERN: Final[dict[str, str]] = {
    "clinics": CLINICS_TABLE_ENV,
    "patients": PATIENTS_TABLE_ENV,
    "appointments": APPOINTMENTS_TABLE_ENV,
    "escalations": ESCALATIONS_TABLE_ENV,
}


def table_name(concern: str) -> str:
    """Resolve one table's physical name for the current deployment.

    Args:
        concern: One of ``clinics``, ``patients``, ``appointments``,
            ``escalations``.

    Returns:
        The environment variable's value if set, otherwise
        ``{project_prefix}-{environment}-{concern}``.

    Raises:
        ConfigurationError: If `concern` is not one of the four tables.
            A deployment/programming fault, never a patient-request one.
    """
    try:
        env_var = _TABLE_ENV_BY_CONCERN[concern]
    except KeyError as exc:
        known = ", ".join(_TABLE_ENV_BY_CONCERN)
        raise ConfigurationError(
            f"Unknown table {concern!r}; expected one of: {known}."
        ) from exc
    configured = os.environ.get(env_var, "").strip()
    if configured:
        return configured
    prefix = os.environ.get(PROJECT_PREFIX_ENV, "").strip() or DEFAULT_PROJECT_PREFIX
    environment = os.environ.get(ENVIRONMENT_ENV, "").strip() or DEFAULT_ENVIRONMENT
    return f"{prefix}-{environment}-{concern}"


@lru_cache(maxsize=1)
def _dynamodb_resource():  # noqa: ANN202 - boto3 resources have no public type
    """The process-wide boto3 DynamoDB resource.

    Cached because creating a boto3 resource is expensive enough to matter
    on a Lambda cold start and a voice turn. This is a client handle, not
    session state -- `code-standards.md` -> Python forbids the latter at
    module level, and nothing per-patient is stored here.

    boto3 is imported lazily so that importing `tools.schema` or
    `tools.validation` (pure stdlib) stays possible in a context without
    the AWS SDK installed.
    """
    import boto3  # noqa: PLC0415 - deliberate lazy import, see docstring

    return boto3.resource("dynamodb")


@lru_cache(maxsize=len(_TABLE_ENV_BY_CONCERN))
def get_table(concern: str) -> Table:
    """Return the boto3 `Table` handle for one of the four tables.

    Args:
        concern: One of ``clinics``, ``patients``, ``appointments``,
            ``escalations``.

    Returns:
        A boto3 DynamoDB `Table` resource bound to the resolved name.
        Cached per concern: the handle is stateless and reusable.

    Raises:
        ConfigurationError: If `concern` is not one of the four tables.
    """
    return _dynamodb_resource().Table(table_name(concern))


def clinics_table() -> Table:
    """The `Clinics` table: per-tenant config, keyed by `clinic_id`."""
    return get_table("clinics")


def patients_table() -> Table:
    """The `Patients` table: demo profiles, plus the `by-phone` index."""
    return get_table("patients")


def appointments_table() -> Table:
    """The `Appointments` table, plus the `by-start-time`/`by-patient` indexes."""
    return get_table("appointments")


def escalations_table() -> Table:
    """The `Escalations` table, plus the `by-created-at` index."""
    return get_table("escalations")


def reset_cached_clients() -> None:
    """Drop the cached resource and table handles.

    For tests and for seed scripts that change the target environment
    variables mid-process; production code never needs it.
    """
    get_table.cache_clear()
    _dynamodb_resource.cache_clear()
