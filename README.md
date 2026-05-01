# My JEE Tutor Agent

AI-powered IIT JEE instructor built on AWS Lambda, S3, Terraform, CrewAI, and liteLLM.

## What it does

1. A student uploads a `.jpg` or `.png` attempt image into `uploads/` in S3.
2. S3 triggers the Lambda container.
3. Lambda converts the image to a data URI and sends it into a CrewAI tutor workflow.
4. The tutor uses liteLLM to call a vision-capable OpenAI or Google model.
5. The coaching response is saved back into `outputs/` as JSON.

## Local setup with Poetry

```powershell
cd S:\PythonWorkspace\my-jee-tutor-agent
poetry lock
poetry install --with dev
```

## Runtime environment variables

Set the model you want Lambda to use:

```text
VISION_MODEL=openai/gpt-4o
```

OpenAI option:

```text
OPENAI_API_KEY=your-openai-key
```

Google Gemini option:

```text
VISION_MODEL=gemini/gemini-1.5-pro
GOOGLE_API_KEY=your-google-key
```

Optional shared fallback and proxy settings:

```text
LITELLM_API_KEY=optional-fallback-key
LITELLM_BASE_URL=https://your-litellm-proxy.example.com
```

## GitHub Actions secrets and vars

Secrets:

```text
AWS_ROLE_TO_ASSUME
OPENAI_API_KEY
GOOGLE_API_KEY
LITELLM_API_KEY
LITELLM_BASE_URL
```

Repository variables:

```text
AWS_REGION
PROJECT_NAME
VISION_MODEL
TF_STATE_BUCKET
TF_STATE_KEY
TF_STATE_DYNAMODB_TABLE
```

## Terraform notes

- The deployment workflow creates the ECR repository first.
- Then it builds and pushes the Lambda image.
- Then it applies the full Terraform stack with the real image URI.
- Lambda is restricted to `s3:GetObject` on `uploads/*` and `s3:PutObject` on `outputs/*`.
