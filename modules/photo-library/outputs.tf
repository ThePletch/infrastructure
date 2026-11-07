output "cloudfront_distribution_id" {
  value = module.website.cloudfront_distribution_id
}

output "cloudfront_distribution_arn" {
  value = module.website.cloudfront_distribution_arn
}

output "bucket_name" {
  value = module.website.bucket_name
}

output "bucket_arn" {
  value = module.website.bucket_arn
}

output "deployer_arn" {
  value = module.website.deployer_arn
}

output "deployer_name" {
  value = module.website.deployer_name
}

output "website_endpoint" {
  value = module.website.website_endpoint
}

output "bucket_hosted_zone_id" {
  description = "Hosted zone ID of the S3 website endpoint. This is not a Route 53 zone."
  value       = module.website.bucket_hosted_zone_id
}

output "photo_prefix" {
  value = local.photo_prefix
}

output "photo_index_key" {
  value = local.photo_index_key
}

output "photo_index_function_name" {
  value = module.photo_index.name
}
