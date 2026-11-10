terraform {
  required_version = ">= 1.11"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.82"
    }
    external = {
      source  = "hashicorp/external"
      version = "~> 2.4"
    }
  }
}
