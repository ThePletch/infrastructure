output "deployer_arn" {
  value = module.base.deployer_arn
}

output "deployer_name" {
  value = module.base.deployer_name
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.website_cdn.id
}

output "cloudfront_distribution_arn" {
  value = aws_cloudfront_distribution.website_cdn.arn
}

output "bucket_name" {
  value = module.base.bucket_name
}

output "bucket_arn" {
  value = module.base.bucket_arn
}

output "website_endpoint" {
  value = module.base.website_endpoint
}

output "bucket_hosted_zone_id" {
  description = "Hosted zone ID of the S3 website endpoint. This is not a Route 53 zone."
  value       = module.base.zone_id
}
