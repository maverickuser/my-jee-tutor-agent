# JEE Tutor Agent Block Diagram

```mermaid
flowchart TD
    client[Client or GitHub Actions] --> agentcore[Amazon Bedrock AgentCore Runtime]
    agentcore --> app[agentcore_app.py]
    app --> handler[agentcore_handler.py]
    handler --> service[TutorInvocationService]

    service --> validate[Validate TutorInvocationPayload]
    validate --> resolver[ImageInputResolver]
    resolver --> inputSources[Image input<br/>S3 prefix or data URI]
    resolver --> normalizedImages[Normalized image data URIs]

    validate --> trace[Langfuse invocation span<br/>image payloads redacted]
    normalizedImages --> inputGuardrail[Input RuntimeGuardrail<br/>Bedrock ApplyGuardrail]
    inputGuardrail -->|blocked| errorResponse[Error JSON response]
    inputGuardrail -->|allowed| workflow[run_tutor_workflow]

    workflow --> llmClient[VisionLLMClient]
    llmClient --> prompts[PromptProvider<br/>Langfuse or local prompts]
    llmClient --> modelConfig[VisionModelConfig<br/>model, keys, region, options]
    llmClient --> liteLLM[liteLLM completion]
    liteLLM --> visionModel[Vision-capable model]

    visionModel --> analysis[Coaching analysis markdown]
    analysis --> outputGuardrail[Output RuntimeGuardrail<br/>Bedrock ApplyGuardrail]
    outputGuardrail --> successResponse[Success JSON response]
    successResponse --> artifacts{save_analysis_pdf?}
    artifacts -->|yes| artifactWriter[AnalysisArtifactWriter]
    artifactWriter --> artifactStorage[S3 markdown and PDF artifacts]
    artifacts -->|no| finish[Finish invocation]
    artifactStorage --> finish
    errorResponse --> finish
    finish --> score[Record eval scores when supplied]
    score --> flush[Flush Langfuse]
    flush --> response[Return response]

    subgraph CD eval and security path
        cases[evals/jee_tutor_eval_cases.json] --> evalRunner[scripts/run_agent_evals.py]
        evalImages[CD eval images<br/>local fixtures or S3 prefix] --> evalRunner
        evalRunner --> handler
        evalRunner --> evalReport[eval_runs/agent-evals.json]
        garak[scripts/garak_agent_adapter.py] --> handler
        garak --> securityReport[garak security reports]
    end
```

## Main Blocks

- Runtime edge: `agentcore_app.py` and `agentcore_handler.py` keep the Bedrock AgentCore contract thin.
- Invocation service: `TutorInvocationService` validates input, resolves images, applies guardrails, runs the workflow, writes optional artifacts, and finalizes observability.
- Tutor workflow: resolved image data URIs are sent directly to the LiteLLM-backed vision model call; missing images fail the invocation instead of falling back to text-only analysis.
- Safety: Bedrock runtime guardrails wrap both input and output.
- Evaluation: CD evals read `evals/jee_tutor_eval_cases.json`, invoke the same handler, and score the returned structure or guardrail behavior.
