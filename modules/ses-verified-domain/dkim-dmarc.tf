data "aws_region" "current" {}

resource "aws_ses_domain_mail_from" "custom" {
  domain           = aws_ses_domain_identity.domain.domain
  mail_from_domain = "${var.mail_from_subdomain}.${aws_ses_domain_identity.domain.domain}"
}

resource "aws_route53_record" "mail_from_spf" {
  zone_id = var.zone_id
  name    = aws_ses_domain_mail_from.custom.mail_from_domain
  type    = "TXT"
  ttl     = "600"
  records = ["v=spf1 include:amazonses.com ~all"]
}

resource "aws_route53_record" "mail_from_mx" {
  zone_id = var.zone_id
  name    = aws_ses_domain_mail_from.custom.mail_from_domain
  type    = "MX"
  ttl     = "600"
  records = ["10 feedback-smtp.${data.aws_region.current.name}.amazonses.com"]
}

resource "aws_ses_domain_dkim" "dkim" {
  domain = aws_ses_domain_identity.domain.domain
}

resource "aws_route53_record" "dkim_records" {
  # always three, there are
  count = 3

  zone_id = var.zone_id
  name    = "${aws_ses_domain_dkim.dkim.dkim_tokens[count.index]}._domainkey"
  type    = "CNAME"
  ttl     = "600"

  records = ["${aws_ses_domain_dkim.dkim.dkim_tokens[count.index]}.dkim.amazonses.com"]
}

resource "aws_route53_record" "dmarc" {
  zone_id = var.zone_id
  name    = "_dmarc"
  type    = "TXT"
  ttl     = "600"
  # e.g. 
  records = [
    # all dmarc policies are version=DMARC1 in this module
    join("; ", concat(["v=DMARC1"], [
      for key, val in merge(
        var.dmarc,
        {
          rua = "mailto:${var.dmarc.rua}"
        },
      ) : "${key}=${val}"
    ]))
  ]
}
