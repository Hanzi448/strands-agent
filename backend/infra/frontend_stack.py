"""Frontend stack: S3 bucket plus CloudFront distribution for the SPA.

Skeleton only -- no resources yet. Populated once there is a frontend
build to deploy.

Planned contents, per `architecture.md` -> Stack:
  - Private S3 bucket holding the Vite build output.
  - CloudFront distribution serving it over HTTPS, with SPA-style
    fallback to `index.html`.
  - Deployment of runtime config (API endpoint, Cognito ids, agent
    runtime ARN) the SPA reads at load time, sourced from the api/agent
    stacks rather than hardcoded.
"""

from __future__ import annotations

from aws_cdk import Stack
from constructs import Construct

from config import ProjectConfig


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
