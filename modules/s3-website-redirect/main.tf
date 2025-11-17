module "website" {
  source = "../s3-website-base"
  domain_name = var.from.domain
  redirect_to = var.to
}

resource "aws_route53_record" "main" {
  zone_id = var.from.zone_id
  name    = var.from.domain
  type    = "A"

  alias {
    name                   = module.website.website_endpoint
    zone_id                = module.website.zone_id
    evaluate_target_health = false
  }
}
