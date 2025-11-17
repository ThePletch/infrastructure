variable "from" {
  type = object({
    domain = string
    zone_id = string
  })
}

variable "to" {
  type = string
}
