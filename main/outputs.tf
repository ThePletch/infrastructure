output "site_deploy_role_arns" {
  value = merge(
    { for key, site in module.sites : key => site.deployer_arn },
    { for key, library in module.photo_libraries : key => library.deployer_arn },
  )
}

output "site_deployer_names" {
  value = merge(
    { for key, site in module.sites : key => site.deployer_name },
    { for key, library in module.photo_libraries : key => library.deployer_name },
  )
}

output "site_cloudfront_distribution_ids" {
  value = merge(
    { for key, site in module.sites : key => site.cloudfront_distribution_id },
    { for key, library in module.photo_libraries : key => library.cloudfront_distribution_id },
  )
}

output "site_cloudfront_distribution_arns" {
  value = merge(
    { for key, site in module.sites : key => site.cloudfront_distribution_arn },
    { for key, library in module.photo_libraries : key => library.cloudfront_distribution_arn },
  )
}

output "site_bucket_names" {
  value = merge(
    { for key, site in module.sites : key => site.bucket_name },
    { for key, library in module.photo_libraries : key => library.bucket_name },
  )
}

output "site_bucket_arns" {
  value = merge(
    { for key, site in module.sites : key => site.bucket_arn },
    { for key, library in module.photo_libraries : key => library.bucket_arn },
  )
}

output "site_website_endpoints" {
  value = merge(
    { for key, site in module.sites : key => site.website_endpoint },
    { for key, library in module.photo_libraries : key => library.website_endpoint },
  )
}

output "site_bucket_hosted_zone_ids" {
  description = "S3 website endpoint hosted zone IDs, keyed by site. These are not Route 53 zones."
  value = merge(
    { for key, site in module.sites : key => site.bucket_hosted_zone_id },
    { for key, library in module.photo_libraries : key => library.bucket_hosted_zone_id },
  )
}

output "photo_library_prefixes" {
  value = { for key, library in module.photo_libraries : key => library.photo_prefix }
}

output "photo_index_keys" {
  value = { for key, library in module.photo_libraries : key => library.photo_index_key }
}

output "photo_index_function_names" {
  value = { for key, library in module.photo_libraries : key => library.photo_index_function_name }
}

output "aws_region" {
  value = var.aws_region
}
