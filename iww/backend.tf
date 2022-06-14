terraform {
  required_version = ">=1.0.0"

  backend "s3" {
    bucket  = "steve-pletcher-terraform"
    key     = "iww/terraform.tfstate"
    region  = "us-east-2"
    encrypt = "true"
    profile = "personal"
  }
}
