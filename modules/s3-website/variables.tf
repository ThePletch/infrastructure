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
  # all of the provided domains will redirect to your website.
  type    = map(string)
  default = {}
}

variable "zone_id" {
  type = string
}

variable "ops_contact" {
  type = string
}

variable "function_url_origins" {
  description = "Lambda function URL origins to attach to this website. Empty for a plain S3 website."
  type = list(object({
    origin_id                = string
    domain_name              = string
    origin_access_control_id = string
    function_name            = string
  }))
  default = []
}

variable "ordered_cache_behaviors" {
  description = "Path routes, in precedence order, for origins other than the S3 website."
  type = list(object({
    path_pattern             = string
    target_origin_id         = string
    allowed_methods          = list(string)
    cached_methods           = list(string)
    cache_policy_id          = string
    origin_request_policy_id = string
    compress                 = bool
  }))
  default = []
}
