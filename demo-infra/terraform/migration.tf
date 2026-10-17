# Billing team: a temporary copy of customer-db for the schema v2 cutover.
#
# The cutover runbook restored a snapshot here, ran the v2 migrations against it and compared row counts
# before switching billing-api over. Remove it once the cutover is signed off. No role reads its credentials
# and no service connects to it.

resource "aws_db_instance" "orders_migration" {
  #checkov:skip=CKV_AWS_157:Temporary cutover copy; single-AZ by design, the source database stays Multi-AZ
  #checkov:skip=CKV_AWS_118:Performance Insights covers database performance; enhanced monitoring would require a separate IAM role
  #checkov:skip=CKV_AWS_354:Performance Insights uses the default AWS-managed key; KMS key policies stay outside the access model
  #checkov:skip=CKV2_AWS_30:Query logging is configured in demo-postgres16 (platform.tf); the literal name keeps modeled plan fields known
  identifier                          = "orders-migration-db"
  engine                              = "postgres"
  engine_version                      = "16"
  instance_class                      = "db.t4g.medium"
  allocated_storage                   = 100
  username                            = "demo_admin"
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
