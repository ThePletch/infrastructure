output "site_cloudfront_distribution_ids" {
  value = merge(
    { for key, site in module.sites : key => site.cloudfront_distribution_id },
    { for key, library in module.photo_libraries : key => library.cloudfront_distribution_id },
  )
}
