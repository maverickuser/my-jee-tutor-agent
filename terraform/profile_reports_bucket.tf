resource "aws_s3_bucket" "profile_reports" {
  count  = var.profile_report_s3_bucket_create ? 1 : 0
  bucket = local.profile_report_s3_bucket_name
}

resource "aws_s3_bucket_public_access_block" "profile_reports" {
  count  = var.profile_report_s3_bucket_create ? 1 : 0
  bucket = aws_s3_bucket.profile_reports[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "profile_reports" {
  count  = var.profile_report_s3_bucket_create ? 1 : 0
  bucket = aws_s3_bucket.profile_reports[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "profile_reports" {
  count  = var.profile_report_s3_bucket_create ? 1 : 0
  bucket = aws_s3_bucket.profile_reports[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "profile_reports" {
  count  = var.profile_report_s3_bucket_create ? 1 : 0
  bucket = aws_s3_bucket.profile_reports[0].id

  versioning_configuration {
    status = "Enabled"
  }
}
