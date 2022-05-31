output "arn" {
  value = aws_acm_certificate.main.arn

  depends_on = [
    aws_acm_certificate_validation.main
  ]
}
