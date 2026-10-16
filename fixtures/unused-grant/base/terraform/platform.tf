# Shared platform resources. Owner: platform team.
#
# Encryption for the queues, the container registries, the nightly schedules, bucket settings, the database's
# parameter group, internal DNS and the internal API in front of billing-api. Buckets use SSE-S3 (AES256), not KMS,
# so nothing that reads them needs a key grant. Every bucket blocks public access; marketing's public files reach
# the website through its CDN, never straight from the bucket.

# Queues ---------------------------------------------------------------------------------------------------------

resource "aws_kms_key" "queues" {
  description             = "Encrypts the order-events queues"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdministers"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::111122223333:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # SQS encrypts and decrypts each message with this key on the sender's and the receiver's behalf.
        Sid       = "OrdersTasksUseKeyThroughSqs"
        Effect    = "Allow"
        Principal = { AWS = ["arn:aws:iam::111122223333:role/orders-api-task", "arn:aws:iam::111122223333:role/orders-worker-task"] }
        Action    = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource  = "*"
        Condition = { StringEquals = { "kms:ViaService" = "sqs.eu-west-1.amazonaws.com" } }
      }
    ]
  })
}

resource "aws_kms_alias" "queues" {
  name          = "alias/demo-queues"
  target_key_id = aws_kms_key.queues.key_id
}

# Container images -----------------------------------------------------------------------------------------------

resource "aws_ecr_repository" "orders_api" {
  name                 = "orders-api"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "KMS" }
}

resource "aws_ecr_repository" "orders_worker" {
  name                 = "orders-worker"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "KMS" }
}

# Nightly schedules ----------------------------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "billing_nightly" {
  name                = "billing-job-nightly"
  description         = "Invoice yesterday's fulfilled orders"
  schedule_expression = "cron(0 2 * * ? *)"
}

resource "aws_cloudwatch_event_target" "billing_nightly" {
  rule = aws_cloudwatch_event_rule.billing_nightly.name
  arn  = aws_lambda_function.billing_job.arn
}

resource "aws_lambda_permission" "billing_nightly" {
  statement_id  = "AllowNightlySchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.billing_job.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.billing_nightly.arn
}

resource "aws_cloudwatch_event_rule" "analytics_nightly" {
  name                = "analytics-export-nightly"
  description         = "Export yesterday's orders to the data lake, after billing"
  schedule_expression = "cron(0 3 * * ? *)"
}

resource "aws_cloudwatch_event_target" "analytics_nightly" {
  rule = aws_cloudwatch_event_rule.analytics_nightly.name
  arn  = aws_lambda_function.analytics_export.arn
}

resource "aws_lambda_permission" "analytics_nightly" {
  statement_id  = "AllowNightlySchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.analytics_export.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.analytics_nightly.arn
}

# Bucket settings ------------------------------------------------------------------------------------------------

resource "aws_s3_bucket_versioning" "app_logs" {
  bucket = aws_s3_bucket.app_logs.bucket
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_versioning" "company_files" {
  bucket = aws_s3_bucket.company_files.bucket
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.bucket
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.bucket
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "app_logs" {
  bucket = aws_s3_bucket.app_logs.bucket
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "company_files" {
  bucket = aws_s3_bucket.company_files.bucket
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.bucket
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.bucket
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "app_logs" {
  bucket                  = aws_s3_bucket.app_logs.bucket
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "company_files" {
  bucket                  = aws_s3_bucket.company_files.bucket
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket                  = aws_s3_bucket.data_lake.bucket
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.bucket
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Application logs are kept 90 days; older versions of everything else are kept a year, then removed.
resource "aws_s3_bucket_lifecycle_configuration" "app_logs" {
  bucket = aws_s3_bucket.app_logs.bucket
  rule {
    id     = "expire-logs"
    status = "Enabled"
    filter {}
    expiration { days = 90 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "company_files" {
  bucket = aws_s3_bucket.company_files.bucket
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 365 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.bucket
  rule {
    id     = "raw-to-infrequent-access"
    status = "Enabled"
    filter { prefix = "raw/" }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    noncurrent_version_expiration { noncurrent_days = 365 }
  }
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.bucket
  rule {
    id     = "expire-old-state"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 90 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

# Every bucket's object events go to EventBridge, where the security account's rules watch them.
resource "aws_s3_bucket_notification" "app_logs" {
  bucket      = aws_s3_bucket.app_logs.bucket
  eventbridge = true
}

resource "aws_s3_bucket_notification" "company_files" {
  bucket      = aws_s3_bucket.company_files.bucket
  eventbridge = true
}

resource "aws_s3_bucket_notification" "data_lake" {
  bucket      = aws_s3_bucket.data_lake.bucket
  eventbridge = true
}

resource "aws_s3_bucket_notification" "terraform_state" {
  bucket      = aws_s3_bucket.terraform_state.bucket
  eventbridge = true
}

# Database -------------------------------------------------------------------------------------------------------

resource "aws_db_parameter_group" "postgres16" {
  name        = "demo-postgres16"
  family      = "postgres16"
  description = "customer-db: log DDL and any statement slower than a second"
  parameter {
    name  = "log_statement"
    value = "ddl"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
}

# Internal DNS and API -------------------------------------------------------------------------------------------

resource "aws_route53_zone" "internal" {
  name    = "internal.demo.test"
  comment = "Service discovery inside the VPC"
  vpc { vpc_id = aws_vpc.main.id }
}

resource "aws_route53_record" "billing_api" {
  zone_id = aws_route53_zone.internal.zone_id
  name    = "billing-api.internal.demo.test"
  type    = "CNAME"
  ttl     = 300
  records = ["d-4f2k9x7q1a.execute-api.eu-west-1.amazonaws.com"]
}

resource "aws_route53_record" "orders_api" {
  zone_id = aws_route53_zone.internal.zone_id
  name    = "orders-api.internal.demo.test"
  type    = "CNAME"
  ttl     = 300
  records = ["orders-api.demo-apps.local"]
}

resource "aws_apigatewayv2_api" "billing_internal" {
  name          = "billing-internal"
  description   = "billing-api for orders-api and support-portal; reachable only inside the VPC"
  protocol_type = "HTTP"
}
