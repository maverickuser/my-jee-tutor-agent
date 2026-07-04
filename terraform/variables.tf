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
  default     = false
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
  default     = "analysis@konceptai.com"
}

variable "email_subject_template" {
  description = "Configured subject template for analysis email delivery."
  type        = string
  default     = "Test Analysis Report"
}

variable "email_body_template" {
  description = "Configured email body template for analysis email delivery."
  type        = string
  default     = <<-EOT
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>JEE Tutor Analysis</title>
      </head>
      <body style="margin:0;padding:0;background-color:#f6f7fb;font-family:Arial,Helvetica,sans-serif;color:#1f2937;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f6f7fb;padding:32px 16px;">
          <tr>
            <td align="center">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background-color:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
                <tr>
                  <td style="padding:28px 32px;border-bottom:1px solid #e5e7eb;">
                    <h1 style="margin:0;font-size:22px;line-height:1.3;color:#111827;">Your analysis report is ready</h1>
                  </td>
                </tr>
                <tr>
                  <td style="padding:24px 32px;">
                    <p style="margin:0 0 16px;font-size:15px;line-height:1.6;">The PDF report for your latest JEE Tutor analysis is attached to this email.</p>
                    <p style="margin:0;font-size:14px;line-height:1.6;color:#6b7280;">If you need to review the report later, keep this email for reference.</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0 32px 28px;">
                    <p style="margin:0;font-size:13px;line-height:1.5;color:#9ca3af;">Delivery ID: {delivery_id}</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
  EOT
}
