locals {
  receipt_rule_name = "email-forward-${local.namified_domain}-s3"
}

resource "aws_ses_receipt_rule_set" "forwarding_rules" {
  rule_set_name = "email-forward-${local.namified_domain}"
}

resource "aws_ses_active_receipt_rule_set" "active" {
  rule_set_name = aws_ses_receipt_rule_set.forwarding_rules.id
}

resource "aws_ses_receipt_rule" "dump_to_s3_and_forward" {
  enabled       = true
  scan_enabled  = true
  name          = local.receipt_rule_name
  rule_set_name = aws_ses_receipt_rule_set.forwarding_rules.rule_set_name
  recipients    = [
    var.incoming_domain,
    ".${var.incoming_domain}"
  ]

  s3_action {
    bucket_name       = aws_s3_bucket.maildump.bucket
    object_key_prefix = "${var.bucket_prefix}/"
    position          = 1
  }

  lambda_action {
    function_arn    = module.forwarder.arn
    invocation_type = "Event"
    position        = 2
  }

  depends_on = [aws_s3_bucket_policy.maildump]
}

resource "aws_lambda_permission" "invoke_forwarder" {
  statement_id  = "AllowForwardingEmails"
  action        = "lambda:InvokeFunction"
  function_name = module.forwarder.name
  principal     = "ses.amazonaws.com"

  # due to order of operations, we have to construct the ARN manually here
  source_arn = join(":", [
    "arn",
    "aws",
    "ses",
    data.aws_region.current.name,
    data.aws_caller_identity.current.account_id,
    "receipt-rule-set/${aws_ses_receipt_rule_set.forwarding_rules.id}",
    "receipt-rule/${local.receipt_rule_name}",
  ])
}
