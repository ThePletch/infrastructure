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
