# Keep this file's unrelated text exactly.
resource "aws_iam_user" "priya" { name = "priya-intern" }
resource "aws_iam_group" "support" { name = "support-engineers" }
resource "aws_iam_group" "interns" { name = "interns" }
resource "aws_iam_user_group_membership" "priya" {
  user = "priya-intern"
  groups = ["support-engineers", "other"]
}
resource "aws_iam_role" "deploy" {
  name = "github-deploy"
  assume_role_policy = jsonencode({
    Statement = [{
      Action = "sts:AssumeRoleWithWebIdentity"
      Principal = {
        Federated = "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"
      }
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike = { "token.actions.githubusercontent.com:sub" = "repo:demo-org/*" }
      }
    }]
  })
}
resource "aws_iam_role_policy" "read" {
  role = "github-deploy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Read" Effect = "Allow" Action = "s3:GetObject" Resource = ["safe/*"] },
      { Sid = "Keep" Effect = "Allow" Action = "s3:ListBucket" Resource = "safe" }
    ]
  })
}
