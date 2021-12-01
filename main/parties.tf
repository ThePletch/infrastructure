resource "aws_route53_zone" "parties_domain" {
  name = var.parties_domain
}

module "parties_domain_verification" {
  source = "../modules/ses-verified-domain"

  domain = var.parties_domain

  depends_on = [aws_route53_zone.parties_domain]
}
