"""Tests for table-name resolution.

Only the naming layer is exercised: `get_table` needs credentials and a
live boto3 resource, and is covered when the first tool that queries is
implemented. Naming is worth testing on its own because a wrong table
name fails at runtime in a deployed Lambda, not here.
"""

from __future__ import annotations

import pytest

from tools.dynamo import (
    APPOINTMENTS_TABLE_ENV,
    CLINICS_TABLE_ENV,
    ENVIRONMENT_ENV,
    ESCALATIONS_TABLE_ENV,
    PATIENTS_TABLE_ENV,
    PROJECT_PREFIX_ENV,
    table_name,
)
from tools.errors import ConfigurationError

ALL_TABLE_ENVS = (
    CLINICS_TABLE_ENV,
    PATIENTS_TABLE_ENV,
    APPOINTMENTS_TABLE_ENV,
    ESCALATIONS_TABLE_ENV,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run each test against an unconfigured process, whatever the shell has."""
    for name in (*ALL_TABLE_ENVS, PROJECT_PREFIX_ENV, ENVIRONMENT_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("concern", "expected"),
    [
        ("clinics", "clinicpilot-dev-clinics"),
        ("patients", "clinicpilot-dev-patients"),
        ("appointments", "clinicpilot-dev-appointments"),
        ("escalations", "clinicpilot-dev-escalations"),
    ],
)
def test_names_default_to_the_projects_naming_scheme(concern, expected) -> None:
    assert table_name(concern) == expected


def test_environment_variable_selects_the_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENVIRONMENT_ENV, "prod")
    assert table_name("appointments") == "clinicpilot-prod-appointments"


def test_project_prefix_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROJECT_PREFIX_ENV, "renamed")
    assert table_name("clinics") == "renamed-dev-clinics"


def test_explicit_table_name_wins_over_the_derived_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CDK stacks set the explicit variables; they must take precedence."""
    monkeypatch.setenv(ENVIRONMENT_ENV, "prod")
    monkeypatch.setenv(APPOINTMENTS_TABLE_ENV, "explicit-table")
    assert table_name("appointments") == "explicit-table"


def test_blank_environment_variable_falls_back_rather_than_naming_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset variable often arrives as an empty string, not as absent."""
    monkeypatch.setenv(APPOINTMENTS_TABLE_ENV, "   ")
    assert table_name("appointments") == "clinicpilot-dev-appointments"


def test_unknown_table_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="appointments"):
        table_name("appointment")
