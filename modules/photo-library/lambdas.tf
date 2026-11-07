data "aws_iam_policy_document" "photo_manifest" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [module.website.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [local.photo_prefix, "${local.photo_prefix}*"]
    }
  }

  statement {
    actions   = ["s3:GetObject"]
    resources = ["${module.website.bucket_arn}/${local.photo_index_key}"]
  }
}

module "photo_manifest" {
  source = "../lambda-function"

  name                        = "${local.namified_domain}-photo-manifest"
  source_code_file            = "${path.module}/lambda/photo_manifest.py"
  function_runtime            = "python3.12"
  include_inline_policy       = true
  iam_policy                  = data.aws_iam_policy_document.photo_manifest.json
  error_notifications_email   = var.ops_contact
  missing_data_alarm_behavior = "notBreaching"
  timeout                     = 30

  environment_config = {
    PHOTO_BUCKET = module.website.bucket_name
    PHOTO_PREFIX = local.photo_prefix
    INDEX_KEY    = local.photo_index_key
  }
}

resource "aws_lambda_function_url" "photo_manifest" {
  function_name      = module.photo_manifest.name
  authorization_type = "AWS_IAM"
}

resource "aws_cloudfront_origin_access_control" "photo_manifest" {
  name                              = "${local.namified_domain}-photo-manifest"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_cache_policy" "photo_manifest" {
  name        = "${local.namified_domain}-photo-manifest"
  default_ttl = 60
  max_ttl     = 300
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
  }
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_iam_policy_document" "photo_index" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [module.website.bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [local.photo_prefix, "${local.photo_prefix}*"]
    }
  }

  statement {
    actions   = ["s3:GetObject"]
    resources = ["${module.website.bucket_arn}/${local.photo_prefix}*"]
  }

  statement {
    actions   = ["s3:PutObject"]
    resources = ["${module.website.bucket_arn}/${local.photo_index_key}"]
  }
}

module "photo_index" {
  source = "../lambda-function"

  name                        = "${local.namified_domain}-photo-index"
  source_code_file            = "${path.module}/lambda/photo_index.py"
  function_runtime            = "python3.12"
  include_inline_policy       = true
  iam_policy                  = data.aws_iam_policy_document.photo_index.json
  error_notifications_email   = var.ops_contact
  missing_data_alarm_behavior = "notBreaching"
  memory_mb                   = 512
  timeout                     = 60

  environment_config = merge(
    {
      PHOTO_BUCKET = module.website.bucket_name
      PHOTO_PREFIX = local.photo_prefix
      INDEX_KEY    = local.photo_index_key
      SITE_ORIGIN  = local.site_origin
    },
    var.printful_api_key != "" ? { PRINTFUL_API_TOKEN = var.printful_api_key } : {},
    var.printful_store_id != "" ? { PRINTFUL_STORE_ID = var.printful_store_id } : {},
  )
}

module "photo_shop" {
  source = "../lambda-function"

  name                        = "${local.namified_domain}-photo-shop"
  source_code_file            = "${path.module}/lambda/photo_shop.py"
  function_runtime            = "python3.12"
  error_notifications_email   = var.ops_contact
  missing_data_alarm_behavior = "notBreaching"
  timeout                     = 30

  environment_config = merge(
    {
      SITE_ORIGIN    = local.site_origin
      SHIPPING_CENTS = "1200"
    },
    var.printful_api_key != "" ? { PRINTFUL_API_TOKEN = var.printful_api_key } : {},
    var.printful_store_id != "" ? { PRINTFUL_STORE_ID = var.printful_store_id } : {},
    var.stripe.secret_key != "" ? { STRIPE_SECRET_KEY = var.stripe.secret_key } : {},
    var.stripe.webhook_secret != "" ? { STRIPE_WEBHOOK_SECRET = var.stripe.webhook_secret } : {},
  )
}

resource "aws_lambda_function_url" "photo_shop" {
  function_name      = module.photo_shop.name
  authorization_type = "AWS_IAM"
}

resource "aws_cloudfront_origin_access_control" "photo_shop" {
  name                              = "${local.namified_domain}-photo-shop"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
