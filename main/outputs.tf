output "site_deploy_role_arns" {
  value = merge(
    { for key, site in module.sites : key => site.deployer_arn },
    { for key, library in module.photo_libraries : key => library.deployer_arn },
  )
}

output "site_cloudfront_distribution_ids" {
  value = merge(
    { for key, site in module.sites : key => site.cloudfront_distribution_id },
    { for key, library in module.photo_libraries : key => library.cloudfront_distribution_id },
  )
}
