resource "aws_route53_zone" "main_zone" {
  name = var.base_domain
}

module "verified_domain" {
  source = "../modules/ses-verified-domain"
  domain = var.base_domain

  depends_on = [aws_route53_zone.main_zone]
}

module "email_forwarder" {
  source              = "../modules/ses-email-forwarding"
  incoming_domain     = var.base_domain
  forwarder_email     = "${var.forwarder_email}@${var.base_domain}"
  catch_all_destinations = var.forwarding_config.catch_all
  inbox_destinations = var.forwarding_config.exact_mapping
  inbox_prefix_destinations = var.forwarding_config.prefix_mapping
}
