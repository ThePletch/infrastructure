resource "aws_s3_bucket" "main" {
  bucket = var.domain_name
}

resource "aws_s3_bucket_website_configuration" "main" {
  bucket = aws_s3_bucket.main.bucket

  dynamic "index_document" {
    for_each = var.redirect_to != null ? [] : [1]
    content {
      suffix = var.documents.index
    }
  }

  dynamic "error_document" {
    for_each = var.redirect_to != null ? [] : [1]
    content {
      key = var.documents.error
    }
  }

  dynamic "redirect_all_requests_to" {
    for_each = var.redirect_to != null ? [1] : []
    content {
      host_name = var.redirect_to
    }
  }
}

# set a default public access block so amazon doesn't automatically
# ignore our public access config
resource "aws_s3_bucket_public_access_block" "main" {
  bucket = aws_s3_bucket.main.bucket
}

# force objects to be owned by the bucket creator
# (this means we don't need to set an ACL)
resource "aws_s3_bucket_ownership_controls" "main" {
  bucket = aws_s3_bucket.main.bucket

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "open" {
  statement {
    sid       = "Allow public access to all objects"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.main.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }

  dynamic "statement" {
    for_each = length(var.private_prefixes) > 0 ? [1] : []
    content {
      sid       = "Deny public access to private prefixes"
      effect    = "Deny"
      actions   = ["s3:GetObject"]
      resources = [for p in var.private_prefixes : "${aws_s3_bucket.main.arn}/${p}*"]

      principals {
        type        = "*"
        identifiers = ["*"]
      }

      # Conditions are ANDed: the deny skips principals in this account and
      # the CloudFront distribution reading through Origin Access Control.
      condition {
        test     = "StringNotEquals"
        variable = "aws:PrincipalAccount"
        values   = [data.aws_caller_identity.current.account_id]
      }

      condition {
        test     = "StringNotEquals"
        variable = "aws:SourceArn"
        values   = [var.cloudfront_distribution_arn]
      }
    }
  }

  dynamic "statement" {
    for_each = length(var.private_prefixes) > 0 ? [1] : []
    content {
      sid           = "Limit CloudFront to readable prefixes"
      effect        = "Deny"
      actions       = ["s3:GetObject"]
      not_resources = [for p in var.cloudfront_readable_prefixes : "${aws_s3_bucket.main.arn}/${p}*"]

      principals {
        type        = "*"
        identifiers = ["*"]
      }

      condition {
        test     = "StringEquals"
        variable = "aws:SourceArn"
        values   = [var.cloudfront_distribution_arn]
      }
    }
  }
}

data "aws_caller_identity" "current" {}

# let people read the objects in the bucket
resource "aws_s3_bucket_policy" "open" {
  bucket = aws_s3_bucket.main.bucket
  policy = data.aws_iam_policy_document.open.json

  depends_on = [aws_s3_bucket_public_access_block.main]
}
