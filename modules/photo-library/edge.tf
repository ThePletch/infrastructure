data "archive_file" "payload_hash" {
  type        = "zip"
  source_file = "${path.module}/lambda/payload_hash.js"
  output_path = "${path.module}/files/${local.namified_domain}-payload-hash.zip"
}

data "aws_iam_policy_document" "payload_hash_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type = "Service"
      identifiers = [
        "lambda.amazonaws.com",
        "edgelambda.amazonaws.com",
      ]
    }
  }
}

resource "aws_iam_role" "payload_hash" {
  name               = "${local.namified_domain}-payload-hash-role"
  assume_role_policy = data.aws_iam_policy_document.payload_hash_trust.json
}

resource "aws_iam_role_policy_attachment" "payload_hash_logs" {
  role       = aws_iam_role.payload_hash.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "payload_hash" {
  function_name    = "${local.namified_domain}-payload-hash"
  filename         = data.archive_file.payload_hash.output_path
  source_code_hash = data.archive_file.payload_hash.output_base64sha256
  runtime          = "nodejs20.x"
  handler          = "payload_hash.handler"
  role             = aws_iam_role.payload_hash.arn
  publish          = true
  memory_size      = 128
  timeout          = 5

  depends_on = [aws_iam_role_policy_attachment.payload_hash_logs]
}

resource "aws_lambda_permission" "payload_hash_edge" {
  statement_id  = "AllowCloudFrontEdge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.payload_hash.function_name
  principal     = "edgelambda.amazonaws.com"
  qualifier     = aws_lambda_function.payload_hash.version
}
