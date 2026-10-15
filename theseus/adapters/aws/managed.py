"""The AWS-managed policies the demo world attaches, expanded (04-engine.md section 5).

Neither has a modeled action: they let a role write logs and pull images. Any other AWS-managed ARN is an
unknown policy, never a guess at what AWS put in it.
"""

from __future__ import annotations

from theseus.adapters.aws.iam import PolicyStatement, statements

LAMBDA_BASIC = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
ECS_TASK_EXECUTION = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"

AWS_MANAGED: dict[str, list[PolicyStatement]] = {
    LAMBDA_BASIC: statements(
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                    "Resource": "*",
                }
            ]
        }
    ),
    ECS_TASK_EXECUTION: statements(
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "ecr:GetAuthorizationToken",
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                    ],
                    "Resource": "*",
                }
            ]
        }
    ),
}
