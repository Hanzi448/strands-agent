# ClinicPilot infrastructure (AWS CDK, Python)

All AWS resources for ClinicPilot are defined here. One stack per
concern, per `context/code-standards.md` -> AWS CDK (Python):

| Stack file             | Stack name                     | Owns                                            |
| ---------------------- | ------------------------------ | ----------------------------------------------- |
| `data_stack.py`        | `ClinicPilot-Dev-Data`         | DynamoDB tables, knowledge base source S3 bucket |
| `agent_stack.py`       | `ClinicPilot-Dev-Agent`        | AgentCore Runtime hosting `agents/agentcore_app.py`; one Bedrock Knowledge Base per demo clinic (S3 Vectors); AgentCore Memory not yet built |
| `api_stack.py`         | `ClinicPilot-Dev-Api`          | API Gateway, API Lambdas, Cognito (staff)       |
| `automation_stack.py`  | `ClinicPilot-Dev-Automation`   | EventBridge schedule + background scan Lambda   |
| `frontend_stack.py`    | `ClinicPilot-Dev-Frontend`     | S3 + CloudFront static hosting                  |

**`data_stack.py` and `agent_stack.py` have resources so far.**
`data_stack.py` holds the four DynamoDB tables and the knowledge base
source bucket; `agent_stack.py` holds one Bedrock Knowledge Base per
demo clinic (`config.DEMO_CLINIC_IDS`), each over its own Amazon S3
Vectors bucket/index and reading only that clinic's `kb/{clinic_id}/`
prefix, plus the AgentCore Runtime that hosts `agents/agentcore_app.py`
— a container image asset built from `backend/Dockerfile`
(`AgentRuntimeArtifact.from_asset`, an ordinary CDK asset: `cdk synth`
needs neither Docker nor AWS credentials, only `cdk deploy`'s asset
publishing step does), with its execution role granted exactly the
DynamoDB and Bedrock calls `backend/tools/` makes — see
`context/architecture.md` -> System Boundaries. AgentCore Memory is not
built yet, and neither is the guest-identity Cognito role a browser will
assume to invoke the runtime (`architecture.md` -> Auth and Access
Model) — that lands with `api_stack.py`/`frontend_stack.py`.
`api_stack.py`, `automation_stack.py`, and `frontend_stack.py` are still
empty skeletons; their structure, naming, and deployment order are in
place, and resources are added by the later items in
`context/progress-tracker.md`.

## Tables

Defined in `data_stack.py`, schema and rationale in
`context/architecture.md` -> Storage Model.

| Table          | PK / SK                        | Indexes                            |
| -------------- | ------------------------------ | ---------------------------------- |
| `Clinics`      | `clinic_id`                    | —                                  |
| `Patients`     | `clinic_id` / `patient_id`     | `by-phone`                         |
| `Appointments` | `clinic_id` / `appointment_id` | `by-start-time`, `by-patient`      |
| `Escalations`  | `clinic_id` / `escalation_id`  | `by-created-at`                    |

Every index carries `clinic_id` inside its own partition key, so no
index is a cross-clinic query path (`architecture.md` -> Invariants #1).
Key and index names are module constants in `data_stack.py` — import
them rather than retyping the strings.

In `dev` the tables are destroyed with the stack; in `prod` they are
retained, with point-in-time recovery and deletion protection on.

Deployment order (declared in `app.py`):

```
data ──┬─> agent ──> api ──> frontend
       ├─> api
       └─> automation
```

## Naming

No stack hardcodes a resource name or ARN. `config.py` holds the single
`ProjectConfig` that every stack receives, and all names come from it:

- `config.resource_name("appointments")` -> `clinicpilot-dev-appointments`
- `config.stack_name("data")` -> `ClinicPilot-Dev-Data`

Overridable via environment variables: `CLINICPILOT_PROJECT_PREFIX`,
`CLINICPILOT_ENV`, and CDK's own `CDK_DEFAULT_ACCOUNT` /
`CDK_DEFAULT_REGION` (`AWS_REGION` as a fallback). Region defaults to
`us-east-1` -- still an open question in the tracker, confirm before the
first real deploy.

## Setup

Python 3.12+ (`context/code-standards.md`), and the CDK CLI:

```bash
cd backend/infra
py -3.12 -m venv .venv        # Windows;  python3.12 -m venv .venv on macOS/Linux
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
npm install -g aws-cdk        # or use npx aws-cdk@2 below
```

Create the venv with an explicit `py -3.12` / `python3.12`, not a bare
`python` -- bare `python` may resolve to an older or unrelated
interpreter.

## Commands

```bash
cdk list                      # the five stacks
cdk synth                     # synthesise all templates to cdk.out/
cdk deploy --all              # deploy in dependency order
cdk destroy --all
```

If the CDK CLI is not installed globally, prefix with `npx aws-cdk@2`.
On Windows, when the venv is not activated, point the CLI at the venv
interpreter with a backslash path -- CDK spawns the app through
`cmd.exe`, which does not accept `.venv/Scripts/python.exe`:

```bash
npx aws-cdk@2 synth --app '.venv\Scripts\python.exe app.py'
```

`cdk.out/` is generated output -- never edit it, it is gitignored.

`cdk deploy` (not `synth`) needs Docker running locally to build and push
`agent_stack.py`'s container image asset -- `synth` only fingerprints the
`backend/` source tree, which is why it works in an environment with
neither Docker nor AWS credentials.
