resource "aws_iam_role" "prod_support" {
  name = "prod-support"
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

resource "aws_iam_role_policy" "prod_support_read" {
  name = "prod-support-read"
  role = "prod-support"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadLogs"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"]
      },
      {
        Sid      = "ReadInvoices"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "arn:aws:s3:::demo-company-files/invoices/*"
      },
      {
        Sid      = "ReadDbSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:eu-west-1:111122223333:secret:prod-db-credentials-*"
      }
    ]
  })
}

resource "aws_iam_role" "analytics_read" {
  name = "analytics-read"
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

resource "aws_iam_role_policy_attachment" "analytics_read_curated" {
  role       = "analytics-read"
  policy_arn = "arn:aws:iam::111122223333:policy/data-lake-curated-read"
}
