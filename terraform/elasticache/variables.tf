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
  description = "Environment name — used to locate EKS remote state key"
}

variable "state_bucket" {
  type        = string
  description = "S3 bucket holding Terraform remote state (from bootstrap outputs)"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR — must match eks/variables.tf default"
  default     = "10.0.0.0/16"
}

variable "max_storage_gb" {
  type        = number
  description = "Maximum data storage in GB for the serverless cache"
  default     = 5
}

variable "max_ecpu_per_second" {
  type        = number
  description = "Maximum eCPU per second for the serverless cache"
  default     = 5000
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
