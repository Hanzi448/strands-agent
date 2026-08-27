"""Agent stack: Bedrock AgentCore Runtime/Memory and the Bedrock Knowledge Base.

Skeleton only -- no resources yet. Populated once the agents themselves
exist (`progress-tracker.md` Next Up #4-#6).

Planned contents, per `architecture.md` -> Stack:
  - AgentCore Runtime hosting the Orchestrator agent (which invokes the
    Scheduling/FAQ/Escalation sub-agents in-process as tools -- they are
    never deployed as separately addressable endpoints, per
    `architecture.md` -> Invariants #2).
  - AgentCore Memory for per-patient session continuity.
  - Bedrock Knowledge Base over the data stack's KB bucket, retrieval
    filtered by `clinic_id`.
  - Execution role scoped to the specific tables/buckets/models used.

Reference for the AgentCore wiring: the vendored TypeScript
`vendor/sample-nova-sonic-websocket-agentcore/cdk/lib/runtime-stack.ts`
(read-only reference -- our CDK stays Python).
"""

from __future__ import annotations

from aws_cdk import Stack
from constructs import Construct

from config import ProjectConfig


class AgentStack(Stack):
    """AgentCore Runtime, AgentCore Memory, and the per-clinic Knowledge Base."""

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
