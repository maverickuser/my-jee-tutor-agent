# JEE Tutor Agent Block Diagram

```mermaid
flowchart LR
    user[Client / Web App] --> agentcore

    subgraph github[GitHub]
        code[Source Code] --> actions[GitHub Actions CI/CD]
    end

    subgraph aws[AWS ap-south-1 Region]
        ecr[Amazon ECR<br/>Agent container image]
        tfstate[S3<br/>Terraform state]

        subgraph runtime[Amazon Bedrock AgentCore]
            endpoint[DEFAULT Endpoint]
            agentcore[JEE Tutor Runtime<br/>Python container]
        end

        s3input[S3<br/>Question screenshots]
        s3report[S3<br/>Analysis PDF / Markdown]
        guardrails[Amazon Bedrock Guardrails]
        crew[CrewAI Agent<br/>must call vision tool]
        validator[Validation Gate<br/>tool call + markdown rows]
        llm[Vision LLM<br/>Gemini / OpenAI / Bedrock]
        logs[CloudWatch Logs]
        newrelic[New Relic<br/>Logs and metrics]
        langfuse[Langfuse<br/>Prompts and traces]

        endpoint --> agentcore
        agentcore --> s3input
        agentcore --> guardrails
        agentcore --> crew
        crew --> llm
        crew --> validator
        validator --> guardrails
        agentcore --> s3report
        agentcore --> logs
        agentcore --> langfuse
        logs --> newrelic
    end

    actions -->|Run tests| code
    actions -->|Build and push image| ecr
    actions -->|Terraform apply| tfstate
    actions -->|Deploy runtime| agentcore
    ecr -->|Container image| agentcore
```

## Flow

1. GitHub Actions runs tests, builds the container image, pushes it to ECR, and applies Terraform.
2. Terraform creates the AgentCore runtime, IAM role, Bedrock Guardrail, CloudWatch logging, and related AWS resources.
3. The client invokes the AgentCore `DEFAULT` endpoint.
4. The runtime reads question screenshots from S3 or accepts a direct image data URI.
5. Bedrock Guardrails check input before the agent runs.
6. CrewAI must call the vision tool, which calls the configured vision LLM through LiteLLM.
7. The validation gate checks that the tool ran, row count matches image count, and markdown question numbers match S3 filenames.
8. Bedrock Guardrails check the validated output.
9. The runtime returns JSON analysis and optionally writes PDF/Markdown reports to S3.
10. Logs go to CloudWatch and optionally New Relic; prompts/traces go to Langfuse.
