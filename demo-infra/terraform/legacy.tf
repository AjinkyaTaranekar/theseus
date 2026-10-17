# Platform team: access and resources from before the IAM review, still waiting on their owners.

# A contractor for the payments migration, and the break-glass role the group was given "for the cutover".
resource "aws_iam_user" "casey" {
  #checkov:skip=CKV_AWS_273:Contractors get IAM users until the identity provider onboards external accounts
  name = "casey-contractor"
}

resource "aws_iam_group" "contractors" {
  name = "contractors"
}


resource "aws_iam_group_policy" "contractors_assume" {
  name  = "assume-platform-admin"
  group = "contractors"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "AssumePlatformAdmin"
      Effect   = "Allow"
      Action   = "sts:AssumeRole"
      Resource = "arn:aws:iam::111122223333:role/platform-admin"
    }]
  })
}

resource "aws_iam_role" "platform_admin" {
  #checkov:skip=CKV_AWS_61:Callers need an identity-policy grant; break-glass access is granted per group
  name = "platform-admin"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TrustAccountPrincipals"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::111122223333:root" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "platform_admin" {
  #checkov:skip=CKV_AWS_355:Break-glass role; scoped down after the payments cutover
  name = "platform-admin-break-glass"
  role = "platform-admin"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadAllSecrets"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:*"
      },
      {
        Sid      = "ReadCompanyFiles"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:aws:s3:::demo-company-files/*"
      }
    ]
  })
}

# Snapshots: any workflow in the infra repo can take this role, and it reads every secret.
resource "aws_iam_role" "backup_runner" {
  name = "backup-runner"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "GitHubActionsOIDC"
      Effect = "Allow"
      Principal = {
        Federated = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:demo-org/infra:*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "backup_runner" {
  #checkov:skip=CKV_AWS_355:The backup job copies every secret into the vault; per-secret grants are on the backlog
  name = "backup-runner"
  role = "backup-runner"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "BackupSecrets"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:*"
      },
      {
        Sid      = "BackupCompanyFiles"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::demo-company-files", "arn:aws:s3:::demo-company-files/*"]
      }
    ]
  })
}

# Notifications: two functions share one role, copied from billing-job's, with a payments grant neither uses.
resource "aws_iam_role" "shared_lambda" {
  name = "shared-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "shared_lambda" {
  name = "shared-lambda"
  role = "shared-lambda"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadSmtpSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:smtp-credentials-*"
      },
      {
        Sid      = "ReadInvoices"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:aws:s3:::demo-company-files/invoices/*"
      },
      {
        Sid      = "ReadPaymentsKey"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:payments-api-key-*"
      }
    ]
  })
}

resource "aws_secretsmanager_secret" "smtp" {
  #checkov:skip=CKV_AWS_149:AWS-managed key; spec 02 keeps KMS key policies outside the access model
  #checkov:skip=CKV2_AWS_57:The mail provider rotates SMTP credentials; the secret is updated by hand after each rotation
  name = "smtp-credentials"
}

resource "aws_lambda_function" "invoice_mailer" {
  #checkov:skip=CKV_AWS_116:Mail sends are retried by the provider; a DLQ is deferred
  #checkov:skip=CKV_AWS_173:Environment holds resource names only; secret values are fetched from Secrets Manager
  #checkov:skip=CKV_AWS_272:Artifacts are built and signed in CI; deployment validates them before publication
  function_name = "invoice-mailer"
  role          = "arn:aws:iam::111122223333:role/shared-lambda"
  runtime       = "python3.12"
  handler       = "handler.handler"
  s3_bucket     = "demo-artifacts"
  s3_key        = "invoice-mailer/1.4.0.zip"

  reserved_concurrent_executions = 5

  tracing_config {
    mode = "Active"
  }

  vpc_config {
    subnet_ids         = ["subnet-0a1b2c3d4e5f60001", "subnet-0a1b2c3d4e5f60002"]
    security_group_ids = ["sg-0a1b2c3d4e5f60001"]
  }

  environment {
    variables = {
      INVOICES_BUCKET = "demo-company-files"
      SMTP_SECRET     = "smtp-credentials"
    }
  }

  tags = { theseus_code_path = "services/invoice_mailer" }
}

resource "aws_lambda_function" "receipt_renderer" {
  #checkov:skip=CKV_AWS_116:Receipts are rendered again on the next request; a DLQ is deferred
  #checkov:skip=CKV_AWS_173:Environment holds resource names only; secret values are fetched from Secrets Manager
  #checkov:skip=CKV_AWS_272:Artifacts are built and signed in CI; deployment validates them before publication
  function_name = "receipt-renderer"
  role          = "arn:aws:iam::111122223333:role/shared-lambda"
  runtime       = "python3.12"
  handler       = "handler.handler"
  s3_bucket     = "demo-artifacts"
  s3_key        = "receipt-renderer/0.9.2.zip"

  reserved_concurrent_executions = 5

  tracing_config {
    mode = "Active"
  }

  vpc_config {
    subnet_ids         = ["subnet-0a1b2c3d4e5f60001", "subnet-0a1b2c3d4e5f60002"]
    security_group_ids = ["sg-0a1b2c3d4e5f60001"]
  }

  environment {
    variables = {
      INVOICES_BUCKET = "demo-company-files"
      SMTP_SECRET     = "smtp-credentials"
    }
  }

  tags = { theseus_code_path = "services/receipt_renderer" }
}

# Left over from the reporting migration: nothing reads this replica or its old password any more.
resource "aws_db_instance" "reports_replica" {
  #checkov:skip=CKV_AWS_118:Decommission pending; monitoring was turned off with the reporting cutover
  #checkov:skip=CKV_AWS_354:Performance Insights uses the default AWS-managed key; KMS key policies stay outside the access model
  #checkov:skip=CKV2_AWS_30:Query logging is configured in demo-postgres16 (platform.tf); the literal name keeps modeled plan fields known
  #checkov:skip=CKV_AWS_157:Decommission pending; the replica was single-AZ by design
  identifier                          = "reports-replica"
  engine                              = "postgres"
  engine_version                      = "16"
  instance_class                      = "db.t4g.medium"
  allocated_storage                   = 100
  username                            = "reports_admin"
  manage_master_user_password         = true
  db_subnet_group_name                = "demo-db-subnets"
  storage_encrypted                   = true
  deletion_protection                 = true
  multi_az                            = false
  iam_database_authentication_enabled = true
  auto_minor_version_upgrade          = true
  copy_tags_to_snapshot               = true
  performance_insights_enabled        = true
  enabled_cloudwatch_logs_exports     = ["postgresql"]
  parameter_group_name                = "demo-postgres16"
}

resource "aws_secretsmanager_secret" "legacy_reports" {
  #checkov:skip=CKV_AWS_149:AWS-managed key; spec 02 keeps KMS key policies outside the access model
  #checkov:skip=CKV2_AWS_57:Decommission pending with the reports replica
  name = "legacy-reports-password"
}
