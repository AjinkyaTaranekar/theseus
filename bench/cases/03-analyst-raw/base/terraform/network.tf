# The production VPC. Owner: platform team.
#
# Two private subnets hold the ECS tasks, the Lambdas that reach the database, and the database itself. The public
# subnets route to the internet gateway and are kept for the edge. S3 traffic stays on the gateway endpoint. Flow
# logs for every VPC are collected centrally by the security account (an organization-wide setting).

resource "aws_vpc" "main" {
  #checkov:skip=CKV2_AWS_11:Flow logs are enabled organization-wide and delivered to the security account
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "demo-main" }
}

# Nothing may use the default security group.
resource "aws_default_security_group" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.0.0/20"
  availability_zone = "eu-west-1a"
  tags              = { Name = "demo-private-a", Tier = "private" }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.16.0/20"
  availability_zone = "eu-west-1b"
  tags              = { Name = "demo-private-b", Tier = "private" }
}

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.128.0/20"
  availability_zone       = "eu-west-1a"
  map_public_ip_on_launch = false
  tags                    = { Name = "demo-public-a", Tier = "public" }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.144.0/20"
  availability_zone       = "eu-west-1b"
  map_public_ip_on_launch = false
  tags                    = { Name = "demo-public-b", Tier = "public" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "demo-main" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "demo-public" }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "app" {
  #checkov:skip=CKV2_AWS_5:Attached to the ECS services and Lambdas, which name it by ID
  name        = "demo-app"
  description = "Application tasks and functions"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_egress_rule" "app_https" {
  security_group_id = aws_security_group.app.id
  description       = "HTTPS to AWS APIs and the payment provider"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_security_group" "db" {
  #checkov:skip=CKV2_AWS_5:Attached to customer-db, which names it by ID
  name        = "demo-db"
  description = "The customer database"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "Postgres from the application tier only"
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_subnet_group" "main" {
  name        = "demo-db-subnets"
  description = "Private subnets for the customer database"
  subnet_ids  = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.eu-west-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id]
}
