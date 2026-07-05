output "ecr_repository_url" {
  value = aws_ecr_repository.agentcore_repo.repository_url
}

output "agentcore_log_group_name" {
  value = aws_cloudwatch_log_group.agentcore_runtime.name
}

output "agentcore_runtime_arn" {
  value = awscc_bedrockagentcore_runtime.tutor.agent_runtime_arn
}

output "agentcore_runtime_id" {
  value = awscc_bedrockagentcore_runtime.tutor.agent_runtime_id
}

output "agentcore_endpoint_arn" {
  value = "${awscc_bedrockagentcore_runtime.tutor.agent_runtime_arn}/runtime-endpoint/${local.agentcore_endpoint_name}"
}

output "email_delivery_function_name" {
  value = aws_lambda_function.email_delivery.function_name
}

output "email_delivery_function_arn" {
  value = aws_lambda_function.email_delivery.arn
}

output "bedrock_guardrail_id" {
  value       = local.bedrock_guardrail_id
  description = "Bedrock Guardrail ID injected into the AgentCore runtime."
}

output "bedrock_guardrail_arn" {
  value       = try(awscc_bedrock_guardrail.jee_tutor[0].guardrail_arn, null)
  description = "Bedrock Guardrail ARN."
}

output "bedrock_guardrail_version" {
  value       = var.bedrock_guardrail_version
  description = "Guardrail version injected into the AgentCore runtime."
}

output "invocation_status_table_name" {
  value       = aws_dynamodb_table.invocation_status.name
  description = "DynamoDB table used for agent invocation status tracking."
}
