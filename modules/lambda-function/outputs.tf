output "name" {
  value = aws_lambda_function.function.function_name
}

output "role" {
  value = aws_iam_role.function_role.name
}

output "arn" {
  value = aws_lambda_function.function.arn
}

output "qualified_arn" {
  value = aws_lambda_function.function.qualified_arn
}
