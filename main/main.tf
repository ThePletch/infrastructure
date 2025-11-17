resource "aws_route53_zone" "email_zone" {
  for_each = var.forwarding_configs
  name = each.key
}

module "verified_domain" {
  source = "../modules/ses-verified-domain"
  for_each = aws_route53_zone.email_zone
  domain = each.value.name
  zone_id = aws_route53_zone.email_zone[each.key].zone_id
}

module "email_forwarder" {
  for_each = var.forwarding_configs
  source              = "../modules/ses-email-forwarding"
  incoming_domain     = each.key
  forwarder_email     = "${each.value.forwarder_email}@${each.key}"
  catch_all_destinations = each.value.catch_all
  inbox_destinations = each.value.exact_mapping
  inbox_prefix_destinations = each.value.prefix_mapping
  zone_id = aws_route53_zone.email_zone[each.key].zone_id
}
