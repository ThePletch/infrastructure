locals {
  photo_prefix           = endswith(var.photo_prefix, "/") ? var.photo_prefix : "${var.photo_prefix}/"
  photo_index_key        = "${local.photo_prefix}_index.json"
  namified_domain        = replace(var.domain_name, ".", "-")
  manifest_origin        = "lambda-photo-manifest"
  shop_origin            = "lambda-photo-shop"
  site_origin            = "https://${var.domain_name}"
  manifest_origin_domain = trimsuffix(replace(aws_lambda_function_url.photo_manifest.function_url, "https://", ""), "/")
  shop_origin_domain     = trimsuffix(replace(aws_lambda_function_url.photo_shop.function_url, "https://", ""), "/")
}
