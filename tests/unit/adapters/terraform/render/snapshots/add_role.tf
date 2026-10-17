resource "aws_iam_role" "theseus_add_role_1b064a50bd49" {
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
  name = "intern-onboarding"
}

resource "aws_iam_role_policy" "theseus_add_role_1b064a50bd49_access" {
  name = "theseus_add_role_1b064a50bd49_access"
  policy = jsonencode({
    "Statement" = [{
      "Action" = ["s3:GetObject"]
      "Effect" = "Allow"
      "Resource" = ["arn:aws:s3:::logs/*"]
      "Sid" = "ReadLogs"
    }]
    "Version" = "2012-10-17"
  })
  role = aws_iam_role.theseus_add_role_1b064a50bd49.name
}
