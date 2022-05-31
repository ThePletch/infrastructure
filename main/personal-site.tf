module "personal_site" {
  source = "../modules/s3-website"

  zone_id     = aws_route53_zone.main_zone.zone_id
  domain_name = var.personal_site.main_domain
  aliases     = var.personal_site.aliases
}
