#!/usr/bin/env python3
"""ClinicPilot CDK app entrypoint.

Instantiates one stack per concern, as required by `code-standards.md`
-> AWS CDK (Python). Every stack is a skeleton at this point: the
structure and the dependency graph are real, the resources are not yet.

Run from this directory:
    cdk synth
    cdk deploy --all
"""

from __future__ import annotations

import aws_cdk as cdk

from agent_stack import AgentStack
from api_stack import ApiStack
from automation_stack import AutomationStack
from config import ProjectConfig
from data_stack import DataStack
from frontend_stack import FrontendStack


def main() -> None:
    app = cdk.App()
    config = ProjectConfig.from_environment()

    # `account` is None when synthesising without credentials, which keeps
    # `cdk synth` working environment-agnostically.
    env = cdk.Environment(account=config.account, region=config.region)
    common = {"env": env, "config": config}

    data = DataStack(
        app,
        config.stack_name("data"),
        description="ClinicPilot data: DynamoDB tables and the knowledge base bucket.",
        **common,
    )

    agent = AgentStack(
        app,
        config.stack_name("agent"),
        description="ClinicPilot agent: AgentCore Runtime and the Bedrock Knowledge Base.",
        kb_bucket=data.kb_bucket,
        clinics_table=data.clinics_table,
        patients_table=data.patients_table,
        appointments_table=data.appointments_table,
        escalations_table=data.escalations_table,
        **common,
    )

    api = ApiStack(
        app,
        config.stack_name("api"),
        description="ClinicPilot API: staff dashboard API, voice bridge, and Cognito.",
        clinics_table=data.clinics_table,
        appointments_table=data.appointments_table,
        escalations_table=data.escalations_table,
        agent_runtime=agent.runtime,
        **common,
    )

    automation = AutomationStack(
        app,
        config.stack_name("automation"),
        description="ClinicPilot automation: daily appointment scan on EventBridge + Lambda.",
        clinics_table=data.clinics_table,
        patients_table=data.patients_table,
        appointments_table=data.appointments_table,
        escalations_table=data.escalations_table,
        **common,
    )

    frontend = FrontendStack(
        app,
        config.stack_name("frontend"),
        description="ClinicPilot frontend: S3 + CloudFront static hosting for the SPA.",
        **common,
    )

    # Deployment order. `agent` also takes `data.kb_bucket` and all four
    # tables directly (the Knowledge Base data sources read the bucket, and
    # the AgentCore Runtime's execution role is granted against the
    # tables); the rest are declared now so `cdk deploy --all` is correct
    # from the first resource each stack gains.
    agent.add_stack_dependency(data)        # KB bucket + table grants
    api.add_stack_dependency(data)          # dashboard handlers read the tables
    api.add_stack_dependency(agent)         # voice bridge targets the agent runtime
    automation.add_stack_dependency(data)   # background scan mutates the tables
    frontend.add_stack_dependency(api)      # SPA config needs API + Cognito ids

    app.synth()


if __name__ == "__main__":
    main()
