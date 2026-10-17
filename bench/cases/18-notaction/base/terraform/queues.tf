# Messaging between services. Owner: platform team.
#
# order-events carries `order.created` from orders-api to orders-worker. A message that fails five times moves to
# the dead-letter queue, which the on-call engineer replays by hand. Both queues use the queues KMS key in
# platform.tf. invoice-created announces each invoice billing-job issues; finance tooling subscribes to it.

resource "aws_sqs_queue" "order_events" {
  name                       = "order-events"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  kms_master_key_id          = "alias/demo-queues"
  redrive_policy = jsonencode({
    deadLetterTargetArn = "arn:aws:sqs:eu-west-1:111122223333:order-events-dlq"
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue" "order_events_dlq" {
  name                      = "order-events-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = "alias/demo-queues"
}

resource "aws_sns_topic" "invoice_created" {
  name              = "invoice-created"
  kms_master_key_id = "alias/aws/sns"
}
