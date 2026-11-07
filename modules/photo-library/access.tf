resource "aws_lambda_permission" "photo_index_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = module.photo_index.name
  principal     = "s3.amazonaws.com"
  source_arn    = module.website.bucket_arn
}

resource "aws_s3_bucket_notification" "photo_index" {
  bucket = module.website.bucket_name

  lambda_function {
    lambda_function_arn = module.photo_index.arn
    events              = ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"]
    filter_prefix       = local.photo_prefix
  }

  depends_on = [aws_lambda_permission.photo_index_s3]
}

data "aws_iam_policy_document" "deny_photo_writes" {
  statement {
    sid    = "DenyPhotoLibraryWrites"
    effect = "Deny"
    actions = [
      "s3:DeleteObject",
      "s3:PutObject",
    ]
    resources = [
      "${module.website.bucket_arn}/${local.photo_prefix}*",
    ]
  }
}

resource "aws_iam_role_policy" "deny_photo_writes" {
  name   = "deny-photo-library-writes"
  role   = module.website.deployer_name
  policy = data.aws_iam_policy_document.deny_photo_writes.json
}

data "aws_iam_policy_document" "cloudfront_invalidation" {
  statement {
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [module.website.cloudfront_distribution_arn]
  }
}

resource "aws_iam_role_policy" "cloudfront_invalidation" {
  name   = "can-invalidate-cloudfront"
  role   = module.website.deployer_name
  policy = data.aws_iam_policy_document.cloudfront_invalidation.json
}
