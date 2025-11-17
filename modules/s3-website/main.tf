module "base" {
  source = "../../modules/s3-website-base"
  domain_name = var.domain_name
}
