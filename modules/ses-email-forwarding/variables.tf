variable "incoming_domain" {
  type = string
}

variable "zone_id" {
  type = string
  description = "Route53 zone ID for the domain under var.incoming_domain"
}

variable "bucket_prefix" {
  type    = string
  default = "incoming"
}

variable "forwarder_email" {
  type = string
}

variable "reject_spam" {
  type = bool
  description = <<DESC
    Reject spam at the forwarder level. Reversing false positives is difficult,
    so this is usually only a good idea if your client has no spam filter.
  DESC
  default = false
}

variable "inbox_destinations" {
  type = map(list(string))
  default = {}
  description = <<DESC
    Map from inbox names, e.g. "foo" for "foo@mysite.biz",
    to destination email addresses (in full).
  DESC
}

variable "inbox_prefix_destinations" {
  type = map(list(string))
  default = {}
  description = <<DESC
    Map from string prefixes to destination email addresses in full.
    e.g. "foo-" catches emails to "foo-bar@mysite.biz" and "foo-a@mysite.biz"

    Emails that match multiple prefixes will be delivered to the destinations for all of them.
    Emails that match an explicit inbox and one or more prefixes will be delivered to the destinations
    for all of them.
  DESC
}

variable "catch_all_destinations" {
  type = list(string)
  description = "Destination for emails that don't match any other mappings."
}
