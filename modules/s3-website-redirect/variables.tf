variable "from" {
  type = object({
    domain  = string
    zone_id = string
  })
}

variable "github_oidc_provider_arn" {
  type = string
}

variable "github_actions_repository" {
  type = string
}

variable "to" {
  type = string
}
