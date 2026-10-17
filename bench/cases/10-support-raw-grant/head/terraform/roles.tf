# Platform team: support and analytics access to production data.

resource "aws_iam_role" "prod_support" {
  #checkov:skip=CKV_AWS_61:Callers need an identity-policy grant; only the support group and migration role are granted assumption
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
        Sid      = "ReadRaw"
        Effect = "Allow"
        Action = "s3:GetObject"
        Resource = "arn:aws:s3:::demo-data-lake/raw/*"
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
  #checkov:skip=CKV_AWS_61:Callers need an identity-policy grant; the data-analysts group's policy grants assumption
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
