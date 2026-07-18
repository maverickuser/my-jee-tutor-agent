resource "aws_dynamodb_table" "evidence_embeddings" {
  name         = local.evidence_embedding_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "diagnosis_json_s3_uri"
  range_key    = "embedding_key"

  attribute {
    name = "diagnosis_json_s3_uri"
    type = "S"
  }

  attribute {
    name = "embedding_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}
