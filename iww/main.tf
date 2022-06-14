# Static website for Boston IWW
module "iww_static" {
  source = "../modules/s3-website"

  zone_id     = data.aws_route53_zone.temp_steve_zone.zone_id
  domain_name = var.iww_static.main_domain
  aliases     = var.iww_static.aliases
}
