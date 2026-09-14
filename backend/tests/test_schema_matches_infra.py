"""Guards the duplication between `backend/tools/` and `backend/infra/`.

The tool layer cannot import the CDK app (that would make business logic
depend on `aws-cdk-lib`, and the two run in different virtual
environments), so key attribute names, index names, and the table-naming
scheme are written in both places. A drift between them does not raise:
DynamoDB answers a query against a misspelled key or a missing index with
an empty result or a runtime failure inside a deployed Lambda. These
tests turn that silent drift into a failing test here.

`backend/infra/data_stack.py` is read with `ast` rather than imported,
since importing it would require `aws-cdk-lib`. `backend/infra/config.py`
is pure stdlib and is imported outright, so the naming scheme itself --
not just its default values -- is compared.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tools import dynamo, faq, schema

from seed import aws_io

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra"
DATA_STACK_PATH = INFRA_DIR / "data_stack.py"
AGENT_STACK_PATH = INFRA_DIR / "agent_stack.py"
CONFIG_PATH = INFRA_DIR / "config.py"

# Constants that carry the same name on both sides. Anything DynamoDB
# itself enforces -- key attribute names and index names -- belongs here.
SHARED_CONSTANTS = (
    "CLINIC_ID",
    "PATIENT_ID",
    "APPOINTMENT_ID",
    "ESCALATION_ID",
    "STARTS_AT",
    "CREATED_AT",
    "PHONE",
    "CLINIC_PATIENT",
    "APPOINTMENTS_BY_START_TIME_INDEX",
    "APPOINTMENTS_BY_PATIENT_INDEX",
    "PATIENTS_BY_PHONE_INDEX",
    "ESCALATIONS_BY_CREATED_AT_INDEX",
)


def _module_level_strings(path: Path) -> dict[str, str]:
    """Extract module-level ``NAME = "value"`` assignments without importing."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = node.value.value
    return found


def _load_infra_config() -> ModuleType:
    """Import `backend/infra/config.py` by path (it has no CDK dependency)."""
    spec = importlib.util.spec_from_file_location("infra_config", CONFIG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def data_stack_constants() -> dict[str, str]:
    return _module_level_strings(DATA_STACK_PATH)


@pytest.mark.parametrize("name", SHARED_CONSTANTS)
def test_key_and_index_names_match_the_data_stack(name, data_stack_constants) -> None:
    assert name in data_stack_constants, (
        f"{name} is defined in tools/schema.py but no longer in "
        f"{DATA_STACK_PATH.name}."
    )
    assert data_stack_constants[name] == getattr(schema, name), (
        f"{name} disagrees between tools/schema.py and {DATA_STACK_PATH.name}: "
        f"{getattr(schema, name)!r} vs {data_stack_constants[name]!r}."
    )


def test_table_names_match_the_cdk_naming_scheme(monkeypatch) -> None:
    """`table_name` must derive exactly what the CDK physically deploys.

    Compared against `ProjectConfig.resource_name` itself rather than
    against a hardcoded string, so a change to the scheme is caught even
    if both default values stay the same.
    """
    for env_var in (
        dynamo.CLINICS_TABLE_ENV,
        dynamo.PATIENTS_TABLE_ENV,
        dynamo.APPOINTMENTS_TABLE_ENV,
        dynamo.ESCALATIONS_TABLE_ENV,
        dynamo.PROJECT_PREFIX_ENV,
        dynamo.ENVIRONMENT_ENV,
    ):
        monkeypatch.delenv(env_var, raising=False)

    config = _load_infra_config().ProjectConfig()
    for concern in ("clinics", "patients", "appointments", "escalations"):
        assert dynamo.table_name(concern) == config.resource_name(concern)


def test_naming_defaults_match_the_cdk_config() -> None:
    config_module = _load_infra_config()
    assert dynamo.DEFAULT_PROJECT_PREFIX == config_module.DEFAULT_PROJECT_PREFIX
    assert dynamo.DEFAULT_ENVIRONMENT == config_module.DEFAULT_ENVIRONMENT


def test_kb_id_env_prefix_matches_the_agent_stack() -> None:
    """`agent_stack.py` duplicates `faq.KB_ID_ENV_PREFIX` for the reason
    `data_stack.py` duplicates the key/index names: it needs `aws-cdk-lib`,
    which `tools/faq.py` must never depend on. A drift here would mean the
    runtime's environment variable and `knowledge_base_id_env_var`'s lookup
    disagree silently -- every clinic's FAQ tool would fail closed with
    "no Knowledge Base configured" against a real deploy.
    """
    agent_stack_constants = _module_level_strings(AGENT_STACK_PATH)
    assert "KB_ID_ENV_PREFIX" in agent_stack_constants, (
        f"KB_ID_ENV_PREFIX is defined in tools/faq.py but no longer in "
        f"{AGENT_STACK_PATH.name}."
    )
    assert agent_stack_constants["KB_ID_ENV_PREFIX"] == faq.KB_ID_ENV_PREFIX, (
        "KB_ID_ENV_PREFIX disagrees between tools/faq.py and "
        f"{AGENT_STACK_PATH.name}: {faq.KB_ID_ENV_PREFIX!r} vs "
        f"{agent_stack_constants['KB_ID_ENV_PREFIX']!r}."
    )


def test_memory_id_env_var_matches_the_agent_stack() -> None:
    """The env var `agent_stack.py` sets must be the one `agents/memory.py`
    reads -- the same duplicated-constant discipline `KB_ID_ENV_PREFIX`
    already follows. A drift here would mean the runtime injects a memory
    id the agent code never looks for, and memory silently stays off in
    the deployed container while every offline test passes.
    """
    from agents import memory

    agent_stack_constants = _module_level_strings(AGENT_STACK_PATH)
    assert "MEMORY_ID_ENV" in agent_stack_constants, (
        f"MEMORY_ID_ENV is defined in agents/memory.py but no longer in "
        f"{AGENT_STACK_PATH.name}."
    )
    assert agent_stack_constants["MEMORY_ID_ENV"] == memory.MEMORY_ID_ENV, (
        "MEMORY_ID_ENV disagrees between agents/memory.py and "
        f"{AGENT_STACK_PATH.name}: {memory.MEMORY_ID_ENV!r} vs "
        f"{agent_stack_constants['MEMORY_ID_ENV']!r}."
    )


def test_memory_namespace_template_matches_the_agent_stack() -> None:
    """The namespace the strategy writes to (CDK, `{actorId}`/`{sessionId}`
    resolved by the service) and the namespace path the runtime retrieves
    by prefix (`agents/memory.py`, `{actor_id}` filled client-side) must
    agree as write-and-read halves of one layout, or summaries land where
    retrieval never looks -- every caller a first-time caller, forever,
    with no error anywhere.

    Two invariants, the first learned live (2026-09-14 deploy failure):
    the service **rejects a SUMMARIZATION namespace without `{sessionId}`**
    ("Memory strategy ... is of Summarization type requiring {sessionId}
    as a mandatory part of namespace") -- `cdk synth` cannot catch this,
    only `cdk deploy` can. The second is the drift guard this test has
    always carried: the client's actor-scoped retrieval prefix must be a
    path prefix of the strategy's session-scoped write namespace, so
    retrieval sees every session's summary under the actor.
    """
    from agents import memory

    agent_stack_constants = _module_level_strings(AGENT_STACK_PATH)
    assert "MEMORY_NAMESPACE_TEMPLATE" in agent_stack_constants, (
        f"MEMORY_NAMESPACE_TEMPLATE is defined in agents/memory.py but no"
        f" longer in {AGENT_STACK_PATH.name}."
    )
    template = agent_stack_constants["MEMORY_NAMESPACE_TEMPLATE"]
    assert "{sessionId}" in template, (
        "The AgentCore service refuses to create a SUMMARIZATION strategy"
        " whose namespace has no {sessionId} in it (deploy failure,"
        " 2026-09-14) -- the write namespace must be session-scoped,"
        f" and {AGENT_STACK_PATH.name}'s is {template!r}."
    )
    assert "{actorId}" in template, (
        "A strategy namespace without {actorId} is not actor-scoped: one"
        " patient's summaries would be every other patient's retrieval"
        f" (`architecture.md` -> Invariants #1). {AGENT_STACK_PATH.name}'s"
        f" is {template!r}."
    )
    normalised = template.replace("{actorId}", "{actor_id}").replace(
        "{sessionId}", "{session_id}"
    )
    assert normalised.startswith(memory.NAMESPACE_TEMPLATE), (
        "The strategy writes into session-scoped namespaces under the"
        " actor, but `agents/memory.py` retrieves by a path that is not"
        " their prefix -- summaries would land where retrieval never"
        f" looks. {memory.NAMESPACE_TEMPLATE!r} vs the write template"
        f" {template!r}."
    )


def test_kb_bucket_prefix_matches_the_data_stack() -> None:
    """`seed/aws_io.py` duplicates `data_stack.py`'s `KB_BUCKET_PREFIX` for
    the same reason this file's other tests exist: `seed/` cannot import
    `aws_cdk` either. A drift here would upload FAQ documents to a prefix
    no clinic's Bedrock data source is actually watching.
    """
    data_stack_constants = _module_level_strings(DATA_STACK_PATH)
    assert data_stack_constants["KB_BUCKET_PREFIX"] == aws_io.KB_BUCKET_PREFIX, (
        "KB_BUCKET_PREFIX disagrees between seed/aws_io.py and "
        f"{DATA_STACK_PATH.name}: {aws_io.KB_BUCKET_PREFIX!r} vs "
        f"{data_stack_constants['KB_BUCKET_PREFIX']!r}."
    )


def test_kb_bucket_name_matches_the_cdk_naming_scheme(monkeypatch) -> None:
    """`aws_io.kb_bucket_name`'s derived default must match what
    `backend/infra/config.py`'s `resource_name("kb")` physically deploys,
    the same property `test_table_names_match_the_cdk_naming_scheme`
    checks for the four tables.
    """
    for env_var in (aws_io.KB_BUCKET_ENV, aws_io._PROJECT_PREFIX_ENV, aws_io._ENVIRONMENT_ENV):
        monkeypatch.delenv(env_var, raising=False)

    config = _load_infra_config().ProjectConfig()
    assert aws_io.kb_bucket_name() == config.resource_name("kb")
