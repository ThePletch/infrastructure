locals {
  site_domains = {
    for key, site in var.sites :
    key => join(".", compact([site.main_subdomain, site.base_domain]))
  }

  static_sites = {
    for key, site in var.sites : key => site
    if site.photo_prefix == ""
  }

  photo_sites = {
    for key, site in var.sites : key => site
    if site.photo_prefix != ""
  }
}

module "sites" {
  for_each = local.static_sites
  source   = "../modules/s3-website"

  zone_id                   = aws_route53_zone.email_zone[each.value.base_domain].zone_id
  domain_name               = local.site_domains[each.key]
  aliases                   = each.value.aliases
  redirects                 = each.value.redirects
  ops_contact               = each.value.contact_email
  github_oidc_provider_arn  = aws_iam_openid_connect_provider.github.arn
  github_actions_repository = var.github_actions_repository
}

moved {
  from = module.sites["photos"]
  to   = module.photo_libraries["photos"].module.website
}

module "photo_libraries" {
  for_each = local.photo_sites
  source   = "../modules/photo-library"

  zone_id                   = aws_route53_zone.email_zone[each.value.base_domain].zone_id
  domain_name               = local.site_domains[each.key]
  aliases                   = each.value.aliases
  redirects                 = each.value.redirects
  ops_contact               = each.value.contact_email
  github_oidc_provider_arn  = aws_iam_openid_connect_provider.github.arn
  github_actions_repository = var.github_actions_repository
  photo_prefix              = each.value.photo_prefix
  printful_api_key          = var.printful_api_key
  stripe                    = var.stripe
}
