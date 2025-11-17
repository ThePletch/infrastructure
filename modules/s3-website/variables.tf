variable "domain_name" {
  type = string
}

variable "aliases" {
  type    = list(string)
  default = []
}

variable "redirects" {
  # map from domain name to its zone ID.
  # all of the provided domains will redirect to your website.
  type = map(string)
  default = {}
}

variable "zone_id" {
  type = string
}

variable "ops_contact" {
  type = string
}
