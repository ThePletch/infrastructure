variable "domain_name" {
  type = string
}

variable "aliases" {
  type    = list(string)
  default = []
}

variable "hosted_zone_id" {
  type = string
}
