# My JEE Tutor Agent

AI-powered IIT JEE instructor built for Amazon Bedrock AgentCore Runtime with CrewAI and liteLLM.

## What It Does

1. A client invokes the Bedrock AgentCore runtime with an S3 image prefix or image data URI.
2. `src/agentcore_app.py` receives the invocation on AgentCore's `/invocations` contract.
3. `src/agentcore_handler.py` validates the payload and converts it into the tutor workflow input shape.
4. CrewAI runs the IIT JEE tutor agent.
5. `VisionLLMClient` calls the configured vision-capable model through liteLLM.
6. Optional Bedrock runtime guardrails check the request and final response.
7. The AgentCore invocation returns coaching-style feedback as JSON.

## Local Setup With Poetry

```powershell
cd S:\PythonWorkspace\my-jee-tutor-agent
poetry lock
poetry install --with dev
```

## AgentCore Payload Shape

The runtime accepts a deliberately small payload. Send exactly one of
`image_s3_prefix` or `image_data_uri`.

```json
{
  "task": "Diagnose this JEE attempt.",
  "subject": "maths",
  "image_s3_prefix": "s3://attempt-bucket/maths/student-1/",
  "save_analysis_pdf": true
}
```

S3 prefixes are folder-like object prefixes, not local folders. Supported image
extensions are `.png`, `.jpg`, `.jpeg`, and `.webp`; objects are loaded in key
order. The AgentCore runtime role must have `s3:GetObject` and `s3:ListBucket`
for S3 prefixes. Configure access with GitHub repository variables formatted as
Terraform JSON lists:

```text
S3_IMAGE_INPUT_BUCKET_ARNS=["arn:aws:s3:::web-scraper-dev-055173110395-ap-south-1-screenshots"]
S3_IMAGE_INPUT_OBJECT_ARNS=["arn:aws:s3:::web-scraper-dev-055173110395-ap-south-1-screenshots/*"]
```

Single-image payload:

```json
{
  "task": "Diagnose this JEE attempt.",
  "subject": "maths",
  "image_data_uri": "data:image/png;base64,...",
  "save_analysis_pdf": false
}
```

## LLM Config

Default model settings live in [src/config/llm.toml](src/config/llm.toml):

```toml
[vision]
model = "gemini/gemini-3-flash-preview"

[completion]
temperature = 0.2
```

Optional Bedrock runtime guardrails live in the same file:

```toml
[guardrails]
enabled = false
identifier = ""
version = "DRAFT"
output_scope = "INTERVENTIONS"
fail_closed = true
include_image = true
```

Add any extra LiteLLM completion option under `[completion]`:

```toml
[completion]
temperature = 0.2
top_p = 0.9
max_tokens = 1200
timeout = 60
```

You can point to a different config file with:

```text
LLM_CONFIG_FILE=/app/config/llm.toml
```

## Runtime Environment Variables

Secrets still come from environment variables:

```text
OPENAI_API_KEY=your-openai-key
GOOGLE_API_KEY=your-google-key
LITELLM_API_KEY=optional-fallback-key
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Deployment-specific values can override the properties file when needed:

```text
VISION_MODEL=openai/gpt-4o
LITELLM_BASE_URL=https://your-litellm-proxy.example.com
BEDROCK_GUARDRAIL_ENABLED=true
BEDROCK_GUARDRAIL_ID=your-guardrail-id-or-arn
BEDROCK_GUARDRAIL_VERSION=DRAFT
```

## Terraform Notes

- Terraform provisions an ECR repository, AgentCore execution role, AgentCore runtime, and default runtime endpoint.
- Terraform manages the AgentCore runtime CloudWatch log group with 3-day retention by default.
- Terraform grants the AgentCore runtime access to configured S3 image input buckets.
- Terraform creates a Bedrock Guardrail for the tutor and injects its ID into the AgentCore runtime.
- Build the container from `src/Dockerfile`.
- Push that image to ECR.
- Pass the pushed image URI as `agentcore_image_uri`.
- `bedrock/...` model calls use the AgentCore runtime IAM role; no external API key is needed for Bedrock models.
- Runtime guardrails use the same role with `bedrock:ApplyGuardrail`. By default, Terraform uses the guardrail it creates; set `bedrock_guardrail_id` only to use an existing guardrail instead.
- S3 image inputs use the AgentCore runtime role. Configure bucket and object ARNs with `S3_IMAGE_INPUT_BUCKET_ARNS` and `S3_IMAGE_INPUT_OBJECT_ARNS`.
- Langfuse keys are passed as AgentCore runtime environment variables when configured.

The role used by GitHub Actions in `AWS_ROLE_TO_ASSUME` must be able to manage
Bedrock Guardrails through the AWS Cloud Control API. If Terraform fails with
`Access denied for operation 'AWS::Bedrock::Guardrail'`, attach permissions like
[docs/aws-deploy-role-policy.json](docs/aws-deploy-role-policy.json) to that
deploy role. `bedrock:TagResource` is required because the Terraform guardrail
resource creates tags.

AgentCore runtimes created on or after October 13, 2025 also require the deploy
role to allow `iam:CreateServiceLinkedRole` for
`runtime-identity.bedrock-agentcore.amazonaws.com` so AgentCore can create
`AWSServiceRoleForBedrockAgentCoreRuntimeIdentity` during runtime deployment.
That statement is included in [docs/aws-deploy-role-policy.json](docs/aws-deploy-role-policy.json).

The CD workflow prints the effective AWS caller and runs `bedrock
list-guardrails` before Terraform applies the guardrail. If that preflight fails,
the assumed deploy role, permission boundary, SCP, or selected region is blocking
Bedrock access before Terraform runs.

If the deploy role cannot create guardrails, create one manually and set the
GitHub repository variable `BEDROCK_GUARDRAIL_ID` to its ID or ARN. To deploy
without guardrails temporarily, set `BEDROCK_GUARDRAIL_ENABLED=false`.

## CD Agent Evals and Security Scan

The CD workflow runs agent evals after deployment. The garak scan is enabled by
default and can be skipped by setting `GARAK_SCAN_ENABLED=false`.

The eval step runs cases from `evals/jee_tutor_eval_cases.json` against the real
AgentCore handler, using live eval images from S3 and deployed Bedrock Guardrail
settings. By default, CD reads images from:

```text
s3://<TF_STATE_BUCKET>/cd-evals-images/
```

For the default state bucket, that is:

```text
s3://jee-tutor-agent-terraform-state/cd-evals-images/
```

Upload non-sensitive synthetic JEE attempt screenshots to that prefix before
enabling live evals. Keep `tests/fixtures/image_folder` for local unit tests only;
those tiny placeholder files are not valid model-eval images. Override the live
eval location with `CD_EVAL_IMAGE_S3_PREFIX` when needed. The GitHub Actions AWS
role must have `s3:ListBucket` on the bucket and `s3:GetObject` on the
`cd-evals-images/*` objects.

The eval step writes `eval_runs/agent-evals.json` and fails the workflow when the
pass rate is below `CD_EVAL_MIN_SCORE`.

When enabled, the garak step starts a local REST adapter around the same
handler, supplies the same S3 eval image prefix, sends garak probe prompts as
`task`, and reuses the deployed Bedrock Guardrail ID.

GitHub repository variables can tune the eval and scan steps:

```text
CD_EVAL_MIN_SCORE=0.75
CD_EVAL_IMAGE_S3_PREFIX=s3://jee-tutor-agent-terraform-state/cd-evals-images/
GARAK_SCAN_ENABLED=true
GARAK_PROBES=dan.Dan_11_0,promptinject.HijackHateHumansMini
GARAK_HIT_THRESHOLD=0
```

When `GARAK_SCAN_ENABLED=true`, the workflow installs garak, starts the local
adapter, runs the guardrail smoke check, executes garak probes, and enforces
`GARAK_HIT_THRESHOLD`. The default probe list is intentionally reduced and
capped at one prompt per probe by `soft_probe_prompt_cap` in
[security/garak-rest.yml](security/garak-rest.yml). Gemini calls are
rate-limited to 100 requests per minute, but full probe families such as
`dan,promptinject,encoding` can still exceed the 30-minute CI step timeout
because each prompt performs a full agent invocation with image analysis. Use
`GARAK_PROBES` and a higher prompt cap for deeper scheduled scans when longer
runtime is acceptable.

When Langfuse credentials are configured, CD publishes aggregate deploy metrics:
the agent eval score/pass result and garak aggregate fields including
enabled/disabled, probes, hit count, hit threshold, pass/fail, and commit SHA.
Detailed eval and garak reports remain in GitHub Actions artifacts.

Eval reports, plus garak reports when enabled, are uploaded as the
`garak-security-reports` workflow artifact.

## Runtime Guardrails

The AgentCore handler applies Bedrock Guardrails at the runtime boundary:

- Input guardrail: checks optional text context and png/jpeg image payloads before CrewAI runs.
- Output guardrail: checks the final tutor analysis before returning it.
- PII guardrail: uses the configured Bedrock sensitive information policy to block or mask personal data such as email, phone, names, addresses, and custom regex matches.
- If an input check intervenes, the invocation returns an error response.
- If an output check intervenes, the response uses the guardrail-provided text when available.

Configure PII behavior in the Bedrock guardrail itself under sensitive information filters. For this tutor, use `BLOCK` for user input PII and `ANONYMIZE` or `BLOCK` for model output PII, depending on whether you want redacted coaching text returned.

Terraform exposes guardrail settings as variables:

```hcl
bedrock_guardrail_enabled = true
bedrock_guardrail_id      = ""
bedrock_guardrail_version = "DRAFT"
```

Leave `bedrock_guardrail_id` empty to use the Terraform-created guardrail. Set it only when you want the AgentCore runtime to use a pre-existing Bedrock Guardrail.

Terraform also exposes AgentCore log retention:

```hcl
cloudwatch_log_retention_days = 3
```

For GitHub Actions deployments, override it with the repository variable `CLOUDWATCH_LOG_RETENTION_DAYS` if needed. If the AgentCore log group already exists before Terraform manages it, import it once with the `agentcore_log_group_name` output value.

### New Relic Log Forwarding

AgentCore writes runtime logs to CloudWatch Logs. Terraform can deploy New Relic's CloudWatch log ingestion Lambda and subscribe the AgentCore runtime log group to it.

For GitHub Actions deployments, add this repository secret:

```text
NEW_RELIC_LICENSE_KEY=your-new-relic-ingest-license-key
```

When that secret is present, CD sets `newrelic_log_forwarding_enabled=true` and Terraform creates:

- A New Relic log ingestion Lambda from `newrelic/aws-log-ingestion`
- A CloudWatch Logs subscription filter from the AgentCore log group to that Lambda

Optional repository variables:

```text
NEW_RELIC_LOG_FORWARDER_NAME=jee-tutor-newrelic-log-ingestion
NEW_RELIC_LOG_FILTER_PATTERN=
NEW_RELIC_LOG_TAGS=["environment:prod","team:learning"]
```

The app log lines include `service=jee-tutor-agent` by default, and the forwarder adds New Relic tags including `service:<project_name>`, `source:bedrock-agentcore`, and the CloudWatch log group name.

The runtime also emits one invocation metric log per request:

```text
agent_invocation metric_name=agent.invocations metric_value=1 metric_unit=Count
```

In New Relic Logs, this can be queried directly:

```sql
SELECT count(*) FROM Log
WHERE service = 'jee-tutor-agent'
  AND metric_name = 'agent.invocations'
```

Or create a New Relic log-based metric named `agent.invocations` using `metric_value` as the count value.

Terraform also exposes S3 image input permissions:

```hcl
s3_image_input_bucket_arns = ["arn:aws:s3:::web-scraper-dev-055173110395-ap-south-1-screenshots"]
s3_image_input_object_arns = ["arn:aws:s3:::web-scraper-dev-055173110395-ap-south-1-screenshots/*"]
```

Bucket ARNs grant `s3:ListBucket`; object ARNs grant `s3:GetObject`,
`s3:PutObject`, and `s3:AbortMultipartUpload`.

## Langfuse

Langfuse is optional and activates when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are present.

- Observability: AgentCore invocations are traced as spans, and LiteLLM calls are traced as generations.
- Prompt management: create Langfuse text prompts for the behavioral prompt keys in `src/config/llm.toml`. If any prompt is missing, the local fallback in `prompts.py` is used.

Managed prompt names:

```text
jee-tutor-vision-system-prompt
jee-tutor-vision-user-prompt
jee-tutor-agent-goal
jee-tutor-agent-backstory
jee-tutor-diagnosis-task-description
jee-tutor-diagnosis-task-expected-output
```
