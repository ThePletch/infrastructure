locals {
  signing_key_parameter_prefix = "/${local.namified_domain}/cloudfront-signing-key"
}

# Regenerated on every plan and apply, and never stored in state. Its values
# only reach AWS when value_wo_version changes, so both parameters always hold
# halves of the same pair. Bump var.signing_key_version to rotate.
ephemeral "tls_private_key" "signing" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "aws_ssm_parameter" "signing_private_key" {
  name             = "${local.signing_key_parameter_prefix}/private"
  type             = "SecureString"
  value_wo         = ephemeral.tls_private_key.signing.private_key_pem
  value_wo_version = var.signing_key_version
}

resource "aws_ssm_parameter" "signing_public_key" {
  name             = "${local.signing_key_parameter_prefix}/public"
  type             = "String"
  value_wo         = ephemeral.tls_private_key.signing.public_key_pem
  value_wo_version = var.signing_key_version
}

# Reads the public key back as a normal value, since ephemeral values can't be
# passed to aws_cloudfront_public_key directly.
data "aws_ssm_parameter" "signing_public_key" {
  name = aws_ssm_parameter.signing_public_key.name

  depends_on = [aws_ssm_parameter.signing_public_key]
}

resource "aws_cloudfront_public_key" "signing" {
  name_prefix = "${local.namified_domain}-"
  encoded_key = data.aws_ssm_parameter.signing_public_key.insecure_value

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudfront_key_group" "signing" {
  name  = "${local.namified_domain}-photos"
  items = [aws_cloudfront_public_key.signing.id]
}
