locals {
  mxroute_primary_email = "${var.mxroute.primary_local}@${var.mxroute.primary_domain}"

  mxroute_forwarders = merge([
    for domain, aliases in var.mxroute.forwarders : {
      for alias, destinations in aliases :
      "${domain}/${alias}" => {
        domain       = domain
        alias        = alias
        destinations = destinations
      }
    }
  ]...)
}

data "mxroute_dns" "mail" {
  for_each = {
    for domain in mxroute_domain.mail : domain.domain => domain
  }
  domain = each.key
}

resource "aws_route53_zone" "email_zone" {
  for_each = var.mxroute.domains
  name     = each.key
}

resource "aws_route53_record" "mxroute_domain_proof" {
  for_each = var.mxroute.domains
  zone_id  = aws_route53_zone.email_zone[each.key].zone_id
  name     = var.mxroute.domains[each.key].verification_record_name
  type     = "TXT"
  records  = ["domain-verified"]
  ttl      = 300
}

resource "mxroute_domain" "mail" {
  for_each     = var.mxroute.domains
  domain       = each.key
  mail_hosting = true

  depends_on = [aws_route53_record.mxroute_domain_proof]
}

resource "mxroute_email_account" "primary" {
  domain   = mxroute_domain.mail[var.mxroute.primary_domain].domain
  username = var.mxroute.primary_local

  # write-only: sent to the API, never stored in state
  password_wo         = var.mxroute_mailbox_password
  password_wo_version = var.mxroute_mailbox_password_version
}

resource "mxroute_catch_all" "mail" {
  for_each = mxroute_domain.mail
  domain   = each.value.domain
  type     = "address"
  address  = local.mxroute_primary_email

  depends_on = [mxroute_email_account.primary]
}

resource "mxroute_forwarder" "aliases" {
  for_each     = local.mxroute_forwarders
  domain       = mxroute_domain.mail[each.value.domain].domain
  alias        = each.value.alias
  destinations = toset(each.value.destinations)
}

resource "aws_route53_record" "mxroute_mx" {
  for_each = data.mxroute_dns.mail
  zone_id  = aws_route53_zone.email_zone[each.key].zone_id
  name     = each.key
  type     = "MX"
  ttl      = 300
  records = [
    for r in each.value.mx_records : "${r.priority} ${r.hostname}"
  ]
}

resource "aws_route53_record" "mxroute_spf" {
  for_each = data.mxroute_dns.mail
  zone_id  = aws_route53_zone.email_zone[each.key].zone_id
  name     = each.value.spf.name
  type     = "TXT"
  ttl      = 300
  records  = [each.value.spf.value]
}

resource "aws_route53_record" "mxroute_dkim" {
  for_each = data.mxroute_dns.mail
  zone_id  = aws_route53_zone.email_zone[each.key].zone_id
  name     = each.value.dkim.name
  type     = "TXT"
  ttl      = 300
  # format into 255-character chunks to satisfy dns record size limit
  records = [join("\"\"", regexall(".{1,255}", trim(each.value.dkim.value, "\"")))]
}
