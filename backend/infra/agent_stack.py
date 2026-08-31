"""Agent stack: the per-clinic Bedrock Knowledge Base.

AgentCore Runtime/Memory are not defined yet -- they need
`agentcore_app.py` provisioned first (`progress-tracker.md` Next Up #1),
and are a separate CDK unit from this one
(`ai-workflow-rules.md` -> When to Split Work).

This stack owns the Knowledge Base half only: one Bedrock Knowledge Base
per demo clinic (`config.DEMO_CLINIC_IDS`), each reading only that
clinic's prefix in the data stack's `kb_bucket`
(`data_stack.kb_source_prefix`). A separate Knowledge Base per clinic --
rather than one shared Knowledge Base with a `clinic_id` metadata filter
-- is what makes `architecture.md` -> Invariants #1 hold structurally: a
retrieval call is scoped to a clinic by which Knowledge Base id it is
given, not by trusting a filter to be applied correctly.

Vector storage is Amazon S3 Vectors (`architecture.md` -> Stack calls the
Knowledge Base "S3-backed"), not OpenSearch Serverless: no cluster to
size or keep warm for two small per-clinic FAQ corpora. One vector
bucket, one vector index per clinic. Embeddings are Amazon Titan Text
Embeddings V2 at its default 1024 dimensions -- an AWS-native model with
no separate model access request, needed nowhere else in this stack, and
a reasonable default for a small FAQ corpus rather than a product
decision (see `progress-tracker.md` -> Open Questions for the KB
decisions that *were* escalated: reranking, `retrieve` vs
`retrieve_and_generate`, chunking).

The FAQ query tool (`backend/tools/faq.py`) and `faq_agent.py` are not
part of this unit -- `ai-workflow-rules.md` -> When to Split Work keeps
agent/tool logic and infrastructure changes separate steps. They land
next, reading each Knowledge Base id off this stack's `CfnOutput`s the
way `backend/tools/dynamo.py` reads table names.

Reference for the AgentCore wiring (not yet used): the vendored
TypeScript `vendor/sample-nova-sonic-websocket-agentcore/cdk/lib/runtime-stack.ts`
(read-only reference -- our CDK stays Python).
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct

from config import DEMO_CLINIC_IDS, ProjectConfig
from data_stack import kb_source_prefix

# Titan Text Embeddings V2, at its default output width. Bedrock
# foundation-model ARNs are not account-scoped, so this is safe to build
# directly rather than looking anything up.
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024


def _clinic_slug(clinic_id: str) -> str:
    """`clinic-dental` -> `Dental`, for CDK construct ids and CfnOutput names."""
    return clinic_id.removeprefix("clinic-").replace("-", " ").title().replace(" ", "")


class AgentStack(Stack):
    """One Bedrock Knowledge Base per demo clinic, over Amazon S3 Vectors."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: ProjectConfig,
        kb_bucket: s3.IBucket,
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
        for clinic_id in DEMO_CLINIC_IDS:
            kb_id = self._build_clinic_knowledge_base(clinic_id, kb_bucket)
            self.knowledge_base_ids[clinic_id] = kb_id

    def _build_clinic_knowledge_base(self, clinic_id: str, kb_bucket: s3.IBucket) -> str:
        """Provision one clinic's vector index, Knowledge Base, and data source.

        Returns the `{Fn::GetAtt KnowledgeBaseId}` token -- not a plain
        string, since the real id does not exist until this stack deploys.
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

        return knowledge_base.attr_knowledge_base_id
