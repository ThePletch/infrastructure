output "website_endpoint" {
  value = aws_s3_bucket_website_configuration.main.website_endpoint
}

output "zone_id" {
  value = aws_s3_bucket.main.hosted_zone_id
}

output "deployer_arn" {
  value = aws_iam_user.deployer.arn
}
