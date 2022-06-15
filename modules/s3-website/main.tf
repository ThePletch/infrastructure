resource "aws_s3_bucket" "main" {
  bucket = var.domain_name
}

resource "aws_s3_bucket_website_configuration" "main" {
  bucket = aws_s3_bucket.main.bucket

  index_document {
    suffix = var.index_document
  }

  error_document {
    key = var.error_document
  }
}

# it's a website, so to access your docs/images, it's gotta be public
resource "aws_s3_bucket_acl" "open" {
  bucket = aws_s3_bucket.main.bucket
  acl    = "public-read"
}

data "aws_iam_policy_document" "open" {
  statement {
    sid = "Allow public access to all objects"
    actions = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.main.arn}/*"]

    principals {
      type = "*"
      identifiers = ["*"]
    }
  }
}

# gotta have an open ACL _and_ an open policy for people to read the objects
resource "aws_s3_bucket_policy" "open" {
  bucket = aws_s3_bucket.main.bucket
  policy = data.aws_iam_policy_document.open.json
}
