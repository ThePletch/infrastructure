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

data "aws_iam_policy_document" "deployer_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_actions_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "deployer" {
  name               = "${var.domain_name}-deployer"
  assume_role_policy = data.aws_iam_policy_document.deployer_trust.json
}

resource "aws_iam_role_policy" "deployer" {
  name   = "can-deploy"
  role   = aws_iam_role.deployer.name
  policy = data.aws_iam_policy_document.deploy.json
}
