module "verified_domain" {
  source   = "../modules/ses-verified-domain"
  for_each = aws_route53_zone.email_zone

  mail_from_subdomain = var.mxroute.domains[each.key].mail_from_subdomain
  dmarc = {
    rua = var.mxroute.domains[each.key].dmarc_email
  }
  domain  = each.value.name
  zone_id = aws_route53_zone.email_zone[each.key].zone_id
}
