resource "aws_sqs_queue" "dead_letters" {
  name = "${var.name}-dead-letters"

  # retain failed events for 7 days
  message_retention_seconds = 604800
}

resource "aws_sns_topic" "error_notifier" {
  name = "${var.name}-errors"
}

# todo put a lambda function between the notification and the email so it isn't just a pile of JSON
resource "aws_sns_topic_subscription" "error_notifier" {
  topic_arn = aws_sns_topic.error_notifier.arn
  protocol  = "email"
  endpoint  = var.error_notifications_email
}

resource "aws_cloudwatch_metric_alarm" "error_detection" {
  alarm_name          = "${var.name}-errors"
  alarm_description   = "Errors have occurred in email forwarder ${aws_lambda_function.function.function_name}"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  statistic           = "Sum"
  evaluation_periods  = 1
  period              = 60
  treat_missing_data  = var.missing_data_alarm_behavior
  datapoints_to_alarm = var.min_alarm_datapoints


  dimensions = {
    FunctionName = aws_lambda_function.function.function_name
  }

  actions_enabled = "true"
  alarm_actions   = [aws_sns_topic.error_notifier.arn]
}
