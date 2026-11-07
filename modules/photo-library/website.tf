module "website" {
  source      = "../s3-website"
  domain_name = var.domain_name
  aliases     = var.aliases
  redirects   = var.redirects
  zone_id     = var.zone_id
  ops_contact = var.ops_contact

  function_url_origins = [
    {
      origin_id                = local.manifest_origin
      domain_name              = local.manifest_origin_domain
      origin_access_control_id = aws_cloudfront_origin_access_control.photo_manifest.id
      function_name            = module.photo_manifest.name
    },
    {
      origin_id                = local.shop_origin
      domain_name              = local.shop_origin_domain
      origin_access_control_id = aws_cloudfront_origin_access_control.photo_shop.id
      function_name            = module.photo_shop.name
    },
  ]

  ordered_cache_behaviors = concat(
    [
      {
        path_pattern             = "/api/photos"
        target_origin_id         = local.manifest_origin
        allowed_methods          = ["GET", "HEAD", "OPTIONS"]
        cached_methods           = ["GET", "HEAD", "OPTIONS"]
        cache_policy_id          = aws_cloudfront_cache_policy.photo_manifest.id
        origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
        compress                 = true
      },
    ],
    [
      for path in ["/api/checkout", "/api/webhooks/stripe"] : {
        path_pattern             = path
        target_origin_id         = local.shop_origin
        allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
        cached_methods           = ["GET", "HEAD"]
        cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
        origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
        compress                 = true
      }
    ],
  )
}
