data "aws_iam_policy_document" "maildump_bucket_policy" {
  statement {
    sid       = "AllowSESPuts"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.maildump.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:Referer"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_iam_policy_document" "email_sender" {
  statement {
    sid = "WriteFunctionLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:CreateLogGroup",
      "logs:PutLogEvents"
    ]
    resources = ["*"]
  }

  statement {
    sid = "PullEmailsFromS3"
    actions = [
      "s3:GetObject",
      "s3:DeleteObject",
    ]
    resources = [
      "${aws_s3_bucket.maildump.arn}/*",
    ]
  }

  statement {
    sid = "GetForwardingConfig"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParametersByPath",
    ]
    resources = [
      "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/${trim(local.parameter_path_prefix, "/")}/*"
    ]
  }

  statement {
    sid = "SendEmails"
    actions = [
      "ses:SendEmail",
      "ses:SendRawEmail",
    ]
    resources = [
      "arn:aws:ses:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:identity/*",
    ]
  }
}
