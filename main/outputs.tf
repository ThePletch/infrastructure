output "site_deploy_role_arn" {
  value = module.photo_site.deployer_arn
}

output "site_deployer_name" {
  value = module.photo_site.deployer_name
}

output "site_cloudfront_distribution_id" {
  value = module.photo_site.cloudfront_distribution_id
}

output "site_cloudfront_distribution_arn" {
  value = module.photo_site.cloudfront_distribution_arn
}

output "site_bucket_name" {
  value = module.photo_site.bucket_name
}

output "site_bucket_arn" {
  value = module.photo_site.bucket_arn
}

output "site_website_endpoint" {
  value = module.photo_site.website_endpoint
}

output "site_bucket_hosted_zone_id" {
  description = "S3 website endpoint hosted zone ID for the photos site. This is not a Route 53 zone."
  value       = module.photo_site.bucket_hosted_zone_id
}

output "photo_library_prefix" {
  value = module.photo_site.photo_prefix
}

output "photo_index_key" {
  value = module.photo_site.photo_index_key
}

output "photo_index_function_name" {
  value = module.photo_site.photo_index_function_name
}

output "aws_region" {
  value = var.aws_region
}
