module "base" {
  source                       = "../../modules/s3-website-base"
  domain_name                  = var.domain_name
  github_oidc_provider_arn     = var.github_oidc_provider_arn
  github_actions_repository    = var.github_actions_repository
  private_prefixes             = var.signed_paths == null ? [] : var.signed_paths.private_prefixes
  cloudfront_readable_prefixes = local.signed_prefixes
  cloudfront_distribution_arn  = aws_cloudfront_distribution.website_cdn.arn
}
