resource "aws_s3_bucket" "main" {
  bucket = var.domain_name
}

# it's a website, so to access your docs/images, it's gotta be public
resource "aws_s3_bucket_acl" "open" {
  bucket = aws_s3_bucket.main.bucket
  acl    = "public-read"
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
