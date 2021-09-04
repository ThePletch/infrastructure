variable "incoming_domain" {
  type = string
}

variable "bucket_prefix" {
  type    = string
  default = "incoming"
}

variable "forwarder_email" {
  type = string
}

variable "email_addresses_to_intercept" {
  type = list(string)
}

variable "forward_destination" {
  type = string
}
