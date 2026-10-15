resource "aws_iam_role" "billing_job" {
  name = "billing-job"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "billing_job_logs" {
  role       = "billing-job"
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "billing_job" {
  name = "billing-job"
  role = "billing-job"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteInvoices"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "arn:aws:s3:::demo-company-files/invoices/*"
      },
      {
        Sid      = "ReadPaymentsKey"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:payments-api-key-*"
      },
      {
        Sid    = "ReadOrders"
        Effect = "Allow"
        Action = "dynamodb:Query"
        Resource = [
          "arn:aws:dynamodb:eu-west-1:111122223333:table/demo-orders",
          "arn:aws:dynamodb:eu-west-1:111122223333:table/demo-orders/index/*"
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "billing_job" {
  function_name = "billing-job"
  role          = "arn:aws:iam::111122223333:role/billing-job"
  runtime       = "python3.12"
  handler       = "handler.handler"
  s3_bucket     = "demo-artifacts"
  s3_key        = "billing-job/2.3.1.zip"

  environment {
    variables = {
      INVOICES_BUCKET   = "demo-company-files"
      ORDERS_TABLE      = "demo-orders"
      PAYMENTS_SECRET   = "payments-api-key"
      INVOICE_TOPIC_ARN = "arn:aws:sns:eu-west-1:111122223333:invoice-created"
    }
  }

  tags = { theseus_code_path = "services/billing_job" }
}

resource "aws_iam_role" "billing_api" {
  name = "billing-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "billing_api_logs" {
  role       = "billing-api"
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "billing_api" {
  name = "billing-api"
  role = "billing-api"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadDbSecret"
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod-db-credentials-*"
    }]
  })
}

resource "aws_lambda_function" "billing_api" {
  function_name = "billing-api"
  role          = "arn:aws:iam::111122223333:role/billing-api"
  runtime       = "python3.12"
  handler       = "handler.handler"
  s3_bucket     = "demo-artifacts"
  s3_key        = "billing-api/2.3.1.zip"

  environment {
    variables = {
      DB_SECRET = "prod-db-credentials"
      DB_NAME   = "customers"
    }
  }

  tags = { theseus_code_path = "services/billing_api" }
}

resource "aws_iam_role" "support_portal" {
  name = "support-portal"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "support_portal_logs" {
  role       = "support-portal"
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "support_portal" {
  name = "support-portal"
  role = "support-portal"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "LegacyDbSecret"
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod-db-credentials-*"
    }]
  })
}

resource "aws_lambda_function" "support_portal" {
  function_name = "support-portal"
  role          = "arn:aws:iam::111122223333:role/support-portal"
  runtime       = "python3.12"
  handler       = "handler.handler"
  s3_bucket     = "demo-artifacts"
  s3_key        = "support-portal/2.3.1.zip"

  environment {
    variables = {
      BILLING_API_URL = "https://billing-api.internal.demo.test"
      ORDERS_API_URL  = "https://orders-api.internal.demo.test"
    }
  }

  tags = { theseus_code_path = "services/support_portal" }
}

resource "aws_iam_role" "analytics_export" {
  name = "analytics-export"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "analytics_export_logs" {
  role       = "analytics-export"
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "analytics_export" {
  name = "analytics-export"
  role = "analytics-export"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadOrders"
        Effect   = "Allow"
        Action   = "dynamodb:Scan"
        Resource = "arn:aws:dynamodb:eu-west-1:111122223333:table/demo-orders"
      },
      {
        Sid      = "RawZone"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "arn:aws:s3:::demo-data-lake/raw/*"
      },
      {
        Sid      = "CuratedZone"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "arn:aws:s3:::demo-data-lake/curated/*"
      }
    ]
  })
}

resource "aws_lambda_function" "analytics_export" {
  function_name = "analytics-export"
  role          = "arn:aws:iam::111122223333:role/analytics-export"
  runtime       = "python3.12"
  handler       = "handler.handler"
  s3_bucket     = "demo-artifacts"
  s3_key        = "analytics-export/2.3.1.zip"

  environment {
    variables = {
      ORDERS_TABLE = "demo-orders"
      LAKE_BUCKET  = "demo-data-lake"
    }
  }

  tags = { theseus_code_path = "services/analytics_export" }
}
