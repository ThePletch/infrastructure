locals {
  parameter_path_prefix = "/email-forwarding/${var.incoming_domain}"
}

resource "aws_ssm_parameter" "catch_all" {
  name = "${local.parameter_path_prefix}/catch-all"
  type = "StringList"
  value = join(",", var.catch_all_destinations)
}

resource "aws_ssm_parameter" "explicit_matchers" {
  for_each = var.inbox_destinations

  name = "${local.parameter_path_prefix}/inboxes/${each.key}"
  type = "StringList"
  value = join(",", each.value)
}

resource "aws_ssm_parameter" "prefixes" {
  for_each = var.inbox_prefix_destinations

  name = "${local.parameter_path_prefix}/inbox-prefixes/${each.key}"
  type = "StringList"
  value = join(",", each.value)
}
