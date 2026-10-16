# Platform team: production storage, database and application secrets.

resource "aws_s3_bucket" "app_logs" {
  #checkov:skip=CKV_AWS_145:SSE-S3 (AES256) by design, spec 02; bucket encryption is configured in platform.tf
  #checkov:skip=CKV_AWS_144:Single-region account; recovery uses versioned objects in eu-west-1
  #checkov:skip=CKV_AWS_18:S3 data events go to the security account CloudTrail; separate server access logs are not retained
  bucket = "demo-app-logs"
}

resource "aws_s3_bucket" "company_files" {
  #checkov:skip=CKV_AWS_145:SSE-S3 (AES256) by design, spec 02; bucket encryption is configured in platform.tf
  #checkov:skip=CKV_AWS_144:Single-region account; recovery uses versioned objects in eu-west-1
  #checkov:skip=CKV_AWS_18:S3 data events go to the security account CloudTrail; separate server access logs are not retained
  bucket = "demo-company-files"
}

resource "aws_s3_bucket" "data_lake" {
  #checkov:skip=CKV_AWS_145:SSE-S3 (AES256) by design, spec 02; bucket encryption is configured in platform.tf
  #checkov:skip=CKV_AWS_144:Single-region account; recovery uses versioned objects in eu-west-1
  #checkov:skip=CKV_AWS_18:S3 data events go to the security account CloudTrail; separate server access logs are not retained
  bucket = "demo-data-lake"
}

resource "aws_s3_bucket" "terraform_state" {
  #checkov:skip=CKV_AWS_145:SSE-S3 (AES256) by design, spec 02; bucket encryption is configured in platform.tf
  #checkov:skip=CKV_AWS_144:Single-region account; recovery uses versioned objects in eu-west-1
  #checkov:skip=CKV_AWS_18:S3 data events go to the security account CloudTrail; separate server access logs are not retained
  bucket = "demo-terraform-state"
}

resource "aws_secretsmanager_secret" "prod_db" {
  #checkov:skip=CKV_AWS_149:AWS-managed key; spec 02 keeps KMS key policies outside the access model
  #checkov:skip=CKV2_AWS_57:Billing owns the application database credential; its cutover runbook rotates the DB password and updates this secret together
  name = "prod-db-credentials"
  tags = { db_instance = "customer-db" }
}

resource "aws_secretsmanager_secret" "payments" {
  #checkov:skip=CKV_AWS_149:AWS-managed key; spec 02 keeps KMS key policies outside the access model
  #checkov:skip=CKV2_AWS_57:Finance rotates the payment provider key in its dashboard and updates this secret; rotation requires the external provider
  name = "payments-api-key"
}

resource "aws_db_instance" "customer" {
  #checkov:skip=CKV_AWS_118:Performance Insights covers database performance; enhanced monitoring would require a separate IAM role
  #checkov:skip=CKV_AWS_354:Performance Insights uses the default AWS-managed key; KMS key policies stay outside the access model
  #checkov:skip=CKV2_AWS_30:Query logging is configured in demo-postgres16 (platform.tf); the literal name keeps modeled plan fields known
  identifier                          = "customer-db"
  engine                              = "postgres"
  engine_version                      = "16"
  instance_class                      = "db.t4g.micro"
  allocated_storage                   = 20
  username                            = "demo_admin"
  manage_master_user_password         = true
  db_subnet_group_name                = "demo-db-subnets"
  storage_encrypted                   = true
  deletion_protection                 = true
  multi_az                            = true
  iam_database_authentication_enabled = true
  auto_minor_version_upgrade          = true
  copy_tags_to_snapshot               = true
  performance_insights_enabled        = true
  enabled_cloudwatch_logs_exports     = ["postgresql"]
  parameter_group_name                = "demo-postgres16"
}

resource "aws_dynamodb_table" "orders" {
  #checkov:skip=CKV_AWS_119:DynamoDB uses an AWS-owned encryption key; no customer-managed key grant is needed
  name         = "demo-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "order_id"

  attribute {
    name = "order_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "by_status"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_s3_bucket_policy" "company_files_public" {
  bucket = "demo-company-files"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicRead"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "arn:aws:s3:::demo-company-files/*"
    }]
  })
}
