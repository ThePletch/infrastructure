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
  forwarder_email     = "${var.personal_email}@${var.base_domain}"
  forward_destination = var.destination_email
  email_addresses_to_intercept = [
    var.personal_email,
    var.robots_email,
  ]
}
