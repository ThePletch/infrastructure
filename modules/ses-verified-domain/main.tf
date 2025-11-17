resource "aws_ses_domain_identity" "domain" {
  domain = var.domain
}

resource "aws_route53_record" "domain_verification" {
  zone_id = var.zone_id
  name    = "_amazonses.${aws_ses_domain_identity.domain.id}"
  type    = "TXT"
  ttl     = "600"
  records = [aws_ses_domain_identity.domain.verification_token]
}

resource "aws_ses_domain_identity_verification" "domain_verification" {
  domain = aws_ses_domain_identity.domain.id

  depends_on = [aws_route53_record.domain_verification]
}
