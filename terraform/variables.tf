variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Base name used to prefix AWS resources."
  type        = string
  default     = "jee-tutor-agent"
}

variable "agentcore_image_uri" {
  description = "Full ECR image URI, including a tag or digest, for the Bedrock AgentCore runtime container."
  type        = string
}

variable "litellm_api_key" {
  description = "Fallback API key used when provider-specific keys are not supplied."
  type        = string
  default     = ""
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key used when the configured model points to an OpenAI model."
  type        = string
  default     = ""
  sensitive   = true
}

variable "google_api_key" {
  description = "Google AI Studio API key used when the configured model points to a Gemini model."
  type        = string
  default     = ""
  sensitive   = true
}

variable "litellm_base_url" {
  description = "Optional liteLLM proxy base URL."
  type        = string
  default     = ""
}

variable "langfuse_public_key" {
  description = "Langfuse public key for observability, prompt management, and evaluation scores."
  type        = string
  default     = ""
  sensitive   = true
}

variable "langfuse_secret_key" {
  description = "Langfuse secret key for observability, prompt management, and evaluation scores."
  type        = string
  default     = ""
  sensitive   = true
}

variable "langfuse_base_url" {
  description = "Langfuse base URL, for example https://cloud.langfuse.com or https://us.cloud.langfuse.com."
  type        = string
  default     = "https://cloud.langfuse.com"
}

variable "bedrock_guardrail_enabled" {
  description = "Enable Bedrock ApplyGuardrail checks at the AgentCore runtime boundary."
  type        = bool
  default     = true
}

variable "bedrock_guardrail_id" {
  description = "Bedrock Guardrail identifier or ARN used by ApplyGuardrail."
  type        = string
  default     = ""
}

variable "bedrock_guardrail_version" {
  description = "Bedrock Guardrail version to apply, for example DRAFT or a published version number."
  type        = string
  default     = "DRAFT"
}

variable "bedrock_guardrail_output_scope" {
  description = "ApplyGuardrail response scope: INTERVENTIONS or FULL."
  type        = string
  default     = "INTERVENTIONS"
}

variable "bedrock_guardrail_fail_closed" {
  description = "Block requests when a configured guardrail check fails."
  type        = bool
  default     = true
}

variable "bedrock_guardrail_include_image" {
  description = "Include png/jpeg attempt images in input guardrail checks."
  type        = bool
  default     = true
}

variable "cloudwatch_log_retention_days" {
  description = "Number of days to retain AgentCore runtime CloudWatch logs."
  type        = number
  default     = 3
}

variable "newrelic_log_forwarding_enabled" {
  description = "Enable direct asynchronous application log delivery to New Relic."
  type        = bool
  default     = true
}

variable "newrelic_license_key_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the New Relic ingest license key."
  type        = string
  default     = ""
}

variable "newrelic_region" {
  description = "New Relic ingest region: US or EU."
  type        = string
  default     = "US"
  validation {
    condition     = contains(["US", "EU"], upper(var.newrelic_region))
    error_message = "newrelic_region must be US or EU."
  }
}

variable "invocation_status_enabled" {
  description = "Enable persistent invocation status tracking in DynamoDB."
  type        = bool
  default     = true
}

variable "s3_image_input_bucket_arns" {
  description = "S3 bucket ARNs the AgentCore runtime can list for image_s3_prefix inputs."
  type        = list(string)
  default     = []
}

variable "s3_image_input_object_arns" {
  description = "S3 object ARNs the AgentCore runtime can read and write for image_s3_uri, image_s3_prefix, and analysis artifacts."
  type        = list(string)
  default     = []
}

variable "cd_eval_bucket_name" {
  description = "S3 bucket containing mandatory CD smoke and agent-eval image prefixes."
  type        = string
  default     = ""
}

variable "curriculum_taxonomy_s3_uri" {
  description = "Stable S3 URI for the approved curriculum taxonomy JSON consumed by the runtime."
  type        = string
  default     = "s3://jee-tutor-agent-terraform-state/curriculum/jee_curriculum_taxonomy.json"

  validation {
    condition     = var.curriculum_taxonomy_s3_uri == "" || can(regex("^s3://[^/]+/.+", var.curriculum_taxonomy_s3_uri))
    error_message = "curriculum_taxonomy_s3_uri must be empty or a valid s3://bucket/key URI."
  }
}

variable "curriculum_taxonomy_required" {
  description = "Fail closed when the runtime cannot load a configured curriculum taxonomy."
  type        = bool
  default     = true
}

variable "curriculum_taxonomy_cache_ttl_seconds" {
  description = "Runtime in-memory cache TTL for the curriculum taxonomy JSON."
  type        = number
  default     = 3600
}

variable "email_delivery_function_memory_mb" {
  description = "Memory size for the email delivery Lambda worker."
  type        = number
  default     = 512
}

variable "email_delivery_function_timeout_seconds" {
  description = "Timeout for the email delivery Lambda worker."
  type        = number
  default     = 60
}

variable "email_from_address" {
  description = "Configured sender email address used by the email delivery flow."
  type        = string
  default     = "Koncept Agent App <sociusnest@gmail.com>"
}

variable "email_subject_template" {
  description = "Configured subject template for analysis email delivery."
  type        = string
  default     = "Analysis Report"
}

variable "email_body_template" {
  description = "Configured email body template for analysis email delivery."
  type        = string
  default     = "<!doctype html><html><body><p>Your analysis PDF is attached.</p><p>Delivery ID: {delivery_id}</p></body></html>"
}
