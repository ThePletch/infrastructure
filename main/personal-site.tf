module "new_personal_site" {
  source = "../modules/s3-website"

  zone_id = aws_route53_zone.email_zone[var.personal_site.main_domain].zone_id
  domain_name = var.personal_site.main_domain
  aliases     = var.personal_site.aliases
  redirects   = var.personal_site.redirects
  ops_contact = var.personal_site.contact_email
}
