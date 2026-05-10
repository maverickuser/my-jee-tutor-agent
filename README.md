# My JEE Tutor Agent

AI-powered IIT JEE instructor built for Amazon Bedrock AgentCore Runtime with CrewAI and liteLLM.

## What It Does

1. A client invokes the Bedrock AgentCore runtime with an image folder or image payload.
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

Preferred folder payload:

```json
{
  "image_folder": "/app/input/attempt-images",
  "question_context": "Optional student/question context"
}
```

The folder path must be available inside the runtime container. Supported files are `.png`,
`.jpg`, `.jpeg`, and `.webp`; files are loaded in filename order.

Single-image payload:

```json
{
  "image_data_uri": "data:image/png;base64,...",
  "question_context": "Optional student/question context"
}
```

Alternative media payload:

```json
{
  "media": {
    "type": "image",
    "format": "png",
    "data": "base64..."
  },
  "prompt": "Optional student/question context"
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
- Terraform creates a Bedrock Guardrail for the tutor and injects its ID into the AgentCore runtime.
- Build the container from `src/Dockerfile`.
- Push that image to ECR.
- Pass the pushed image URI as `agentcore_image_uri`.
- `bedrock/...` model calls use the AgentCore runtime IAM role; no external API key is needed for Bedrock models.
- Runtime guardrails use the same role with `bedrock:ApplyGuardrail`. By default, Terraform uses the guardrail it creates; set `bedrock_guardrail_id` only to use an existing guardrail instead.
- Langfuse keys are passed as AgentCore runtime environment variables when configured.

The role used by GitHub Actions in `AWS_ROLE_TO_ASSUME` must be able to manage
Bedrock Guardrails through the AWS Cloud Control API. If Terraform fails with
`Access denied for operation 'AWS::Bedrock::Guardrail'`, attach permissions like
[docs/aws-deploy-role-policy.json](docs/aws-deploy-role-policy.json) to that
deploy role. `bedrock:TagResource` is required because the Terraform guardrail
resource creates tags.

The CD workflow prints the effective AWS caller and runs `bedrock
list-guardrails` before Terraform applies the guardrail. If that preflight fails,
the assumed deploy role, permission boundary, SCP, or selected region is blocking
Bedrock access before Terraform runs.

If the deploy role cannot create guardrails, create one manually and set the
GitHub repository variable `BEDROCK_GUARDRAIL_ID` to its ID or ARN. To deploy
without guardrails temporarily, set `BEDROCK_GUARDRAIL_ENABLED=false`.

## CD Agent Evals and Security Scan

The CD workflow runs agent evals and a garak scan after deployment.

The eval step runs cases from `evals/jee_tutor_eval_cases.json` against the real
AgentCore handler, using the sample image folder and deployed Bedrock Guardrail
settings. It writes `eval_runs/agent-evals.json` and fails the workflow when the
pass rate is below `CD_EVAL_MIN_SCORE`.

The garak step starts a local REST adapter around the same handler, supplies the
sample image folder, sends garak probe prompts as `question_context`, and reuses
the deployed Bedrock Guardrail ID.

GitHub repository variables can tune the scan:

```text
CD_EVAL_MIN_SCORE=0.75
GARAK_PROBES=dan.Dan_11_0,promptinject.HijackHateHumansMini
GARAK_HIT_THRESHOLD=0
```

The default garak probe list is intentionally a CD smoke scan. Gemini calls are
rate-limited to 100 requests per minute, but full probe families such as
`dan,promptinject,encoding` can still exceed the 30-minute CI step timeout
because each prompt performs a full agent invocation with image analysis. Use
`GARAK_PROBES` for deeper scheduled scans when longer runtime is acceptable.

Eval and garak reports are uploaded as the `garak-security-reports` workflow artifact.

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

## Langfuse

Langfuse is optional and activates when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are present.

- Observability: AgentCore invocations are traced as spans, and LiteLLM calls are traced as generations.
- Prompt management: create Langfuse text prompts for the behavioral prompt keys in `src/config/llm.toml`. If any prompt is missing, the local fallback in `prompts.py` is used.
- Evaluation: include `evaluation_scores` in the invocation payload to attach scores to the active trace.

Managed prompt names:

```text
jee-tutor-vision-system-prompt
jee-tutor-agent-goal
jee-tutor-agent-backstory
jee-tutor-diagnosis-task-description
jee-tutor-diagnosis-task-expected-output
```

Example score payload:

```json
{
  "image_folder": "/app/input/attempt-images",
  "evaluation_scores": [
    {
      "name": "helpfulness",
      "value": 1,
      "data_type": "NUMERIC",
      "comment": "Useful hints without revealing the answer"
    }
  ]
}
```
