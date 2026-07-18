resource "aws_cloudwatch_log_group" "agentcore_runtime" {
  name              = "/aws/bedrock-agentcore/runtimes/${local.agentcore_runtime_name}"
  retention_in_days = var.cloudwatch_log_retention_days
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
        Sid    = "InvokeEmailDeliveryLambda"
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = [
          aws_lambda_function.email_delivery.arn
        ]
      }
      ],
      var.invocation_status_enabled ? [
        {
          Sid    = "WriteInvocationStatus"
          Effect = "Allow"
          Action = [
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:DescribeTable"
          ]
          Resource = aws_dynamodb_table.invocation_status.arn
        }
      ] : [],
      var.student_diagnosis_metadata_enabled ? [
        {
          Sid    = "ReadWriteStudentDiagnosisMetadata"
          Effect = "Allow"
          Action = [
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:Query",
            "dynamodb:DescribeTable"
          ]
          Resource = aws_dynamodb_table.student_diagnosis_metadata.arn
        }
      ] : [],
      length(var.s3_image_input_object_arns) > 0 ? [
        {
          Sid    = "S3ImageObjectReadWrite"
          Effect = "Allow"
          Action = [
            "s3:GetObject",
            "s3:PutObject",
            "s3:AbortMultipartUpload"
          ]
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
      ] : [],
      var.cd_eval_bucket_name != "" ? [
        {
          Sid    = "S3CdEvalObjectReadWrite"
          Effect = "Allow"
          Action = [
            "s3:GetObject",
            "s3:PutObject",
            "s3:AbortMultipartUpload"
          ]
          Resource = [
            "arn:aws:s3:::${var.cd_eval_bucket_name}/cd-evals-images/*"
          ]
        }
      ] : [],
      var.cd_eval_bucket_name != "" ? [
        {
          Sid      = "S3CdEvalPrefixList"
          Effect   = "Allow"
          Action   = ["s3:ListBucket"]
          Resource = "arn:aws:s3:::${var.cd_eval_bucket_name}"
          Condition = {
            StringLike = {
              "s3:prefix" = [
                "cd-evals-images/*"
              ]
            }
          }
        }
      ] : [],
      local.curriculum_taxonomy_object_arn != "" ? [
        {
          Sid      = "S3CurriculumTaxonomyRead"
          Effect   = "Allow"
          Action   = ["s3:GetObject"]
          Resource = local.curriculum_taxonomy_object_arn
        }
      ] : [],
      var.newrelic_log_forwarding_enabled && var.newrelic_license_key_secret_arn != "" ? [
        {
          Sid      = "ReadNewRelicLicenseKey"
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue"]
          Resource = var.newrelic_license_key_secret_arn
        }
    ] : [])
  })
}

resource "time_sleep" "agentcore_iam_propagation" {
  create_duration = "45s"

  depends_on = [
    aws_iam_role.agentcore_runtime,
    aws_iam_role_policy.agentcore_runtime_access,
  ]
}
