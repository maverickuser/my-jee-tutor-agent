resource "awscc_bedrockagentcore_runtime" "tutor" {
  agent_runtime_name     = local.agentcore_runtime_name
  description            = "IIT JEE tutor agent runtime"
  role_arn               = aws_iam_role.agentcore_runtime.arn
  protocol_configuration = "HTTP"

  agent_runtime_artifact = {
    container_configuration = {
      container_uri = var.agentcore_image_uri
    }
  }

  environment_variables = {
    LITELLM_API_KEY     = var.litellm_api_key
    OPENAI_API_KEY      = var.openai_api_key
    GOOGLE_API_KEY      = var.google_api_key
    LITELLM_BASE_URL    = var.litellm_base_url
    LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
    LANGFUSE_SECRET_KEY = var.langfuse_secret_key
    LANGFUSE_BASE_URL   = var.langfuse_base_url

    BEDROCK_GUARDRAIL_ENABLED       = tostring(local.bedrock_guardrail_id != "" && var.bedrock_guardrail_enabled)
    BEDROCK_GUARDRAIL_ID            = local.bedrock_guardrail_id
    BEDROCK_GUARDRAIL_VERSION       = var.bedrock_guardrail_version
    BEDROCK_GUARDRAIL_REGION        = var.aws_region
    BEDROCK_GUARDRAIL_OUTPUT_SCOPE  = var.bedrock_guardrail_output_scope
    BEDROCK_GUARDRAIL_FAIL_CLOSED   = tostring(var.bedrock_guardrail_fail_closed)
    BEDROCK_GUARDRAIL_INCLUDE_IMAGE = tostring(var.bedrock_guardrail_include_image)

    NEW_RELIC_LOG_ENABLED            = tostring(var.newrelic_log_forwarding_enabled)
    NEW_RELIC_LICENSE_KEY_SECRET_ARN = var.newrelic_license_key_secret_arn
    NEW_RELIC_REGION                 = var.newrelic_region

    EMAIL_DELIVERY_PROVIDER     = "lambda"
    EMAIL_DELIVERY_FUNCTION_ARN = aws_lambda_function.email_delivery.arn
    EMAIL_FROM_ADDRESS          = var.email_from_address
    EMAIL_SUBJECT_TEMPLATE      = var.email_subject_template
    EMAIL_BODY_TEMPLATE         = local.email_body_template_compact
    EMAIL_REGION                = var.aws_region
  }

  network_configuration = {
    network_mode = "PUBLIC"
  }

  depends_on = [
    aws_cloudwatch_log_group.agentcore_runtime,
    time_sleep.agentcore_iam_propagation,
  ]
}
