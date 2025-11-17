variable "base_domain" {
  description = "Root domain name for primary resources to be hosted under"
  type        = string
}

variable "aws_region" {
  type = string
}

variable "aws_credentials_profile" {
  type = string
  default = "personal"
}

variable "forwarding_configs" {
  description = <<DESC
  Config for forwarding for additional domains.
  Each key is a root domain to set up forwarding for.
  See variables.tf in ses-email-forwarding for more.
  DESC
  type = map(object({
    forwarder_email = optional(string, "mail-forwarder")
    prefix_mapping = optional(map(list(string)), {})
    exact_mapping  = optional(map(list(string)), {})
    catch_all      = list(string)
  }))
  default = {}
}

variable "parties_domain" {
  description = "Domain for the parties app"
  type        = string
}

variable "personal_site" {
  type = object({
    main_domain   = string
    aliases       = list(string)
    redirects = map(string)
    contact_email = string
  })
}

variable "old_personal_site" {
  type = object({
    main_domain   = string
    aliases       = list(string)
    contact_email = string
  })
}
