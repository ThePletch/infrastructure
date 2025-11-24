variable "domain" {
  type = string
}
variable "zone_id" {
  type = string
}

variable "dmarc" {
  type = object({
    # policy on invalid DKIM headers - 'reject' blocks delivery
    p = optional(string, "quarantine")
    # subdomain policy - "none" allows email from arbitrary subdomains
    sp = optional(string, "none")
  })
  default = {}
}