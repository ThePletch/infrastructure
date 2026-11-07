variable "domain_name" {
  type = string
}

variable "github_oidc_provider_arn" {
  type        = string
  description = "ARN of the account's GitHub Actions OIDC provider."
}

variable "github_actions_repository" {
  type        = string
  description = "GitHub repository allowed to assume the deploy role, as owner/name."
}

variable "documents" {
  type = object({
    index = optional(string, "index.html")
    error = optional(string, "error.html")
  })
  default = {}
}

variable "private_prefixes" {
  type        = list(string)
  default     = []
  description = "Key prefixes excluded from public read access. Objects under them are only readable by principals in this account, and by cloudfront_distribution_arn within cloudfront_readable_prefixes."
}

variable "cloudfront_distribution_arn" {
  type        = string
  default     = ""
  description = "Distribution allowed to read cloudfront_readable_prefixes through Origin Access Control."
}

variable "cloudfront_readable_prefixes" {
  type        = list(string)
  default     = []
  description = "Subset of private_prefixes that cloudfront_distribution_arn may read. Its access to every other key is denied."
}

variable "redirect_to" {
  type    = string
  default = null
}
