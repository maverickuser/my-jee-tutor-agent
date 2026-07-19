resource "aws_dynamodb_table" "invocation_status" {
  name                        = local.invocation_status_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "invocation_id"
  deletion_protection_enabled = true

  attribute {
    name = "invocation_id"
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
