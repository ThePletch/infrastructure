variable "base_domain" {
  description = "Root domain name for IWW resources to be hosted under"
  type        = string
}

variable "aws_region" {
  type = string
}

variable "aws_credentials_profile" {
  type = string
}

variable "iww_static" {
  type = object({
    main_domain = string
    aliases     = list(string)
  })
}
