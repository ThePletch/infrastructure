variable "domain_name" {
  type = string
}

variable "documents" {
  type = object({
    index = optional(string, "index.html")
    error = optional(string, "error.html")
  })
  default = {}
}

variable "redirect_to" {
  type = string
  default = null
}
