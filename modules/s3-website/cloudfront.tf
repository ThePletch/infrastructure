module "cert" {
  source          = "../ssl-cert"
  domain_name     = var.domain_name
  aliases         = var.aliases
  hosted_zone_id  = var.zone_id
}

locals {
  cloudfront_origin = "S3-${var.domain_name}"
}

resource "aws_cloudfront_distribution" "website_cdn" {
  origin {
    # We use the website endpoint instead of the bucket domain
    # to make cloudfront treat it like a website instead of a bucket.
    # This lets us do things like serve `index.html` as the default document
    # for subfolders.
    domain_name = module.base.website_endpoint
    origin_id   = local.cloudfront_origin

    custom_origin_config {
      https_port = 443
      http_port = 80
      origin_protocol_policy = "http-only"
      origin_ssl_protocols = ["SSLv3", "TLSv1", "TLSv1.1", "TLSv1.2"]
    }
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
  aliases             = concat([var.domain_name], var.aliases)

  tags = {
    "operations-contact" = var.ops_contact
  }
}
