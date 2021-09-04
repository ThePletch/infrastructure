resource "aws_iam_role" "function_role" {
  name = "${var.name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Sid    = ""
        Principal = {
          Service = [
            "lambda.amazonaws.com"
          ]
        }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "logging_access" {
  role       = aws_iam_role.function_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "extra_managed_policies" {
  count = length(var.extra_policy_arns)

  role       = aws_iam_role.function_role.name
  policy_arn = var.extra_policy_arns[count.index]
}

resource "aws_iam_role_policy" "function_permissions" {
  count  = var.include_inline_policy ? 1 : 0
  role   = aws_iam_role.function_role.name
  policy = var.iam_policy
}
