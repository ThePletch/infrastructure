module "cert" {
  source         = "../ssl-cert"
  domain_name    = var.domain_name
  aliases        = var.aliases
  hosted_zone_id = var.zone_id
}

locals {
  cloudfront_origin = "S3-${var.domain_name}"
}

resource "aws_cloudfront_distribution" "website_cdn" {
  origin {
    domain_name = aws_s3_bucket.main.bucket_regional_domain_name
    origin_id   = local.cloudfront_origin
  }

  viewer_certificate {
    acm_certificate_arn      = module.cert.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  restrictions {
    geo_restriction {
      # i have no idea why this isn't a default, it's very silly
      # that i have to explicitly specify this
      restriction_type = "none"
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD", "OPTIONS"]
    target_origin_id       = local.cloudfront_origin
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      headers                 = []
      query_string            = false
      query_string_cache_keys = []

      cookies {
        forward           = "none"
        whitelisted_names = []
      }
    }
  }

  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = var.index_document
  aliases             = concat([var.domain_name], var.aliases)

  tags = {
    "operations-contact" = "ops@steve-pletcher.com"
  }
}
