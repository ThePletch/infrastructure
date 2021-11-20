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

variable "forward_destination" {
  type = string
}
