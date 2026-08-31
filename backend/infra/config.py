"""Single source of truth for every name and ID used across the CDK stacks.

`code-standards.md` -> AWS CDK (Python) requires that all resource
names/IDs derive from one config object, so no stack ever hardcodes an
ARN or repeats a resource name another stack also knows about. Stacks
receive a `ProjectConfig` and ask it for names; they never build names
by string concatenation themselves.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# `architecture.md` -> Stack defaults to us-east-1. Tracked as an open
# question in `progress-tracker.md`: confirm before the first deploy.
DEFAULT_REGION = "us-east-1"

# `project-overview.md` working name. Renaming the project means changing
# this one value (and the tracker's open question about the name).
DEFAULT_PROJECT_PREFIX = "clinicpilot"

DEFAULT_ENVIRONMENT = "dev"

# The two demo clinics `project-overview.md` scopes this hackathon build
# to (one dental, one cosmetic -- see `architecture.md` -> Storage Model,
# "The two demo clinics differ in all four"). Self-serve clinic
# onboarding is explicitly out of scope, so a fixed list here -- rather
# than a dynamic lookup -- is correct for this build, not a shortcut:
# `agent_stack.py` provisions one Bedrock Knowledge Base per id, and
# `seed/` will write exactly these two `Clinics` rows.
DEMO_CLINIC_IDS: tuple[str, ...] = ("clinic-dental", "clinic-cosmetic")

# CloudFormation stack names are the one place the project name is shown
# to a human, so it carries its display casing rather than the slug's.
DEFAULT_STACK_PREFIX = "ClinicPilot"


@dataclass(frozen=True)
class ProjectConfig:
    """Naming and deployment-target config shared by every stack.

    Attributes:
        project_prefix: Short lowercase project slug used to prefix all
            physical resource names.
        environment: Deployment environment slug (``dev``, ``prod``).
        region: AWS region every stack deploys into. Single-region by
            design -- see `architecture.md` -> Stack.
        account: AWS account id, or None when synthesising without
            credentials (``cdk synth`` works environment-agnostically).
        stack_prefix: Display-cased project name used in stack names.
    """

    project_prefix: str = DEFAULT_PROJECT_PREFIX
    environment: str = DEFAULT_ENVIRONMENT
    region: str = DEFAULT_REGION
    account: str | None = None
    stack_prefix: str = DEFAULT_STACK_PREFIX

    @classmethod
    def from_environment(cls) -> "ProjectConfig":
        """Build config from environment variables, falling back to defaults.

        Reads ``CLINICPILOT_PROJECT_PREFIX``, ``CLINICPILOT_ENV``, and the
        standard CDK-provided ``CDK_DEFAULT_ACCOUNT`` / ``CDK_DEFAULT_REGION``
        (with ``AWS_REGION`` as a fallback for the latter).
        """
        region = (
            os.environ.get("CDK_DEFAULT_REGION")
            or os.environ.get("AWS_REGION")
            or DEFAULT_REGION
        )
        return cls(
            project_prefix=os.environ.get(
                "CLINICPILOT_PROJECT_PREFIX", DEFAULT_PROJECT_PREFIX
            ),
            environment=os.environ.get("CLINICPILOT_ENV", DEFAULT_ENVIRONMENT),
            region=region,
            account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        )

    @property
    def resource_prefix(self) -> str:
        """Prefix for physical resource names, e.g. ``clinicpilot-dev``."""
        return f"{self.project_prefix}-{self.environment}"

    def resource_name(self, name: str) -> str:
        """Physical name for a resource, e.g. ``clinicpilot-dev-appointments``.

        Args:
            name: Lowercase, hyphenated resource-specific suffix.
        """
        return f"{self.resource_prefix}-{name}"

    def stack_name(self, concern: str) -> str:
        """CloudFormation stack name for one concern, e.g. ``ClinicPilot-Dev-Data``.

        Args:
            concern: One of the five stack concerns (data, agent, api,
                automation, frontend).
        """
        return f"{self.stack_prefix}-{self.environment.capitalize()}-{concern.capitalize()}"
