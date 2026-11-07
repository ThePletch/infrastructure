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

variable "redirect_to" {
  type    = string
  default = null
}
