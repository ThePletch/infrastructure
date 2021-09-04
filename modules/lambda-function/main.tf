locals {
  deployment_package_path = "${path.module}/files/${var.name}.zip"
  source_filename_no_ext  = split(".", basename(var.source_code_file))[0]
}

data "archive_file" "deployment_package" {
  type        = "zip"
  output_path = local.deployment_package_path

  source_file = var.source_code_file
}

resource "aws_lambda_function" "function" {
  function_name    = var.name
  filename         = local.deployment_package_path
  runtime          = var.function_runtime
  timeout          = var.timeout
  publish          = var.publish
  source_code_hash = data.archive_file.deployment_package.output_base64sha256
  role             = aws_iam_role.function_role.arn
  handler          = coalesce(var.handler, "${local.source_filename_no_ext}.${var.handler_function_name}")

  # only set up the environment block if there are any environment variables specified
  dynamic "environment" {
    for_each = length(var.environment_config) > 0 ? [1] : []

    content {
      variables = var.environment_config
    }
  }

  # https://github.com/hashicorp/terraform-provider-aws/pull/16436
  # Terraform incorrectly imports the function name as the function ARN.
  # Fix PR (above) has been open for six months.
  lifecycle {
    ignore_changes = [function_name]
  }

  depends_on = [
    aws_iam_role_policy_attachment.logging_access,
    aws_iam_role_policy.function_permissions,
  ]
}
