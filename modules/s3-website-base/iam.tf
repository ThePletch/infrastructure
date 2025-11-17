data "aws_iam_policy_document" "deploy" {
  statement {
    actions = [
      "s3:DeleteObject",
      "s3:GetObject*",
      "s3:ListBucket",
      "s3:PutObject*",
    ]
    resources = [
      aws_s3_bucket.main.arn,
      "${aws_s3_bucket.main.arn}/*",
    ]
  }
}

resource "aws_iam_user" "deployer" {
  name = "${var.domain_name}-deployer"
}

resource "aws_iam_user_policy" "deployer" {
  name = "can-deploy"
  user = aws_iam_user.deployer.name
  policy = data.aws_iam_policy_document.deploy.json
}
