resource "aws_iam_user_policy" "theseus_add_policy_5e5971dd539b" {
  name = "theseus_add_policy_5e5971dd539b"
  policy = jsonencode({
    "Statement" = [{
      "Action" = ["s3:GetObject"]
      "Effect" = "Allow"
      "Resource" = ["arn:aws:s3:::logs/*"]
      "Sid" = "ReadLogs"
    }]
    "Version" = "2012-10-17"
  })
  user = aws_iam_user.priya.name
}
