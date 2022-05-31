resource "aws_route53_record" "website" {
  zone_id = var.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.website_cdn.domain_name
    zone_id                = aws_cloudfront_distribution.website_cdn.hosted_zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "website_aliases" {
  for_each = toset(var.aliases)
  zone_id  = var.zone_id
  name     = each.value
  type     = "A"

  alias {
    name                   = aws_route53_record.website.name
    zone_id                = aws_route53_record.website.zone_id
    evaluate_target_health = true
  }
}
