module "cert" {
  source         = "../ssl-cert"
  domain_name    = var.domain_name
  aliases        = var.aliases
  hosted_zone_id = var.zone_id
}

locals {
  cloudfront_origin = "S3-${var.domain_name}"
  function_url_origins = {
    for origin in var.function_url_origins : origin.origin_id => origin
  }
  ordered_cache_behaviors = {
    for index, behavior in var.ordered_cache_behaviors :
    format("%03d", index) => behavior
  }
  private_origin   = "S3-private-${var.domain_name}"
  private_prefixes = var.private_paths == null ? [] : var.private_paths.prefixes
}

resource "aws_cloudfront_origin_access_control" "private" {
  count                             = var.private_paths == null ? 0 : 1
  name                              = "${replace(var.domain_name, ".", "-")}-s3"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

moved {
  from = aws_cloudfront_origin_access_control.signed[0]
  to   = aws_cloudfront_origin_access_control.private[0]
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

resource "aws_cloudfront_distribution" "website_cdn" {
  # Callers pass wait_for so this distribution is not updated before a
  # dependency such as a Lambda@Edge invoke permission exists.
  lifecycle {
    precondition {
      condition     = var.wait_for != null
      error_message = "wait_for cannot be null."
    }
  }

  origin {
    # We use the website endpoint instead of the bucket domain
    # to make cloudfront treat it like a website instead of a bucket.
    # This lets us do things like serve `index.html` as the default document
    # for subfolders.
    domain_name = module.base.website_endpoint
    origin_id   = local.cloudfront_origin

    custom_origin_config {
      https_port             = 443
      http_port              = 80
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["SSLv3", "TLSv1", "TLSv1.1", "TLSv1.2"]
    }
  }

  dynamic "origin" {
    for_each = local.function_url_origins
    content {
      domain_name              = origin.value.domain_name
      origin_id                = origin.value.origin_id
      origin_access_control_id = origin.value.origin_access_control_id

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  # The website endpoint above can't authenticate to S3, so private paths
  # are read from the REST endpoint through Origin Access Control instead.
  dynamic "origin" {
    for_each = aws_cloudfront_origin_access_control.private
    content {
      domain_name              = module.base.bucket_regional_domain_name
      origin_id                = local.private_origin
      origin_access_control_id = origin.value.id
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

  dynamic "ordered_cache_behavior" {
    for_each = local.ordered_cache_behaviors
    content {
      path_pattern             = ordered_cache_behavior.value.path_pattern
      allowed_methods          = ordered_cache_behavior.value.allowed_methods
      cached_methods           = ordered_cache_behavior.value.cached_methods
      target_origin_id         = ordered_cache_behavior.value.target_origin_id
      viewer_protocol_policy   = "redirect-to-https"
      cache_policy_id          = ordered_cache_behavior.value.cache_policy_id
      origin_request_policy_id = ordered_cache_behavior.value.origin_request_policy_id
      compress                 = ordered_cache_behavior.value.compress

      dynamic "lambda_function_association" {
        for_each = ordered_cache_behavior.value.lambda_function_associations
        content {
          event_type   = lambda_function_association.value.event_type
          lambda_arn   = lambda_function_association.value.lambda_arn
          include_body = lambda_function_association.value.include_body
        }
      }
    }
  }

  # These prefixes stay off the public website endpoint. The bucket policy
  # allows this distribution to read them and denies it everything else
  # under the private prefixes.
  dynamic "ordered_cache_behavior" {
    for_each = local.private_prefixes
    content {
      path_pattern           = "/${ordered_cache_behavior.value}*"
      allowed_methods        = ["GET", "HEAD"]
      cached_methods         = ["GET", "HEAD"]
      target_origin_id       = local.private_origin
      viewer_protocol_policy = "redirect-to-https"
      cache_policy_id        = data.aws_cloudfront_cache_policy.caching_optimized.id
      compress               = true
    }
  }

  enabled         = true
  is_ipv6_enabled = true
  aliases         = concat([var.domain_name], var.aliases)

  tags = {
    "operations-contact" = var.ops_contact
  }
}

resource "aws_lambda_permission" "function_url_origin" {
  for_each               = local.function_url_origins
  statement_id           = "AllowCloudFrontInvokeUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = each.value.function_name
  principal              = "cloudfront.amazonaws.com"
  source_arn             = aws_cloudfront_distribution.website_cdn.arn
  function_url_auth_type = "AWS_IAM"
}

resource "aws_lambda_permission" "function_url_invoke" {
  for_each      = local.function_url_origins
  statement_id  = "AllowCloudFrontInvokeFunction"
  action        = "lambda:InvokeFunction"
  function_name = each.value.function_name
  principal     = "cloudfront.amazonaws.com"
  source_arn    = aws_cloudfront_distribution.website_cdn.arn

  depends_on = [aws_lambda_permission.function_url_origin]
}
