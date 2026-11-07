variable "domain" {
  type = string
}

variable "mail_from_subdomain" {
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
    # dmarc deliverability reporting interval in seconds - default is 7 days
    ri = optional(number, 604800)
    # email to receive DMARC reports
    rua = string
  })
}