locals {
  ecr_repo_name           = "${var.project_name}-repo"
  agentcore_runtime_name  = substr("JeeTutorAgent_${replace(var.project_name, "/[^a-zA-Z0-9_]/", "_")}", 0, 48)
  agentcore_endpoint_name = "DefaultEndpoint"
  s3_image_bucket_name    = substr("${lower(replace(var.project_name, "/[^0-9A-Za-z-]/", "-"))}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-images", 0, 63)
  s3_image_prefixes       = ["physics/", "chemistry/", "maths/"]

  # Use created guardrail if not overridden via var.bedrock_guardrail_id
  bedrock_guardrail_id = var.bedrock_guardrail_id != "" ? var.bedrock_guardrail_id : try(awscc_bedrock_guardrail.jee_tutor[0].guardrail_id, "")
}

data "aws_caller_identity" "current" {}

resource "aws_ecr_repository" "agentcore_repo" {
  name                 = local.ecr_repo_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_s3_bucket" "image_inputs" {
  bucket = local.s3_image_bucket_name
}

resource "aws_s3_bucket_public_access_block" "image_inputs" {
  bucket = aws_s3_bucket.image_inputs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "image_inputs" {
  bucket = aws_s3_bucket.image_inputs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "image_inputs" {
  bucket = aws_s3_bucket.image_inputs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_object" "image_input_prefixes" {
  for_each = toset(local.s3_image_prefixes)

  bucket       = aws_s3_bucket.image_inputs.id
  key          = each.value
  content      = ""
  content_type = "application/x-directory"
}

resource "aws_iam_role" "agentcore_runtime" {
  name = "${var.project_name}-agentcore-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AssumeRolePolicy"
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "agentcore_runtime_access" {
  name = "${var.project_name}-agentcore-access"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid    = "ECRImageAccess"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = aws_ecr_repository.agentcore_repo.arn
      },
      {
        Sid      = "ECRTokenAccess"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "AgentCoreLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"
        ]
      },
      {
        Sid    = "AgentCoreLogStreams"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
        ]
      },
      {
        Sid    = "AgentCoreTracing"
        Effect = "Allow"
        Action = [
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
          "xray:PutTelemetryRecords",
          "xray:PutTraceSegments"
        ]
        Resource = "*"
      },
      {
        Sid      = "AgentCoreMetrics"
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "bedrock-agentcore"
          }
        }
      },
      {
        Sid    = "BedrockModelInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
        ]
      },
      {
        Sid    = "BedrockRuntimeGuardrails"
        Effect = "Allow"
        Action = [
          "bedrock:ApplyGuardrail"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:guardrail/*"
        ]
      },
      {
        Sid    = "ManagedS3ImageObjectReadWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:AbortMultipartUpload"
        ]
        Resource = [
          for prefix in local.s3_image_prefixes :
          "${aws_s3_bucket.image_inputs.arn}/${prefix}*"
        ]
      },
      {
        Sid    = "ManagedS3ImagePrefixList"
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.image_inputs.arn
        Condition = {
          StringLike = {
            "s3:prefix" = concat(local.s3_image_prefixes, [
              for prefix in local.s3_image_prefixes :
              "${prefix}*"
            ])
          }
        }
      }
    ],
      length(var.s3_image_input_object_arns) > 0 ? [
        {
          Sid      = "S3ImageObjectRead"
          Effect   = "Allow"
          Action   = ["s3:GetObject"]
          Resource = var.s3_image_input_object_arns
        }
      ] : [],
      length(var.s3_image_input_bucket_arns) > 0 ? [
        {
          Sid      = "S3ImagePrefixList"
          Effect   = "Allow"
          Action   = ["s3:ListBucket"]
          Resource = var.s3_image_input_bucket_arns
        }
      ] : []
    )
  })
}

resource "awscc_bedrockagentcore_runtime" "tutor" {
  agent_runtime_name     = local.agentcore_runtime_name
  description            = "CrewAI IIT JEE tutor agent runtime"
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
  }

  network_configuration = {
    network_mode = "PUBLIC"
  }

  depends_on = [aws_iam_role_policy.agentcore_runtime_access]
}

resource "awscc_bedrockagentcore_runtime_endpoint" "tutor_default" {
  agent_runtime_id      = awscc_bedrockagentcore_runtime.tutor.agent_runtime_id
  agent_runtime_version = awscc_bedrockagentcore_runtime.tutor.agent_runtime_version
  name                  = local.agentcore_endpoint_name
  description           = "Default endpoint for the CrewAI IIT JEE tutor agent"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.agentcore_repo.repository_url
}

output "image_input_bucket_name" {
  value = aws_s3_bucket.image_inputs.bucket
}

output "image_input_subject_prefixes" {
  value = local.s3_image_prefixes
}

output "agentcore_runtime_arn" {
  value = awscc_bedrockagentcore_runtime.tutor.agent_runtime_arn
}

output "agentcore_runtime_id" {
  value = awscc_bedrockagentcore_runtime.tutor.agent_runtime_id
}

output "agentcore_endpoint_arn" {
  value = awscc_bedrockagentcore_runtime_endpoint.tutor_default.agent_runtime_endpoint_arn
}
