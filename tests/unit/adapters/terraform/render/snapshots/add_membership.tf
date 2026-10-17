resource "aws_iam_user_group_membership" "theseus_add_membership_833ff9805d08" {
  groups = [aws_iam_group.interns.name]
  user = aws_iam_user.priya.name
}
