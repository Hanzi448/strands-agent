"""Frontend stack: S3 bucket plus CloudFront distribution for the SPA.

Serves the built Vite output (`frontend/dist/`) over HTTPS with an
SPA-style fallback to `index.html`, per `architecture.md` -> Stack
("Static SPA hosting, served over HTTPS"). The SPA reads its runtime
config -- API endpoint, Cognito ids, agent runtime ARN -- from
``VITE_*`` variables at *build* time (`frontend/.env.example` maps
each one to the stack output it comes from), so this stack needs no
values from the api/agent stacks: deploy those first, fill
``frontend/.env``, run ``npm run build``, then deploy this one.

Deploy order for this stack, therefore:
    1. ``cdk deploy`` the data/agent/api/automation stacks.
    2. Copy their outputs into ``frontend/.env`` (see
       ``frontend/.env.example`` for the mapping).
    3. ``npm run build`` in ``frontend/``.
    4. ``cdk deploy ClinicPilot-Dev-Frontend`` -- this uploads
       ``frontend/dist/`` and invalidates the CloudFront cache.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from config import ProjectConfig

# The Vite build output, resolved from this file rather than the
# working directory: `cdk` runs from `backend/infra/`, and a relative
# "frontend/dist" would silently upload nothing (or fail) if it were
# ever run from elsewhere.
_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class FrontendStack(Stack):
    """Static SPA hosting: S3 origin behind CloudFront."""

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

        # Same environment branch as every other stack: `dev` is
        # teardown-able in one command, `prod` keeps its data.
        ephemeral = config.environment != "prod"

        bucket = s3.Bucket(
            self,
            "SpaBucket",
            bucket_name=self.config.resource_name("frontend"),
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=not ephemeral,
            removal_policy=(
                RemovalPolicy.DESTROY if ephemeral else RemovalPolicy.RETAIN
            ),
            # The BucketDeployment below owns this bucket's objects in
            # `dev` too -- without this, a `cdk destroy` of the stack
            # fails on a non-empty bucket.
            auto_delete_objects=ephemeral,
        )

        # The bucket stays fully private: only CloudFront reads it, via
        # an Origin Access Control the origin wires the bucket grant to.
        oac = cloudfront.S3OriginAccessControl(
            self,
            "SpaOriginAccessControl",
            description="CloudFront access to the ClinicPilot SPA bucket.",
        )

        distribution = cloudfront.Distribution(
            self,
            "SpaDistribution",
            comment="ClinicPilot patient voice UI and staff dashboard.",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    bucket, origin_access_control=oac
                ),
                viewer_protocol_policy=(
                    cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS
                ),
                # The build output is content-hashed by Vite; only
                # index.html changes between deploys, and the
                # deployment invalidates that explicitly.
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            error_responses=[
                # SPA fallback: an unknown path (or a refresh on one)
                # serves the app, which routes client-side. The app
                # uses hash routes (`#/voice`), so this only fires on
                # genuinely mistyped paths -- but a 403/404 page would
                # still look broken where the app could recover.
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        # Upload the build and invalidate the cache, so a redeploy
        # actually serves the new build rather than CloudFront's copy
        # of the old one.
        s3deploy.BucketDeployment(
            self,
            "SpaDeployment",
            sources=[s3deploy.Source.asset(str(_DIST_DIR))],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # The public demo link -- the hackathon submission's "live demo
        # URL" is this output.
        CfnOutput(
            self,
            "FrontendUrl",
            value=f"https://{distribution.distribution_domain_name}",
            description=(
                "Public URL of the deployed SPA (patient voice UI and "
                "staff dashboard)."
            ),
            export_name=f"{self.config.resource_name('frontend')}-url",
        )
