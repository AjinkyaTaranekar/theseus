# Platform team: shared data grants attached to team and workload identities.

resource "aws_iam_policy" "app_logs_read" {
  name = "app-logs-read"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadAppLogs"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = ["arn:aws:s3:::demo-app-logs/*", "arn:aws:s3:::demo-app-logs"]
    }]
  })
}

resource "aws_iam_policy" "data_lake_curated_read" {
  name = "data-lake-curated-read"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadCurated"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["arn:aws:s3:::demo-data-lake/curated/*"]
    }]
  })
}

resource "aws_iam_policy" "orders_table_rw" {
  name = "orders-table-rw"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "OrdersTableReadWrite"
      Effect = "Allow"
      Action = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"]
      Resource = [
        "arn:aws:dynamodb:eu-west-1:111122223333:table/demo-orders",
        "arn:aws:dynamodb:eu-west-1:111122223333:table/demo-orders/index/*"
      ]
    }]
  })
}
