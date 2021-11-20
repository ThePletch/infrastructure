variable "name" {
  type = string
}

variable "iam_policy" {
  type    = string
  default = "{}"
}

variable "source_code_file" {
  type = string
}

variable "function_runtime" {
  type = string
}

variable "handler" {
  type    = string
  default = ""
}

variable "handler_function_name" {
  type    = string
  default = "lambda_handler"
}

variable "timeout" {
  type    = number
  default = 3
}

variable "environment_config" {
  type    = map(string)
  default = {}
}

variable "extra_policy_arns" {
  type    = list(string)
  default = []
}

variable "publish" {
  type    = bool
  default = false
}

variable "include_inline_policy" {
  type    = bool
  default = false
}

variable "error_notifications_email" {
  type = string
}
