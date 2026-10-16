# Orders team: API and worker tasks on the shared application cluster.

resource "aws_ecs_cluster" "apps" {
  name = "demo-apps"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "ecs-task-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = "ecs-task-execution"
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "orders_api_task" {
  name = "orders-api-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "orders_api_table" {
  role       = "orders-api-task"
  policy_arn = "arn:aws:iam::111122223333:policy/orders-table-rw"
}

# The worker fulfils orders from this queue; the queue key's policy (platform.tf) lets this role encrypt for it.
resource "aws_iam_role_policy" "orders_api_events" {
  name = "orders-api-events"
  role = "orders-api-task"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "SendOrderEvents"
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = "arn:aws:sqs:eu-west-1:111122223333:order-events"
    }]
  })
}

resource "aws_iam_role" "orders_worker_task" {
  name = "orders-worker-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "orders_worker_table" {
  role       = "orders-worker-task"
  policy_arn = "arn:aws:iam::111122223333:policy/orders-table-rw"
}

# Long-polls the queue and deletes each message once its order is fulfilled; failures go to the DLQ by redrive.
resource "aws_iam_role_policy" "orders_worker_events" {
  name = "orders-worker-events"
  role = "orders-worker-task"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ConsumeOrderEvents"
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage"]
      Resource = "arn:aws:sqs:eu-west-1:111122223333:order-events"
    }]
  })
}

resource "aws_ecs_task_definition" "orders_api" {
  family                   = "orders-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  task_role_arn            = "arn:aws:iam::111122223333:role/orders-api-task"
  execution_role_arn       = "arn:aws:iam::111122223333:role/ecs-task-execution"
  container_definitions = jsonencode([{
    name                   = "orders-api"
    image                  = "111122223333.dkr.ecr.eu-west-1.amazonaws.com/orders-api:2.3.1"
    essential              = true
    readonlyRootFilesystem = true
    environment = [
      { name = "BILLING_API_URL", value = "https://billing-api.internal.demo.test" },
      { name = "ORDERS_TABLE", value = "demo-orders" },
      { name = "ORDER_EVENTS_QUEUE_URL", value = "https://sqs.eu-west-1.amazonaws.com/111122223333/order-events" }
    ]
  }])
}

resource "aws_ecs_task_definition" "orders_worker" {
  family                   = "orders-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  task_role_arn            = "arn:aws:iam::111122223333:role/orders-worker-task"
  execution_role_arn       = "arn:aws:iam::111122223333:role/ecs-task-execution"
  container_definitions = jsonencode([{
    name                   = "orders-worker"
    image                  = "111122223333.dkr.ecr.eu-west-1.amazonaws.com/orders-worker:2.3.1"
    essential              = true
    readonlyRootFilesystem = true
    environment = [
      { name = "ORDERS_TABLE", value = "demo-orders" },
      { name = "ORDER_EVENTS_QUEUE_URL", value = "https://sqs.eu-west-1.amazonaws.com/111122223333/order-events" }
    ]
  }])
}

resource "aws_ecs_service" "orders_api" {
  name            = "orders-api"
  cluster         = "arn:aws:ecs:eu-west-1:111122223333:cluster/demo-apps"
  task_definition = "orders-api"
  launch_type     = "FARGATE"
  desired_count   = 2

  network_configuration {
    subnets = ["subnet-0a1b2c3d4e5f60001", "subnet-0a1b2c3d4e5f60002"]
  }

  tags = { theseus_code_path = "services/orders_api" }
}

resource "aws_ecs_service" "orders_worker" {
  name            = "orders-worker"
  cluster         = "arn:aws:ecs:eu-west-1:111122223333:cluster/demo-apps"
  task_definition = "orders-worker"
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets = ["subnet-0a1b2c3d4e5f60001", "subnet-0a1b2c3d4e5f60002"]
  }

  tags = { theseus_code_path = "services/orders_worker" }
}
