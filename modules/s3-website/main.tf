module "base" {
  source                    = "../../modules/s3-website-base"
  domain_name               = var.domain_name
  github_oidc_provider_arn  = var.github_oidc_provider_arn
  github_actions_repository = var.github_actions_repository
}
