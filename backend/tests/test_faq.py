"""Tests for `query_faq`.

Two properties carry the weight here.

*The Knowledge Base id is resolved per clinic, from configuration, never
guessed.* Each demo clinic reads its own environment variable
(`knowledge_base_id_env_var`); a clinic with nothing set is a
`ConfigurationError`, not a silent fall-through to another clinic's index
or an empty result that looks like "no FAQ matched".

*Retrieval passages come back as facts, not phrasing.* The fake client
below returns Bedrock's own `retrieve` response shape, so the module is
proved to read `retrievalResults[].content.text` rather than a shape it
was never given; an empty result list comes back as `found: False`
rather than raised, exactly as `check_availability` returns an empty slot
list rather than failing.
"""

from __future__ import annotations

from typing import Any

import pytest

from tools import faq
from tools.errors import ConfigurationError, ValidationError

DENTAL_ID = "clinic-dental"
COSMETIC_ID = "clinic-cosmetic"
DENTAL_KB_ENV = "CLINICPILOT_KB_ID_CLINIC_DENTAL"
COSMETIC_KB_ENV = "CLINICPILOT_KB_ID_CLINIC_COSMETIC"


class FakeBedrockAgentRuntimeClient:
    """Stands in for the boto3 `bedrock-agent-runtime` client.

    Records every `retrieve` call it was given and returns a canned
    response in Bedrock's own shape, so the module is exercised against
    the real response structure rather than a simplified stand-in.
    """

    def __init__(self, *passages: str) -> None:
        self.passages = passages
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "retrievalResults": [
                {"content": {"text": text, "type": "TEXT"}, "score": 0.9 - index * 0.1}
                for index, text in enumerate(self.passages)
            ]
        }


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run each test against an unconfigured process, whatever the shell has."""
    monkeypatch.delenv(DENTAL_KB_ENV, raising=False)
    monkeypatch.delenv(COSMETIC_KB_ENV, raising=False)
    faq._bedrock_agent_runtime_client.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """Point the module at a fake client and give the dental clinic a KB id."""

    def install(*passages: str) -> FakeBedrockAgentRuntimeClient:
        fake = FakeBedrockAgentRuntimeClient(*passages)
        monkeypatch.setattr(faq, "_bedrock_agent_runtime_client", lambda: fake)
        monkeypatch.setenv(DENTAL_KB_ENV, "kb-dental-123")
        return fake

    return install


# --------------------------------------------------------------------------
# Knowledge Base id resolution
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("clinic_id", "expected"),
    [
        ("clinic-dental", "CLINICPILOT_KB_ID_CLINIC_DENTAL"),
        ("clinic-cosmetic", "CLINICPILOT_KB_ID_CLINIC_COSMETIC"),
        ("clinic_underscored", "CLINICPILOT_KB_ID_CLINIC_UNDERSCORED"),
    ],
)
def test_knowledge_base_env_var_is_derived_from_the_clinic_id(clinic_id, expected) -> None:
    assert faq.knowledge_base_id_env_var(clinic_id) == expected


def test_unconfigured_clinic_is_a_configuration_error(client) -> None:
    client("A cleaning takes about 30 minutes.")
    with pytest.raises(ConfigurationError, match=COSMETIC_KB_ENV):
        faq.query_faq(COSMETIC_ID, "How long does a cleaning take?")


def test_blank_environment_variable_is_also_unconfigured(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client("A cleaning takes about 30 minutes.")
    monkeypatch.setenv(DENTAL_KB_ENV, "   ")
    with pytest.raises(ConfigurationError, match=DENTAL_KB_ENV):
        faq.query_faq(DENTAL_ID, "How long does a cleaning take?")


def test_each_clinic_reads_its_own_id(client, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = client("A cleaning takes about 30 minutes.")
    monkeypatch.setenv(COSMETIC_KB_ENV, "kb-cosmetic-456")

    faq.query_faq(DENTAL_ID, "How long does a cleaning take?")
    faq.query_faq(COSMETIC_ID, "How long does a cleaning take?")

    assert fake.calls[0]["knowledgeBaseId"] == "kb-dental-123"
    assert fake.calls[1]["knowledgeBaseId"] == "kb-cosmetic-456"


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------


def test_passages_are_returned_closest_match_first(client) -> None:
    client("A cleaning takes about 30 minutes.", "We accept most major insurance plans.")

    result = faq.query_faq(DENTAL_ID, "How long does a cleaning take, and do you take insurance?")

    assert result["found"] is True
    assert result["passages"] == [
        {"text": "A cleaning takes about 30 minutes."},
        {"text": "We accept most major insurance plans."},
    ]
    assert result["question"] == "How long does a cleaning take, and do you take insurance?"


def test_no_match_is_a_normal_answer_not_an_error(client) -> None:
    fake = client()

    result = faq.query_faq(DENTAL_ID, "Do you offer valet parking?")

    assert result == {
        "question": "Do you offer valet parking?",
        "passages": [],
        "found": False,
    }
    assert fake.calls, "the Knowledge Base was still queried"


def test_a_result_with_no_readable_text_is_dropped(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class OddShapedClient(FakeBedrockAgentRuntimeClient):
        def retrieve(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return {
                "retrievalResults": [
                    {"content": {"text": "A real passage."}},
                    {"content": {"type": "IMAGE"}},
                    {"content": {"text": "   "}},
                    {},
                ]
            }

    fake = OddShapedClient()
    monkeypatch.setattr(faq, "_bedrock_agent_runtime_client", lambda: fake)
    monkeypatch.setenv(DENTAL_KB_ENV, "kb-dental-123")

    result = faq.query_faq(DENTAL_ID, "What is your cancellation policy?")

    assert result["passages"] == [{"text": "A real passage."}]


def test_max_results_is_forwarded_to_the_vector_search(client) -> None:
    fake = client("A cleaning takes about 30 minutes.")

    faq.query_faq(DENTAL_ID, "How long does a cleaning take?", max_results=7)

    search_config = fake.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert search_config["numberOfResults"] == 7


def test_max_results_defaults_when_not_given(client) -> None:
    fake = client("A cleaning takes about 30 minutes.")

    faq.query_faq(DENTAL_ID, "How long does a cleaning take?")

    search_config = fake.calls[0]["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert search_config["numberOfResults"] == faq.DEFAULT_MAX_RESULTS


def test_max_results_out_of_range_is_a_validation_error(client) -> None:
    client("A cleaning takes about 30 minutes.")
    with pytest.raises(ValidationError, match="max_results"):
        faq.query_faq(DENTAL_ID, "How long does a cleaning take?", max_results=999)


# --------------------------------------------------------------------------
# The tenant boundary and other validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
def test_blank_clinic_id_is_refused_before_any_query(client, clinic_id) -> None:
    fake = client("A cleaning takes about 30 minutes.")
    with pytest.raises(ValidationError, match="clinic_id"):
        faq.query_faq(clinic_id, "How long does a cleaning take?")
    assert not fake.calls


@pytest.mark.parametrize("question", ["", "   ", None])
def test_blank_question_is_refused_before_any_query(client, question) -> None:
    fake = client("A cleaning takes about 30 minutes.")
    with pytest.raises(ValidationError, match="question"):
        faq.query_faq(DENTAL_ID, question)
    assert not fake.calls


def test_clinic_id_is_validated_before_the_question(client) -> None:
    """A blank clinic_id must be the reported fault even when other args are also bad."""
    fake = client("A cleaning takes about 30 minutes.")
    with pytest.raises(ValidationError, match="clinic_id"):
        faq.query_faq("", None, max_results=-1)
    assert not fake.calls
