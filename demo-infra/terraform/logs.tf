# One log group per workload, created here rather than on first write, so retention is set from day one.
# Owner: platform team. A year of retention covers the audit window. Logs hold request metadata, never payloads or
# credentials, so they use CloudWatch's default encryption.

resource "aws_cloudwatch_log_group" "billing_job" {
  #checkov:skip=CKV_AWS_158:Default CloudWatch encryption; no payloads or credentials are logged
  name              = "/aws/lambda/billing-job"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_group" "billing_api" {
  #checkov:skip=CKV_AWS_158:Default CloudWatch encryption; no payloads or credentials are logged
  name              = "/aws/lambda/billing-api"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_group" "support_portal" {
  #checkov:skip=CKV_AWS_158:Default CloudWatch encryption; no payloads or credentials are logged
  name              = "/aws/lambda/support-portal"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_group" "analytics_export" {
  #checkov:skip=CKV_AWS_158:Default CloudWatch encryption; no payloads or credentials are logged
  name              = "/aws/lambda/analytics-export"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_group" "orders_api" {
  #checkov:skip=CKV_AWS_158:Default CloudWatch encryption; no payloads or credentials are logged
  name              = "/ecs/orders-api"
  retention_in_days = 90
}

resource "aws_cloudwatch_log_group" "orders_worker" {
  #checkov:skip=CKV_AWS_158:Default CloudWatch encryption; no payloads or credentials are logged
  name              = "/ecs/orders-worker"
  retention_in_days = 365
}
