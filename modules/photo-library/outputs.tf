output "cloudfront_distribution_id" {
  value = module.website.cloudfront_distribution_id
}

output "bucket_name" {
  value = module.website.bucket_name
}

output "deployer_arn" {
  value = module.website.deployer_arn
}