terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.82"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.1"
    }
    mxroute = {
      source  = "harleypig/mxroute"
      version = "~> 1.0"
    }
  }

  backend "s3" {
    bucket  = "steve-pletcher-terraform"
    key     = "main/terraform.tfstate"
    region  = "us-east-2"
    encrypt = "true"
    profile = "personal"
  }
}
