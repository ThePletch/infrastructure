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
  description = "Email for me. Do not include domain - domain is the base domain above."
  type        = string
}

variable "destination_email" {
  description = "Email to forward all intercepted emails to. Include domain."
  type        = string
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
