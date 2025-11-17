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
