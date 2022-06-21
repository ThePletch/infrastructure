locals {
  maildump_bucket_name = "${var.incoming_domain}-maildump"
  namified_domain      = replace(var.incoming_domain, "/\\./", "-")
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_route53_zone" "target_domain" {
  name = var.incoming_domain
}

resource "aws_route53_record" "incoming_smtp" {
  zone_id = data.aws_route53_zone.target_domain.zone_id
  name    = var.incoming_domain
  type    = "MX"
  records = [
    "10 inbound-smtp.${data.aws_region.current.name}.amazonaws.com"
  ]
  ttl = "300"
}

resource "aws_s3_bucket" "maildump" {
  bucket = "${local.namified_domain}-maildump"
}

resource "aws_s3_bucket_policy" "maildump" {
  bucket = aws_s3_bucket.maildump.id

  policy = data.aws_iam_policy_document.maildump_bucket_policy.json
}

module "forwarder" {
  source                      = "../lambda-function"
  name                        = "email-forwarder-${local.namified_domain}"
  source_code_file            = "${path.module}/lambda/forward_emails.py"
  function_runtime            = "python3.9"
  include_inline_policy       = true
  publish                     = true
  error_notifications_email   = var.catch_all_destinations[0]
  iam_policy                  = data.aws_iam_policy_document.email_sender.json
  missing_data_alarm_behavior = "notBreaching"

  environment_config = {
    ForwardingConfigPrefix = local.parameter_path_prefix
    MailS3Bucket  = aws_s3_bucket.maildump.bucket
    MailS3Prefix  = var.bucket_prefix
    MailSender    = var.forwarder_email
    Region        = data.aws_region.current.name
  }

  memory_mb = 512
  timeout   = 30
}
