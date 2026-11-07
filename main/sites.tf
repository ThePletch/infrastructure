locals {
  site_domains = {
    for key, site in var.sites :
    key => join(".", compact([site.main_subdomain, site.base_domain]))
  }
}

module "sites" {
  for_each = var.sites
  source   = "../modules/s3-website"

  zone_id                   = aws_route53_zone.email_zone[each.value.base_domain].zone_id
  domain_name               = local.site_domains[each.key]
  aliases                   = each.value.aliases
  redirects                 = each.value.redirects
  ops_contact               = each.value.contact_email
  github_oidc_provider_arn  = aws_iam_openid_connect_provider.github.arn
  github_actions_repository = var.github_actions_repository
}

module "photo_site" {
  source = "../modules/photo-library"

  zone_id                   = aws_route53_zone.email_zone[var.photo_site.base_domain].zone_id
  domain_name               = join(".", [var.photo_site.subdomain, var.photo_site.base_domain])
  ops_contact               = var.photo_site.contact_email
  github_oidc_provider_arn  = aws_iam_openid_connect_provider.github.arn
  github_actions_repository = var.github_actions_repository
  photo_prefix              = var.photo_site.photo_prefix
  printful_api_key          = var.printful_api_key
  stripe                    = var.stripe
}

moved {
  from = module.photo_libraries["photos"]
  to   = module.photo_site
}

# moved {
#   from = module.photo_library
#   to = module.photo_site
# }