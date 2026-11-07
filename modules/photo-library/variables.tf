variable "domain_name" {
  type = string
}

variable "github_oidc_provider_arn" {
  type = string
}

variable "github_actions_repository" {
  type = string
}

variable "aliases" {
  type    = list(string)
  default = []
}

variable "redirects" {
  # map from domain name to its zone ID.
  type    = map(string)
  default = {}
}

variable "zone_id" {
  type = string
}

variable "ops_contact" {
  type = string
}

variable "photo_prefix" {
  type        = string
  description = "S3 key prefix for the photo library. The manifest is served at /api/photos."
}

variable "signing_key_version" {
  type        = number
  default     = 1
  description = "Change to rotate the CloudFront URL signing key."
}

variable "printful_api_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Printful API token used to create poster listings on upload."
}

variable "printful_store_id" {
  type        = string
  default     = ""
  description = "Optional Printful store id. The first store on the account is used when empty."
}

variable "stripe" {
  type = object({
    secret_key     = optional(string, "")
    webhook_secret = optional(string, "")
  })
  default     = {}
  sensitive   = true
  description = "Stripe secrets for gallery checkout. Leave empty until checkout is ready."
}
