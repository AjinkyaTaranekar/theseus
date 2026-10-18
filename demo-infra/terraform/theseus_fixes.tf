resource "aws_iam_role" "theseus_add_role_b4d9508b6d1e" {
  assume_role_policy = jsonencode({
    "Statement" = [{
      "Action" = "sts:AssumeRole"
      "Effect" = "Allow"
      "Principal" = {
        "AWS" = ["arn:aws:iam::111122223333:user/priya-intern"]
      }
    }]
    "Version" = "2012-10-17"
  })
  depends_on = [aws_iam_user.priya]
  name = "priya-logs-read"
}

resource "aws_iam_role_policy" "theseus_add_role_b4d9508b6d1e_access" {
  name = "theseus_add_role_b4d9508b6d1e_access"
  policy = jsonencode({
    "Statement" = [{
      "Action" = ["s3:GetObject", "s3:ListBucket"]
      "Effect" = "Allow"
      "Resource" = ["arn:aws:s3:::demo-app-logs", "arn:aws:s3:::demo-app-logs/*"]
      "Sid" = "ReadLogs"
    }]
    "Version" = "2012-10-17"
  })
  role = aws_iam_role.theseus_add_role_b4d9508b6d1e.name
}

resource "aws_iam_user_policy" "theseus_add_policy_680d60b0c391" {
  name = "theseus_add_policy_680d60b0c391"
  policy = jsonencode({
    "Statement" = [{
      "Action" = ["sts:AssumeRole"]
      "Effect" = "Allow"
      "Resource" = ["arn:aws:iam::111122223333:role/priya-logs-read"]
      "Sid" = "AssumeLogsRead"
    }]
    "Version" = "2012-10-17"
  })
  user = aws_iam_user.priya.name
}
