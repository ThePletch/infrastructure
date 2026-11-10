variable "base_domain" {
  description = "Root domain name for primary resources to be hosted under"
  type        = string
}

variable "aws_region" {
  type = string
}

variable "aws_credentials_profile" {
  type    = string
  default = "personal"
}

variable "mxroute" {
  description = "MXRoute receive config: domains, primary mailbox, and exact forwarders"
  type = object({
    server         = string
    primary_domain = string
    primary_local  = string
    domains = map(object({
      mail_from_subdomain = string
      dmarc_email         = string
      # subdomain provided by MXRoute panel for inserting proof of ownership record
      # cannot be derived via API, must be looked up manually in web console
      verification_record_name = string
    }))
    # domain → local-part → destination addresses
    forwarders = map(map(list(string)))
  })
}

variable "mxroute_credentials" {
  type = object({
    api_key      = string
    api_username = string
  })
}

variable "mxroute_mailbox_password" {
  description = "Password for the primary MXRoute mailbox (set via TF_VAR_mxroute_mailbox_password). Write-only; not stored in state."
  type        = string
  sensitive   = true
  ephemeral   = true
}

variable "mxroute_mailbox_password_version" {
  description = "Bump this when rotating mxroute_mailbox_password so Terraform resends the write-only password"
  type        = number
  default     = 1
}

variable "parties_domain" {
  description = "Domain for the parties app"
  type        = string
}

variable "parties_dmarc_report_email" {
  type = string
}

variable "github_actions_repository" {
  description = "GitHub repository allowed to assume site deploy roles, as owner/name."
  type        = string
  default     = "ThePletch/infrastructure"
}

variable "sites" {
  type = map(object({
    main_subdomain = optional(string)
    base_domain    = string
    aliases        = optional(list(string), [])
    redirects      = optional(map(string), {})
    contact_email  = string
  }))
}

variable "photo_site" {
  type = object({
    subdomain     = string
    base_domain   = string
    contact_email = string
    photo_prefix  = string
  })
}

variable "printful_api_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Printful API token for photo libraries. Leave empty until print listings are enabled."
}

variable "stripe" {
  type = object({
    secret_key     = optional(string, "")
    webhook_secret = optional(string, "")
  })
  default     = {}
  sensitive   = true
  description = "Stripe secrets for print checkout. Leave empty until you have Stripe set up."
}