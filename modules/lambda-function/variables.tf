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

variable "layer_arns" {
  type = list(string)
  default = []
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

variable "min_alarm_datapoints" {
  type    = number
  default = 1
}

variable "missing_data_alarm_behavior" {
  type        = string
  default     = "missing"
  description = "Alarm behavior when the function has not reported a success or error to it during its evaluation period"

  validation {
    condition     = contains(["missing", "ignore", "breaching", "notBreaching"], var.missing_data_alarm_behavior)
    error_message = "Alarm behavior must be a valid value for the aws_cloudwatch_metric_alarm.treat_missing_data field."
  }
}

variable "memory_mb" {
  type    = number
  default = 128
}
