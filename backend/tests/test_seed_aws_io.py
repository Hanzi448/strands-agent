"""Tests for `seed.aws_io`: the boto3 calls seeding needs beyond `tools.dynamo`.

No credentials, no moto, no network -- every AWS-facing function is
exercised against a hand-rolled fake substituted for its `*_client()`
accessor, the same shape `test_booking.py`'s `tables` fixture uses for
`scheduling.clinics_table`.
"""

from __future__ import annotations

from typing import Any

import pytest
from tools.errors import ConfigurationError

from seed import aws_io


class _UsernameExistsException(Exception):
    """Stands in for a real boto3 client's dynamically generated exception."""


class _Exceptions:
    UsernameExistsException = _UsernameExistsException


class FakeS3Client:
    def __init__(self) -> None:
        self.put_objects: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_objects.append(kwargs)
        return {}


class FakeBedrockAgentClient:
    def __init__(self, *, data_sources: list[dict[str, Any]] | None = None) -> None:
        self._data_sources = data_sources if data_sources is not None else [
            {"dataSourceId": "ds-1"}
        ]
        self.list_calls: list[str] = []
        self.started: list[dict[str, Any]] = []

    def list_data_sources(self, *, knowledgeBaseId: str) -> dict[str, Any]:  # noqa: N803
        self.list_calls.append(knowledgeBaseId)
        return {"dataSourceSummaries": self._data_sources}

    def start_ingestion_job(self, **kwargs: Any) -> dict[str, Any]:
        self.started.append(kwargs)
        return {"ingestionJob": {"ingestionJobId": "job-1"}}


class FakeCognitoClient:
    def __init__(self, *, existing_usernames: frozenset[str] = frozenset()) -> None:
        self._existing = set(existing_usernames)
        self.created: list[dict[str, Any]] = []
        self.password_sets: list[dict[str, Any]] = []
        self.exceptions = _Exceptions

    def admin_create_user(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["Username"] in self._existing:
            raise self.exceptions.UsernameExistsException()
        self.created.append(kwargs)
        self._existing.add(kwargs["Username"])
        return {}

    def admin_set_user_password(self, **kwargs: Any) -> dict[str, Any]:
        self.password_sets.append(kwargs)
        return {}


# --------------------------------------------------------------------------
# Naming
# --------------------------------------------------------------------------


def test_kb_bucket_name_uses_the_env_var_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(aws_io.KB_BUCKET_ENV, "custom-bucket")
    assert aws_io.kb_bucket_name() == "custom-bucket"


def test_kb_bucket_name_derives_the_default_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(aws_io.KB_BUCKET_ENV, raising=False)
    monkeypatch.delenv(aws_io._PROJECT_PREFIX_ENV, raising=False)
    monkeypatch.delenv(aws_io._ENVIRONMENT_ENV, raising=False)
    assert aws_io.kb_bucket_name() == "clinicpilot-dev-kb"


def test_kb_source_prefix_matches_the_architecture_doc_shape() -> None:
    assert aws_io.kb_source_prefix("clinic-dental") == "kb/clinic-dental/"


def test_staff_user_pool_id_requires_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(aws_io.STAFF_USER_POOL_ID_ENV, raising=False)
    with pytest.raises(ConfigurationError):
        aws_io.staff_user_pool_id()


def test_staff_user_pool_id_reads_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(aws_io.STAFF_USER_POOL_ID_ENV, "us-east-1_Abc123")
    assert aws_io.staff_user_pool_id() == "us-east-1_Abc123"


def test_staff_demo_password_requires_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(aws_io.STAFF_DEMO_PASSWORD_ENV, raising=False)
    with pytest.raises(ConfigurationError):
        aws_io.staff_demo_password()


def test_resolve_knowledge_base_id_requires_the_matching_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLINICPILOT_KB_ID_CLINIC_DENTAL", raising=False)
    with pytest.raises(ConfigurationError):
        aws_io.resolve_knowledge_base_id("clinic-dental")


def test_resolve_knowledge_base_id_reads_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLINICPILOT_KB_ID_CLINIC_DENTAL", "kb-123")
    assert aws_io.resolve_knowledge_base_id("clinic-dental") == "kb-123"


# --------------------------------------------------------------------------
# S3
# --------------------------------------------------------------------------


def test_upload_faq_documents_writes_every_document_under_the_clinic_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr(aws_io, "s3_client", lambda: fake)

    keys = aws_io.upload_faq_documents(
        "my-bucket", "clinic-dental", {"pricing.txt": "hello", "policies.txt": "world"}
    )

    assert keys == ["kb/clinic-dental/pricing.txt", "kb/clinic-dental/policies.txt"]
    assert [call["Key"] for call in fake.put_objects] == keys
    assert all(call["Bucket"] == "my-bucket" for call in fake.put_objects)
    assert fake.put_objects[0]["Body"] == b"hello"


# --------------------------------------------------------------------------
# Bedrock Agent
# --------------------------------------------------------------------------


def test_start_kb_ingestion_starts_the_clinics_only_data_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeBedrockAgentClient(data_sources=[{"dataSourceId": "ds-42"}])
    monkeypatch.setattr(aws_io, "bedrock_agent_client", lambda: fake)

    job_id = aws_io.start_kb_ingestion("kb-1")

    assert job_id == "job-1"
    assert fake.list_calls == ["kb-1"]
    assert fake.started == [{"knowledgeBaseId": "kb-1", "dataSourceId": "ds-42"}]


def test_start_kb_ingestion_fails_loudly_with_no_data_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeBedrockAgentClient(data_sources=[])
    monkeypatch.setattr(aws_io, "bedrock_agent_client", lambda: fake)

    with pytest.raises(ConfigurationError):
        aws_io.start_kb_ingestion("kb-1")
    assert fake.started == []


# --------------------------------------------------------------------------
# Cognito
# --------------------------------------------------------------------------


def test_ensure_staff_account_creates_a_new_account_with_the_clinic_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeCognitoClient()
    monkeypatch.setattr(aws_io, "cognito_client", lambda: fake)

    outcome = aws_io.ensure_staff_account(
        "pool-1", email="staff+clinic-dental@clinicpilot.demo", password="Sup3rSecret!", clinic_id="clinic-dental"
    )

    assert outcome == "created"
    assert len(fake.created) == 1
    attributes = {a["Name"]: a["Value"] for a in fake.created[0]["UserAttributes"]}
    assert attributes["custom:clinic_id"] == "clinic-dental"
    assert attributes["email"] == "staff+clinic-dental@clinicpilot.demo"
    assert fake.created[0]["MessageAction"] == "SUPPRESS"
    assert fake.password_sets == [
        {
            "UserPoolId": "pool-1",
            "Username": "staff+clinic-dental@clinicpilot.demo",
            "Password": "Sup3rSecret!",
            "Permanent": True,
        }
    ]


def test_ensure_staff_account_leaves_an_existing_account_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = "staff+clinic-dental@clinicpilot.demo"
    fake = FakeCognitoClient(existing_usernames=frozenset({email}))
    monkeypatch.setattr(aws_io, "cognito_client", lambda: fake)

    outcome = aws_io.ensure_staff_account(
        "pool-1", email=email, password="Sup3rSecret!", clinic_id="clinic-dental"
    )

    assert outcome == "already_exists"
    assert fake.created == []
    # Not re-set: an existing account's password must survive a re-run.
    assert fake.password_sets == []
