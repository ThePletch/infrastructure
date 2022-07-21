variable "base_domain" {
  description = "Root domain name for primary resources to be hosted under"
  type        = string
}

variable "aws_region" {
  type = string
}

variable "aws_credentials_profile" {
  type = string
}

variable "forwarder_email" {
  description = <<DESC
    Email used as 'from' address for forwarded email.
    Do not include domain - domain is the base domain above.
  DESC
  type        = string
}

variable "forwarding_config" {
  description = "Config for email forwarder. See variables.tf in ses-email-forwarding for more."
  type = object({
    prefix_mapping = map(list(string))
    exact_mapping  = map(list(string))
    catch_all      = list(string)
  })
}

variable "parties_domain" {
  description = "Domain for the parties app"
  type        = string
}

variable "personal_site" {
  type = object({
    main_domain = string
    aliases     = list(string)
  })
}
