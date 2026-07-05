resource "aws_iam_role" "email_delivery" {
  name = "${var.project_name}-email-delivery-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AssumeRolePolicy"
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "email_delivery_access" {
  name = "${var.project_name}-email-delivery-access"
  role = aws_iam_role.email_delivery.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      length(var.s3_image_input_object_arns) > 0 ? [
        {
          Sid    = "ReadAnalysisArtifacts"
          Effect = "Allow"
          Action = [
            "s3:GetObject"
          ]
          Resource = var.s3_image_input_object_arns
        },
      ] : [],
      [
        {
          Sid    = "SendEmailViaSES"
          Effect = "Allow"
          Action = [
            "ses:SendRawEmail"
          ]
          Resource = "*"
        }
      ],
      var.newrelic_log_forwarding_enabled && var.newrelic_license_key_secret_arn != "" ? [
        {
          Sid      = "ReadNewRelicLicenseKey"
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue"]
          Resource = var.newrelic_license_key_secret_arn
        }
      ] : [],
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
      ] : []
    )
  })
}

resource "aws_iam_role_policy_attachment" "email_delivery_basic_logs" {
  role       = aws_iam_role.email_delivery.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "email_delivery" {
  name              = "/aws/lambda/${local.email_delivery_function_name}"
  retention_in_days = var.cloudwatch_log_retention_days
}

resource "aws_lambda_function" "email_delivery" {
  function_name = local.email_delivery_function_name
  role          = aws_iam_role.email_delivery.arn
  package_type  = "Image"
  architectures = ["arm64"]
  image_uri     = var.agentcore_image_uri
  timeout       = var.email_delivery_function_timeout_seconds
  memory_size   = var.email_delivery_function_memory_mb

  image_config {
    command = [
      "python",
      "-m",
      "awslambdaric",
      "jee_tutor.email.worker.handle_email_delivery",
    ]
  }

  environment {
    variables = {
      EMAIL_DELIVERY_PROVIDER          = "lambda"
      EMAIL_FROM_ADDRESS               = var.email_from_address
      EMAIL_SUBJECT_TEMPLATE           = var.email_subject_template
      EMAIL_BODY_TEMPLATE              = local.email_body_template_compact
      EMAIL_REGION                     = var.aws_region
      NEW_RELIC_LOG_ENABLED            = tostring(var.newrelic_log_forwarding_enabled)
      NEW_RELIC_LICENSE_KEY_SECRET_ARN = var.newrelic_license_key_secret_arn
      NEW_RELIC_REGION                 = var.newrelic_region
      INVOCATION_STATUS_ENABLED        = tostring(var.invocation_status_enabled)
      INVOCATION_STATUS_TABLE_NAME     = local.invocation_status_table_name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.email_delivery,
    aws_iam_role_policy_attachment.email_delivery_basic_logs,
  ]
}
