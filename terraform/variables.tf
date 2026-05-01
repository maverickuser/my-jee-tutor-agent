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

variable "bucket_name" {
  description = "Optional explicit S3 bucket name. Leave empty to auto-generate."
  type        = string
  default     = ""
}

variable "lambda_image_uri" {
  description = "Full ECR image URI, including a tag or digest, built by CI/CD."
  type        = string
}

variable "litellm_api_key" {
  description = "Fallback API key used when provider-specific keys are not supplied."
  type        = string
  default     = ""
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key used when VISION_MODEL points to an OpenAI model."
  type        = string
  default     = ""
  sensitive   = true
}

variable "google_api_key" {
  description = "Google AI Studio API key used when VISION_MODEL points to a Gemini model."
  type        = string
  default     = ""
  sensitive   = true
}

variable "litellm_base_url" {
  description = "Optional liteLLM proxy base URL."
  type        = string
  default     = ""
}

variable "vision_model" {
  description = "Vision-capable model identifier used by liteLLM."
  type        = string
  default     = "openai/gpt-4o"
}
