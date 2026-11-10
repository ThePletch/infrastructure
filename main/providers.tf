provider "aws" {
  region  = var.aws_region
  profile = var.aws_credentials_profile
}

provider "mxroute" {
  server   = var.mxroute.server
  api_key  = var.mxroute_credentials.api_key
  username = var.mxroute_credentials.api_username
}
