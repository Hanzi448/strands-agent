"""Agent stack: the AgentCore Runtime and the per-clinic Knowledge Base.

Two concerns in one stack rather than two, because AgentCore Runtime is
what actually *calls* the Knowledge Base (through `tools/faq.py`) and the
runtime's execution role needs each Knowledge Base's ARN to grant
`bedrock:Retrieve` on -- splitting them would mean this stack importing
the other's outputs across a stack boundary for no reason
`ai-workflow-rules.md` -> When to Split Work asks for (that rule splits
agent/tool *logic* from infrastructure, not one infra stack from another
infra stack that consumes its own resources).

This stack owns:
  - One Bedrock Knowledge Base per demo clinic (`config.DEMO_CLINIC_IDS`),
    each reading only that clinic's prefix in the data stack's
    `kb_bucket` (`data_stack.kb_source_prefix`). A separate Knowledge Base
    per clinic -- rather than one shared Knowledge Base with a
    `clinic_id` metadata filter -- is what makes
    `architecture.md` -> Invariants #1 hold structurally: a retrieval
    call is scoped to a clinic by which Knowledge Base id it is given,
    not by trusting a filter to be applied correctly.
  - The AgentCore Runtime that hosts `agents/agentcore_app.py`
    (`progress-tracker.md` Next Up #1), built from a container image
    asset over `backend/Dockerfile` -- the same "code first, deploy
    second" split already applied once (`agentcore_app.py`'s own
    Completed entry): the Python side is done and tested offline, this
    is the CDK half. What is *not* in this unit: actually deploying it
    (needs AWS credentials this environment does not have -- see
    `progress-tracker.md` -> Session Notes) and the guest-identity IAM
    role a browser will assume to invoke it (`architecture.md` -> Auth
    and Access Model), which is now provisioned in `api_stack.py`'s
    `_build_patient_guest_identity` via `Runtime.grant_invoke_runtime` on
    the object this stack returns, not here.

Vector storage is Amazon S3 Vectors (`architecture.md` -> Stack calls the
Knowledge Base "S3-backed"), not OpenSearch Serverless: no cluster to
size or keep warm for two small per-clinic FAQ corpora. One vector
bucket, one vector index per clinic. Embeddings are Cohere Embed English
v3 at its fixed 1024 dimensions -- not a product decision but a quota
workaround: Titan Text Embeddings V2 was the original choice (AWS-native,
no separate access request, same 1024 width) and this account turns out to
have zero on-demand quota for it, so ingestion could never invoke it. See
`EMBEDDING_MODEL_ID` for the detail, and `progress-tracker.md` -> Open
Questions for the KB decisions that *were* escalated: reranking,
`retrieve` vs `retrieve_and_generate`, chunking.

The FAQ query tool (`backend/tools/faq.py`) and `faq_agent.py` are not
part of this unit -- `ai-workflow-rules.md` -> When to Split Work keeps
agent/tool logic and infrastructure changes separate steps. They already
land, reading each Knowledge Base id off this stack's `CfnOutput`s the
way `backend/tools/dynamo.py` reads table names -- and the runtime built
here is what runs them.

**Which foundation models the runtime may invoke is deliberately not
pinned down to one ARN.** `progress-tracker.md` -> Open Questions leaves
the sub-agents' text model, and Nova Sonic's own model id, as unsettled
values threaded through a single `model` argument at the interface layer
(`orchestrator.py`, `voice.py`) -- not something this stack can read off
a config that does not exist yet. The execution role's Bedrock policy is
scoped to the `foundation-model` resource type in this account and
region, not to `*`, but not to one model id either: pinning one now would
silently break the moment that open question is answered with a
different id, and the alternative (rebuild the stack) is what
`code-standards.md` -> AWS CDK's "no `*` resource/action grants" is
weighed against here, deliberately, rather than by omission.

Reference for the AgentCore wiring: the vendored TypeScript
`vendor/sample-nova-sonic-websocket-agentcore/cdk/lib/runtime-stack.ts`
(read-only reference -- our CDK stays Python, and uses the `Runtime` L2
construct's own `AgentRuntimeArtifact.from_asset` to build and push the
container image as an ordinary CDK asset during `cdk deploy`, rather than
the vendored sample's S3-upload-plus-CodeBuild pipeline -- that pipeline
exists in the sample to avoid needing Docker on the machine running
`cdk deploy`; ours does not, so the simpler, standard CDK asset path is
the one with no workaround to explain, per `code-standards.md` ->
General, "fix root causes, do not layer workarounds").
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct

from config import DEMO_CLINIC_IDS, VERIFIED_SES_ADDRESS, ProjectConfig
from data_stack import kb_source_prefix

# Cohere Embed English v3, whose output width is a fixed 1024 -- the same
# width Titan Text Embeddings V2 was configured at, so the vector index
# below is unchanged by this swap. Bedrock foundation-model ARNs are not
# account-scoped, so this is safe to build directly rather than looking
# anything up.
#
# Not Titan v2: this account has zero on-demand quota allocated for
# `amazon.titan-embed-text-v2:0` (confirmed by AWS Support), so every
# ingestion `InvokeModel` fails with `ThrottlingException`. Raising it is
# a 2-4 week Service Quotas request. `cohere.embed-english-v3` has
# working on-demand quota here, verified by a direct `invoke-model` call
# returning a real 1024-float embedding. Revisit once the quota lands --
# this is a quota workaround, not a model-quality decision.
EMBEDDING_MODEL_ID = "cohere.embed-english-v3"
EMBEDDING_DIMENSIONS = 1024

# Duplicated from `tools/faq.py`'s `KB_ID_ENV_PREFIX`, not imported: this
# stack needs `aws-cdk-lib`, which `backend/tools/` must never depend on,
# and the two run in separate virtual environments (`architecture.md` ->
# System Boundaries). Same drift-guard shape `data_stack.py` already uses
# for its own duplicated key/index names --
# `backend/tests/test_schema_matches_infra.py` fails if this ever
# disagrees with `faq.KB_ID_ENV_PREFIX`.
KB_ID_ENV_PREFIX = "CLINICPILOT_KB_ID_"

# Duplicated from `agents/memory.py`, not imported: same tradeoff as
# `KB_ID_ENV_PREFIX` above -- this stack needs `aws-cdk-lib`, which the
# agent code's virtual environment does not install, and the two run
# apart (`architecture.md` -> System Boundaries).
# `tests/test_schema_matches_infra.py` fails if this ever disagrees with
# `memory.MEMORY_ID_ENV`.
MEMORY_ID_ENV = "CLINICPILOT_MEMORY_ID"

# The namespace the SUMMARIZATION strategy consolidates into, per
# session, under the actor. `{sessionId}` is not optional: the AgentCore
# service refuses to create a SUMMARIZATION strategy whose namespace
# lacks it (learned from a live deploy refusal, 2026-09-14 -- `cdk
# synth` passes, only `cdk deploy` hits the validation). Actor scoping
# is kept by construction -- one patient's subtree is unreachable from
# another clinic's session (`architecture.md` -> Invariants #1) -- and
# the cross-call half lives in the read: `agents/memory.py` retrieves
# by the actor path prefix, so every past session's summary is visible
# to the next call. `{actorId}`/`{sessionId}` are resolved by the
# AgentCore service, and `tests/test_schema_matches_infra.py` fails if
# the client-side prefix ever stops matching this template.
MEMORY_NAMESPACE_TEMPLATE = "/summaries/actors/{actorId}/sessions/{sessionId}/"


def _knowledge_base_id_env_var(clinic_id: str) -> str:
    """`tools.faq.knowledge_base_id_env_var`'s naming rule, duplicated -- see
    `KB_ID_ENV_PREFIX`."""
    slug = clinic_id.strip().upper().replace("-", "_")
    return f"{KB_ID_ENV_PREFIX}{slug}"


# Where `agents/agentcore_app.py`'s container is built from -- one
# directory up from this stack's own file, since `backend/` (not
# `backend/infra/`) is the FastAPI app's package root. `Dockerfile` and
# `.dockerignore` live there, alongside `agents/` and `tools/`.
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)

# AgentCore Runtime names must be letters, digits, and underscores only
# (no hyphens) -- unlike every other resource name `ProjectConfig` builds.
# The vendored sample's own runtime is named `nova_sonic_bidi_agent` for
# the same reason.
def _runtime_name(config: ProjectConfig) -> str:
    return config.resource_prefix.replace("-", "_") + "_agent_runtime"


def _memory_name(config: ProjectConfig) -> str:
    """Memory names follow the same letters/digits/underscores-only rule
    as runtime names -- see `_runtime_name`."""
    return config.resource_prefix.replace("-", "_") + "_memory"


def _clinic_slug(clinic_id: str) -> str:
    """`clinic-dental` -> `Dental`, for CDK construct ids and CfnOutput names."""
    return clinic_id.removeprefix("clinic-").replace("-", " ").title().replace(" ", "")


class AgentStack(Stack):
    """The AgentCore Runtime, and one Bedrock Knowledge Base per demo clinic."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: ProjectConfig,
        kb_bucket: s3.IBucket,
        clinics_table: dynamodb.ITableV2,
        patients_table: dynamodb.ITableV2,
        appointments_table: dynamodb.ITableV2,
        escalations_table: dynamodb.ITableV2,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.config = config

        self.vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "KnowledgeBaseVectorBucket",
            vector_bucket_name=config.resource_name("kb-vectors"),
        )

        self.knowledge_base_ids: dict[str, str] = {}
        self.knowledge_base_arns: dict[str, str] = {}
        for clinic_id in DEMO_CLINIC_IDS:
            kb_id, kb_arn = self._build_clinic_knowledge_base(clinic_id, kb_bucket)
            self.knowledge_base_ids[clinic_id] = kb_id
            self.knowledge_base_arns[clinic_id] = kb_arn

        # Before the runtime: it is both an env value the container reads
        # and a grant target for the runtime's role.
        self.memory = self._build_patient_memory()

        self.runtime = self._build_agent_runtime(
            clinics_table=clinics_table,
            patients_table=patients_table,
            appointments_table=appointments_table,
            escalations_table=escalations_table,
        )

    def _build_clinic_knowledge_base(
        self, clinic_id: str, kb_bucket: s3.IBucket
    ) -> tuple[str, str]:
        """Provision one clinic's vector index, Knowledge Base, and data source.

        Returns `(knowledge_base_id, knowledge_base_arn)` -- both
        `{Fn::GetAtt}` tokens, not plain strings, since neither exists
        until this stack deploys. The arn is what
        `_build_agent_runtime` scopes `bedrock:Retrieve` to.
        """
        slug = _clinic_slug(clinic_id)

        index = s3vectors.CfnIndex(
            self,
            f"{slug}VectorIndex",
            vector_bucket_name=self.vector_bucket.vector_bucket_name,
            index_name=f"{clinic_id}-index",
            data_type="float32",
            dimension=EMBEDDING_DIMENSIONS,
            distance_metric="cosine",
        )
        index.add_resource_dependency(self.vector_bucket)

        role = iam.Role(
            self,
            f"{slug}KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )
        ingestion_policy = iam.Policy(
            self,
            f"{slug}KnowledgeBaseIngestionPolicy",
            statements=[
                iam.PolicyStatement(
                    sid="InvokeEmbeddingModel",
                    actions=["bedrock:InvokeModel"],
                    resources=[
                        f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL_ID}"
                    ],
                ),
                iam.PolicyStatement(
                    sid="ReadClinicSourceDocuments",
                    actions=["s3:GetObject"],
                    resources=[f"{kb_bucket.bucket_arn}/{kb_source_prefix(clinic_id)}*"],
                ),
                iam.PolicyStatement(
                    sid="ListSourceBucket",
                    actions=["s3:ListBucket"],
                    resources=[kb_bucket.bucket_arn],
                    conditions={
                        "StringLike": {"s3:prefix": [f"{kb_source_prefix(clinic_id)}*"]}
                    },
                ),
                iam.PolicyStatement(
                    sid="ReadWriteVectorIndex",
                    actions=[
                        "s3vectors:GetIndex",
                        "s3vectors:QueryVectors",
                        "s3vectors:PutVectors",
                        "s3vectors:GetVectors",
                        "s3vectors:DeleteVectors",
                    ],
                    resources=[index.attr_index_arn],
                ),
            ],
        )
        role.attach_inline_policy(ingestion_policy)

        knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            f"{slug}KnowledgeBase",
            name=self.config.resource_name(f"kb-{clinic_id}"),
            description=f"FAQ knowledge base for {clinic_id} ({kb_source_prefix(clinic_id)}).",
            role_arn=role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=(
                        f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL_ID}"
                    ),
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    vector_bucket_arn=self.vector_bucket.attr_vector_bucket_arn,
                    index_arn=index.attr_index_arn,
                ),
            ),
        )
        knowledge_base.node.add_dependency(ingestion_policy)

        bedrock.CfnDataSource(
            self,
            f"{slug}KnowledgeBaseDataSource",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            name=self.config.resource_name(f"kb-{clinic_id}-source"),
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=kb_bucket.bucket_arn,
                    inclusion_prefixes=[kb_source_prefix(clinic_id)],
                ),
            ),
        )

        CfnOutput(
            self,
            f"{slug}KnowledgeBaseId",
            value=knowledge_base.attr_knowledge_base_id,
            description=f"Bedrock Knowledge Base id for {clinic_id}.",
            export_name=f"{self.config.resource_name(f'kb-{clinic_id}')}-id",
        )

        return knowledge_base.attr_knowledge_base_id, knowledge_base.attr_knowledge_base_arn

    def _build_patient_memory(self) -> agentcore.Memory:
        """Provision the AgentCore Memory holding each patient's summary.

        One memory resource for the whole project, one SUMMARIZATION
        strategy writing into a session-scoped namespace under the
        actor: `{clinic_id}#{patient_id}` is the actor
        (`agents/memory.py` -> `actor_id`) and each call is its own
        session, so a patient's summaries accumulate across calls --
        read back by actor path prefix -- and are unreachable from
        another clinic's session by construction
        (`architecture.md` -> Invariants #1). The runtime's grants and
        env var are the only wiring this stack adds; the read and write
        paths themselves live in the agent code.
        """
        return agentcore.Memory(
            self,
            "PatientMemory",
            memory_name=_memory_name(self.config),
            description=(
                "One rolling summary per patient, across ClinicPilot"
                " voice calls."
            ),
            memory_strategies=[
                agentcore.ManagedMemoryStrategy(
                    agentcore.MemoryStrategyType.SUMMARIZATION,
                    strategy_name="patient_call_summaries",
                    namespaces=[MEMORY_NAMESPACE_TEMPLATE],
                )
            ],
        )

    def _build_agent_runtime(
        self,
        *,
        clinics_table: dynamodb.ITableV2,
        patients_table: dynamodb.ITableV2,
        appointments_table: dynamodb.ITableV2,
        escalations_table: dynamodb.ITableV2,
    ) -> agentcore.Runtime:
        """Provision the AgentCore Runtime hosting `agents/agentcore_app.py`.

        The container image is an ordinary CDK asset (`from_asset`, over
        `backend/Dockerfile`) -- CDK computes its hash from the source tree
        at synth time and only builds/pushes it during `cdk deploy`'s asset
        publishing step, so `cdk synth` needs neither Docker nor
        credentials (`progress-tracker.md` -> Session Notes records this
        environment has neither).

        The execution role is the one this construct auto-creates
        (`execution_role` left unset, as `iam.Role` is for
        `_build_clinic_knowledge_base`'s ingestion role): this stack only
        adds the extra grants that role does not get for free -- the four
        tables `backend/tools/` reads and writes, and `bedrock:Retrieve`
        on each clinic's own Knowledge Base and nothing else's
        (`architecture.md` -> Invariants #1).

        Table permissions are scoped to exactly the DynamoDB calls
        `backend/tools/` makes against each one (verified against the
        modules that call them, not assumed): `Clinics` is `GetItem`-only
        (`scheduling.get_clinic`); `Patients` and `Appointments` need
        `Query` (their GSIs), `PutItem`, and `UpdateItem`
        (`patients.py`, `booking.py`, `appointments.py`); `Escalations`
        gets `PutItem` only, because the only tool this runtime's agents
        expose is `create_escalation` -- `list_open_escalations`,
        `get_escalation`, and `resolve_escalation` are staff-dashboard
        reads (`escalation_agent.py`'s own Completed entry) that belong to
        a Lambda execution role in `api_stack.py`, not to this one.
        """
        artifact = agentcore.AgentRuntimeArtifact.from_asset(
            _BACKEND_DIR, file="Dockerfile"
        )

        runtime = agentcore.Runtime(
            self,
            "AgentRuntime",
            runtime_name=_runtime_name(self.config),
            description=(
                "ClinicPilot voice front desk: the Orchestrator over "
                "Scheduling, FAQ, and Escalation, served over WebSocket."
            ),
            agent_runtime_artifact=artifact,
            network_configuration=agentcore.RuntimeNetworkConfiguration.using_public_network(),
            # SigV4/IAM, not a custom JWT authorizer: `architecture.md` ->
            # Auth and Access Model has an unauthenticated patient reach
            # this runtime via a Cognito *identity pool*'s guest AWS
            # credentials, which is exactly what IAM auth verifies. The
            # guest role itself -- scoped to `grant_invoke_runtime` on this
            # resource and nothing else -- is provisioned alongside the
            # identity pool in `api_stack.py`, not here.
            authorizer_configuration=agentcore.RuntimeAuthorizerConfiguration.using_iam(),
            # HTTP carries both the `/ping` health check and the `/ws`
            # WebSocket route `agentcore_app.py` defines -- the vendored
            # sample's own choice for the same shape of app.
            protocol_configuration=agentcore.ProtocolType.HTTP,
            environment_variables=self._runtime_environment(),
        )

        for clinic_id, kb_arn in self.knowledge_base_arns.items():
            runtime.add_to_role_policy(
                iam.PolicyStatement(
                    sid=f"Retrieve{_clinic_slug(clinic_id)}KnowledgeBase",
                    actions=["bedrock:Retrieve"],
                    resources=[kb_arn],
                )
            )

        # `foundation-model/*`, not one model id: the sub-agents' text
        # model and Nova Sonic's own model id are both still open
        # (`progress-tracker.md` -> Open Questions), threaded through a
        # runtime `model` argument this stack cannot read. Still scoped to
        # one resource type, per this module's own docstring -- not the
        # blanket grant `code-standards.md` forbids.
        #
        # TWO resource shapes, because Bedrock authorizes the same
        # foundation model against both (found live 2026-09-14: every
        # booking failed with AccessDenied on
        # `arn:aws:bedrock:::foundation-model/anthropic.claude-sonnet-4-6`
        # -- Strands' default `global.*` inference profile resolves to
        # that region-less ARN, which the region-scoped form below can
        # never match; Nova Sonic's bidirectional stream, by contrast,
        # authorizes against the region-scoped form, which is why the
        # voice half of every call worked while every sub-agent call
        # died).
        runtime.add_to_role_policy(
            iam.PolicyStatement(
                sid="InvokeBedrockFoundationModels",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:InvokeModelWithBidirectionalStream",
                ],
                resources=[
                    # Foundation-model ARNs carry no region or account;
                    # this is their real shape, not a widened grant.
                    "arn:aws:bedrock:::foundation-model/*",
                    # The region-scoped shape the bidirectional stream
                    # (and possibly other clients) evaluates against.
                    f"arn:aws:bedrock:{self.region}::foundation-model/*",
                ],
            )
        )

        # The same invoke actions on this account's inference profiles,
        # which the statement above does not cover. Strands' default text
        # model resolves to a cross-region inference profile
        # (`us.anthropic.claude-sonnet-4-6`) rather than a foundation
        # model, so with only `foundation-model/*` every sub-agent call
        # was an implicitDeny -- the deployed bug behind "technical
        # trouble" on any booking (found 2026-09-13 by simulating the
        # runtime role's policy against both ARN shapes). Scoped to this
        # account's own profiles, still one resource type, not a blanket
        # `*`.
        runtime.add_to_role_policy(
            iam.PolicyStatement(
                sid="InvokeBedrockInferenceProfiles",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:InvokeModelWithBidirectionalStream",
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*"
                ],
            )
        )

        for sid, table, actions in (
            ("ReadClinicsTable", clinics_table, ["dynamodb:GetItem"]),
            (
                "ReadWritePatientsTable",
                patients_table,
                ["dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
            ),
            (
                "ReadWriteAppointmentsTable",
                appointments_table,
                ["dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
            ),
            ("CreateEscalations", escalations_table, ["dynamodb:PutItem"]),
        ):
            resources = [table.table_arn]
            if "dynamodb:Query" in actions:
                resources.append(f"{table.table_arn}/index/*")
            runtime.add_to_role_policy(
                iam.PolicyStatement(sid=sid, actions=actions, resources=resources)
            )

        # `escalations._send_staff_email`, reached from this runtime via
        # the Escalation sub-agent's `create_escalation` call. Scoped to
        # the identity resource type in this account/region, not to `*`
        # -- the same "resource type, not one ARN" tradeoff
        # `automation_stack.py` documents for its own reminder send,
        # since the verified SES identity is created manually outside
        # CDK and its ARN cannot be pinned here.
        runtime.add_to_role_policy(
            iam.PolicyStatement(
                sid="SendEscalationEmail",
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[f"arn:aws:ses:{self.region}:{self.account}:identity/*"],
            )
        )

        # Read (retrieve a patient's summary mid-call) and write (record
        # the call's turns at hang-up) on the one memory resource -- the
        # L2's own grants, so the action list is the construct's to keep
        # correct. `agents/memory.py` is the only code that makes these
        # calls, and it makes exactly these two.
        self.memory.grant_read(runtime)
        self.memory.grant_write(runtime)

        CfnOutput(
            self,
            "AgentRuntimeArn",
            value=runtime.agent_runtime_arn,
            description="AgentCore Runtime ARN for the ClinicPilot voice front desk.",
            export_name=f"{self.config.resource_name('agent-runtime')}-arn",
        )

        return runtime

    def _runtime_environment(self) -> dict[str, str]:
        """Environment variables the deployed container reads on start.

        Deployment *facts* only -- which table, which Knowledge Base,
        which memory resource -- never a product decision. The
        text/voice model ids (`orchestrator.TEXT_MODEL_ENV`,
        `voice.VOICE_MODEL_ENV`, `voice.VOICE_ID_ENV`) are deliberately
        absent: each is an open question in `progress-tracker.md`, and
        leaving them unset is what already lets the Strands/Nova Sonic
        default stand without blocking on the answer (see those
        modules' own docstrings).
        """
        env = {
            # `tools/dynamo.table_name`'s fallback naming scheme needs only
            # these two to resolve all four table names -- the same "at
            # most `CLINICPILOT_ENV` set" property that module's own
            # docstring describes for local scripts.
            "CLINICPILOT_PROJECT_PREFIX": self.config.project_prefix,
            "CLINICPILOT_ENV": self.config.environment,
            # `tools/escalations.py`'s two notification addresses
            # (`ESCALATION_SENDER_ENV` / `ESCALATION_RECIPIENT_ENV`).
            # SES stays in sandbox mode for the demo, so both must be
            # verified identities in this account/region -- which is why
            # the demo sends to the same address it sends from, the same
            # choice `automation_stack.py` documents for reminders. When
            # unset, `create_escalation` records the escalation and
            # sends no email, so this is an enable, not a dependency.
            "CLINICPILOT_ESCALATION_SENDER_EMAIL": VERIFIED_SES_ADDRESS,
            "CLINICPILOT_ESCALATION_RECIPIENT_EMAIL": VERIFIED_SES_ADDRESS,
            # `agents/memory.py`'s enable: the deployed AgentCore Memory
            # resource id. The read and write paths are no-ops without
            # it, so local development never needs it set.
            MEMORY_ID_ENV: self.memory.memory_id,
        }
        for clinic_id, kb_id in self.knowledge_base_ids.items():
            env[_knowledge_base_id_env_var(clinic_id)] = kb_id
        return env
