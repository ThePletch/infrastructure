resource "aws_route53_zone" "parties_domain" {
  name = var.parties_domain
}

module "parties_domain_verification" {
  source = "../modules/ses-verified-domain"

  mail_from_subdomain = "mx"
  domain              = var.parties_domain
  dmarc = {
    rua = var.parties_dmarc_report_email
  }
  zone_id = aws_route53_zone.parties_domain.zone_id
}
