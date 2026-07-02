# Structured Vision Diagnosis Output

Status: Proposed

Implementation breakdown:
[`quality-pipeline-implementation-plan.md`](quality-pipeline-implementation-plan.md)

## Objective

Replace model-generated Markdown with schema-constrained JSON, validate that JSON
with Pydantic and domain rules, and render the existing seven-column Markdown
table deterministically in application code.

The external invocation response, PDF workflow, and Markdown table contract must
remain unchanged.

## Motivation

The model currently owns both diagnosis and presentation. A syntactically
incorrect table, an unescaped pipe, or a malformed row can invalidate an
otherwise useful diagnosis. Structured output separates those concerns:

1. Gemini produces diagnosis data matching a JSON schema.
2. The application validates syntax and domain invariants.
3. The application renders validated data into stable Markdown.

This feature must not add another automatic LLM retry layer.

## Scope

### In scope

- A strict Pydantic schema for the seven diagnosis fields.
- A LiteLLM `response_format` request for Gemini models.
- JSON parsing and application-level semantic validation.
- Deterministic Markdown rendering.
- Prompt changes that request diagnosis data instead of Markdown.
- Langfuse metadata for structured-output validation.
- Unit and integration tests.

### Out of scope

- Student-name metadata or report filename changes.
- Per-image parallel calls.
- Model fallback.
- Changes to the public invocation response format.
- Repair prompts or automatic retries for invalid model output.

## Output Schema

Add a dedicated module such as `jee_tutor.agent.diagnosis_output`.

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str = Field(min_length=1)
    chapter: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    what_you_thought: str = Field(min_length=1)
    why_that_thought_is_wrong: str = Field(min_length=1)
    exact_concept_gap: str = Field(min_length=1)
    what_you_must_deep_dive: str = Field(min_length=1)

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_strings(cls, value):
        if isinstance(value, str):
            value = value.strip()
        if not value:
            raise ValueError("Diagnosis fields must not be blank.")
        return value


class DiagnosisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[QuestionDiagnosis] = Field(min_length=1)
```

The schema must preserve these existing sentinel values:

- `Unreadable from image`
- `Unable to determine from image`

Field descriptions should contain the current column definitions so Gemini
receives the semantic intent with the schema.

## Gemini Request

For Gemini models, add the following LiteLLM request parameter:

```python
response_format = {
    "type": "json_schema",
    "json_schema": {
        "name": "jee_question_diagnosis",
        "strict": True,
        "schema": DiagnosisResponse.model_json_schema(),
    },
}
```

The pinned LiteLLM adapter maps this OpenAI-compatible structure to Gemini's
JSON response MIME type and response schema. Pydantic validation remains
mandatory because the adapter removes unsupported schema keywords such as
`additionalProperties` and Gemini supports only a subset of JSON Schema.

Non-Gemini providers must use structured output only after their support is
explicitly verified. Until then, either retain the legacy Markdown path for
those providers or fail configuration validation with a clear error.

The existing request controls remain unchanged:

- `caching = false`
- `cache = {"no-cache": true}`
- `num_retries = 0`
- configured request timeout

## Prompt Contract

Revise the vision prompt as follows:

- Retain all source-grounding, image-order, diagnostic-quality, unreadable-image,
  multiple-correct, and unattempted-question rules.
- Replace the Markdown output section with a structured-output section.
- Tell the model to return one `questions` item per image in image order.
- Tell the model not to add commentary outside the schema.
- Do not duplicate the full JSON schema in prompt text; field descriptions in
  the schema are authoritative.
- Remove Markdown-specific instructions such as pipe escaping and physical
  line restrictions.

Langfuse prompt versions must be updated together with the local fallback
prompts before rollout.

## Parsing and Validation

`VisionLLMClient.analyze_vision` should parse the completion content:

```python
diagnosis = DiagnosisResponse.model_validate_json(content)
```

Parsing or schema errors must be converted to `OutputValidationError` with safe,
concise details. Raw model content must not be returned in errors or logs.

After Pydantic validation, enforce these domain invariants:

1. `len(questions)` equals the number of resolved invocation images.
2. Items remain in image order.
3. Question numbers are not duplicated, except that multiple unreadable images
   may each use `Unreadable from image`.
4. When all filename-derived expected question numbers are available, normalized
   actual numbers must match the existing expected-number policy.
5. Every field remains non-empty after trimming.
6. The model must not create extra questions.

The expected image count and expected question numbers should be passed into
the structured validator rather than inferred from model output.

Schema and semantic validation failures are non-retryable. Transport retries
remain limited to the configured timeout and HTTP status policy.

## Deterministic Markdown Rendering

Add a renderer that maps fields to the existing columns:

| JSON field | Markdown column |
|---|---|
| `question_number` | Question Number |
| `chapter` | Chapter |
| `topic` | Topic |
| `what_you_thought` | What You Thought |
| `why_that_thought_is_wrong` | Why That Thought Is Wrong |
| `exact_concept_gap` | Exact Concept Gap |
| `what_you_must_deep_dive` | What You Must Deep-Dive |

The renderer must:

- Emit the existing headers in the existing order.
- Emit exactly one physical row per question.
- Replace line breaks in cells with spaces.
- Escape backslashes and Markdown pipe characters safely.
- Preserve inline mathematical notation.
- Return no text outside the table.

The rendered table should continue through the existing Markdown validator
during migration. Once renderer tests prove the output is structurally
guaranteed, duplicate parsing may be removed in a separate change.

## Data Flow

```text
Invocation images
    -> constrained CrewAI ReAct diagnosis
    -> memoized vision tool
    -> VisionLLMClient
    -> Gemini JSON-schema response
    -> CrewAI returns the memoized observation without rewriting
    -> Pydantic parsing
    -> domain validation
    -> deterministic Markdown renderer
    -> existing response guardrail
    -> API response and PDF artifact
```

## Error Handling

Use distinct safe error categories:

- `structured_output_invalid_json`
- `structured_output_schema_mismatch`
- `structured_output_wrong_question_count`
- `structured_output_question_number_mismatch`
- `structured_output_duplicate_question`

The invocation response should continue using the existing tutor workflow error
envelope. Details may include validation category, expected count, and actual
count, but must not include images or full model output.

## Observability

Record the following Langfuse generation metadata:

- `output_format = "json_schema"`
- `schema_name = "jee_question_diagnosis"`
- `schema_version = 1`
- `expected_image_count`
- `validation_status`
- `validation_error_category`, when applicable

Keep image payloads and raw invalid output redacted. Token and cost accounting
remain unchanged.

## Compatibility and Migration

- The public response continues to contain the same Markdown analysis table.
- PDF generation continues to receive Markdown.
- Existing guardrails continue to inspect the rendered Markdown.
- Existing idempotency behavior is unchanged.
- The schema must be versioned in code so later field changes can be rolled out
  deliberately.

Recommended rollout:

1. Unit-test schema, semantic validation, and rendering.
2. Run a local mocked end-to-end test.
3. Run a one-image live Gemini test.
4. Run a six-image live Gemini test.
5. Deploy behind a configuration flag.
6. Monitor validation failures before removing the legacy path.

## Test Requirements

Tests must cover:

- Valid one-question and multi-question JSON.
- Malformed JSON.
- Missing, extra, null, and blank fields.
- Incorrect root object.
- Wrong question count.
- Duplicate question numbers.
- Reordered or mismatched question numbers.
- Multiple `Unreadable from image` entries.
- Markdown pipes, backslashes, and newlines in values.
- Mathematical notation preservation.
- No retry on schema or semantic validation failure.
- Retry remains active for timeout and HTTP 429, 500, and 503.
- Langfuse metadata is populated without raw image or invalid-output content.
- Existing API and PDF outputs remain compatible.

## Acceptance Criteria

The feature is complete when:

1. Gemini receives a response schema on every configured vision request.
2. Invalid JSON cannot reach API or PDF output.
3. Every successful invocation has exactly one validated result per image.
4. Markdown is generated only by application code.
5. The external Markdown table contract is unchanged.
6. Structured validation failures do not trigger an LLM retry.
7. Tests, Ruff, coverage, and a six-image live validation pass.
