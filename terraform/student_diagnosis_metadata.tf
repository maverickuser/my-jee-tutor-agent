resource "aws_dynamodb_table" "student_diagnosis_metadata" {
  name                        = local.student_diagnosis_metadata_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "email"
  range_key                   = "subject_report_key"
  deletion_protection_enabled = true

  attribute {
    name = "email"
    type = "S"
  }

  attribute {
    name = "subject_report_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}
