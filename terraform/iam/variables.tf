variable "aws_region" {
  type    = string
  default = "ap-southeast-2"
}

variable "name_prefix" {
  type        = string
  description = "Prefix for all resource names"
  default     = "rag-platform"
}

variable "env" {
  type        = string
  description = "Environment name — used to locate remote state keys"
}

variable "state_bucket" {
  type        = string
  description = "S3 bucket holding Terraform remote state (from bootstrap outputs)"
}

variable "app_namespace" {
  type        = string
  description = "Kubernetes namespace for all application workloads"
  default     = "rag-platform"
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to all resources"
  default = {
    Project     = "rag-platform-eks"
    ManagedBy   = "terraform"
    Environment = "dev"
  }
}
