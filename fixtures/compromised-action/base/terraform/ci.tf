resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_deploy" {
  name = "github-deploy"
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
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:demo-org/*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "github-deploy"
  role = "github-deploy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PublishSite"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "arn:aws:s3:::demo-company-files/public/*"
      },
      {
        Sid      = "AssumeProdSupportForMigrations"
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = "arn:aws:iam::111122223333:role/prod-support"
      }
    ]
  })
}

resource "aws_iam_role" "terraform_apply" {
  name = "terraform-apply"
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
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:demo-org/infra:environment:production"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "terraform_apply" {
  name = "terraform-apply"
  role = "terraform-apply"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "TerraformState"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::demo-terraform-state/*", "arn:aws:s3:::demo-terraform-state"]
      },
      {
        Sid    = "ApplyInfra"
        Effect = "Allow"
        Action = [
          "iam:*", "lambda:*", "ecs:*", "ec2:*", "rds:*", "sqs:*", "sns:*", "kms:*",
          "logs:*", "events:*", "ecr:*", "route53:*", "apigateway:*",
          "dynamodb:CreateTable", "dynamodb:Describe*", "dynamodb:UpdateTable", "dynamodb:TagResource",
          "s3:CreateBucket", "s3:GetBucket*", "s3:PutBucket*",
          "secretsmanager:CreateSecret", "secretsmanager:DescribeSecret", "secretsmanager:TagResource"
        ]
        Resource = "*"
      }
    ]
  })
}
