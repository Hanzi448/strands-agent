"""The system boundary, as a test rather than a convention.

`architecture.md` -> System Boundaries: `backend/tools/` (and the
Lambda handlers that call the same functions) must not depend on Strands
or AgentCore -- a data-mutating Lambda has to install without the agent
framework, and business logic has to be reachable from both the live
agent and the background job unchanged. Nothing enforced that before;
`agents/memory.py` adds a second framework package to the tree, which
is the moment the guard starts earning its keep.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# The agent framework packages the tool layer must never import.
FORBIDDEN_ROOTS = frozenset({"strands", "bedrock_agentcore"})

# The packages that must stay framework-free.
GUARDED_DIRS = ("tools", "lambda")


def _imported_roots(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [(node.module or "").split(".")[0]] if node.module else ["."]
    return []


def test_the_tool_layer_imports_no_agent_framework() -> None:
    for directory in GUARDED_DIRS:
        for path in sorted((BACKEND / directory).glob("*.py")):
            # `utf-8-sig` strips a BOM if one is present: some files in
            # this tree were saved with one, and it is not an import.
            tree = ast.parse(
                path.read_text(encoding="utf-8-sig"), filename=str(path)
            )
            for node in ast.walk(tree):
                for root in _imported_roots(node):
                    assert root not in FORBIDDEN_ROOTS, (
                        f"{directory}/{path.name} imports {root!r}: business logic"
                        " must stay reachable without the agent framework"
                    )
