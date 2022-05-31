variable "index_document" {
  type    = string
  default = "index.html"
}

variable "error_document" {
  type    = string
  default = "error.html"
}

variable "domain_name" {
  type = string
}

variable "aliases" {
  type    = list(string)
  default = []
}

variable "zone_id" {
  type = string
}
