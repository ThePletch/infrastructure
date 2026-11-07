provider "aws" {
  region  = var.aws_region
  profile = var.aws_credentials_profile
}

provider "mxroute" {
  server = var.mxroute.server
  # username and api_key via MXROUTE_USERNAME / MXROUTE_API_KEY
}
