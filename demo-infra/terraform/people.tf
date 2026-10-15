resource "aws_iam_user" "priya" {
  name = "priya-intern"
}

resource "aws_iam_user" "sam" {
  name = "sam-support"
}

resource "aws_iam_user" "alex" {
  name = "alex-analyst"
}

resource "aws_iam_user" "jordan" {
  name = "jordan-platform"
}

resource "aws_iam_group" "support" {
  name = "support-engineers"
}

resource "aws_iam_group" "analysts" {
  name = "data-analysts"
}

resource "aws_iam_group" "platform" {
  name = "platform-engineers"
}

resource "aws_iam_user_group_membership" "sam_support" {
  user   = "sam-support"
  groups = ["support-engineers"]
}

resource "aws_iam_user_group_membership" "alex_analysts" {
  user   = "alex-analyst"
  groups = ["data-analysts"]
}

resource "aws_iam_user_group_membership" "jordan_platform" {
  user   = "jordan-platform"
  groups = ["platform-engineers"]
}

resource "aws_iam_group_policy" "support_assume" {
  name  = "assume-prod-support"
  group = "support-engineers"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "AssumeProdSupport"
      Effect   = "Allow"
      Action   = "sts:AssumeRole"
      Resource = "arn:aws:iam::111122223333:role/prod-support"
    }]
  })
}

resource "aws_iam_group_policy" "analysts_assume" {
  name  = "assume-analytics-read"
  group = "data-analysts"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "AssumeAnalyticsRead"
      Effect   = "Allow"
      Action   = "sts:AssumeRole"
      Resource = "arn:aws:iam::111122223333:role/analytics-read"
    }]
  })
}

resource "aws_iam_group_policy_attachment" "platform_logs" {
  group      = "platform-engineers"
  policy_arn = "arn:aws:iam::111122223333:policy/app-logs-read"
}

# Access for the support team is reviewed every quarter.
