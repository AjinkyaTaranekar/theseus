resource "aws_s3_bucket" "app_logs" {
  bucket = "demo-app-logs"
}

resource "aws_s3_bucket" "company_files" {
  bucket = "demo-company-files"
}

resource "aws_s3_bucket" "data_lake" {
  bucket = "demo-data-lake"
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = "demo-terraform-state"
}

resource "aws_secretsmanager_secret" "prod_db" {
  name = "prod-db-credentials"
  tags = { db_instance = "customer-db" }
}

resource "aws_secretsmanager_secret" "payments" {
  name = "payments-api-key"
}

resource "aws_db_instance" "customer" {
  identifier                  = "customer-db"
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  username                    = "demo_admin"
  manage_master_user_password = true
  db_subnet_group_name        = "demo-db-subnets"
  storage_encrypted           = true
}

resource "aws_dynamodb_table" "orders" {
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
