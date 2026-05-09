# Bedrock Guardrail for the JEE Tutor Agent.
# Terraform creates this guardrail and AgentCore injects its ID into the runtime.

locals {
  pii_entity_types = [
    "NAME",
    "EMAIL",
    "PHONE",
    "ADDRESS",
    "AGE",
    "USERNAME",
    "PASSWORD",
    "CREDIT_DEBIT_CARD_NUMBER",
    "CREDIT_DEBIT_CARD_CVV",
    "CREDIT_DEBIT_CARD_EXPIRY",
    "PIN",
    "US_SOCIAL_SECURITY_NUMBER",
    "US_PASSPORT_NUMBER",
    "US_BANK_ACCOUNT_NUMBER",
    "US_BANK_ROUTING_NUMBER",
    "INTERNATIONAL_BANK_ACCOUNT_NUMBER",
    "SWIFT_CODE",
    "AWS_ACCESS_KEY",
    "AWS_SECRET_KEY",
    "IP_ADDRESS",
    "URL",
  ]

  content_filter_types = [
    "HATE",
    "INSULTS",
    "MISCONDUCT",
    "SEXUAL",
    "VIOLENCE",
  ]

  # Cloud Control validates these optional arrays as present during updates.
  # Keep inert placeholder entries so updates do not fail on empty lists.
  placeholder_filter_text = "JEE_TUTOR_GUARDRAIL_PLACEHOLDER_9F8C7E6D"
}

resource "awscc_bedrock_guardrail" "jee_tutor" {
  count = var.bedrock_guardrail_enabled && var.bedrock_guardrail_id == "" ? 1 : 0

  name                      = "${var.project_name}-guardrail"
  description               = "Safety guardrail for the IIT JEE tutor agent."
  blocked_input_messaging   = "I can help with your JEE question, but please remove personal or unsafe information first."
  blocked_outputs_messaging = "I cannot return that response because it was blocked by the tutor safety guardrail."

  sensitive_information_policy_config = {
    pii_entities_config = [
      for pii_type in local.pii_entity_types : {
        type           = pii_type
        action         = "BLOCK"
        input_enabled  = true
        input_action   = "BLOCK"
        output_enabled = true
        output_action  = "ANONYMIZE"
      }
    ]

    regexes_config = [
      {
        name           = "placeholder-noop"
        description    = "No-op placeholder required for Cloud Control updates."
        pattern        = local.placeholder_filter_text
        action         = "NONE"
        input_enabled  = true
        input_action   = "NONE"
        output_enabled = true
        output_action  = "NONE"
      }
    ]
  }

  content_policy_config = {
    filters_config = [
      for filter_type in local.content_filter_types : {
        type            = filter_type
        input_enabled   = true
        input_action    = "BLOCK"
        input_strength  = "HIGH"
        output_enabled  = true
        output_action   = "BLOCK"
        output_strength = "HIGH"
      }
    ]
  }

  word_policy_config = {
    managed_word_lists_config = [
      {
        type           = "PROFANITY"
        input_enabled  = true
        input_action   = "BLOCK"
        output_enabled = true
        output_action  = "BLOCK"
      }
    ]

    words_config = [
      {
        text           = local.placeholder_filter_text
        input_enabled  = true
        input_action   = "NONE"
        output_enabled = true
        output_action  = "NONE"
      }
    ]
  }

  tags = [
    {
      key   = "Project"
      value = var.project_name
    },
    {
      key   = "Purpose"
      value = "Safety guardrail for IIT JEE tutor agent"
    },
  ]
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
