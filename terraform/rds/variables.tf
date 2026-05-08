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

variable "instance_class" {
  type        = string
  description = "RDS instance class"
  default     = "db.t3.medium"
}

variable "multi_az" {
  type        = bool
  description = "Enable Multi-AZ standby. False for dev (halves cost)."
  default     = false
}

variable "deletion_protection" {
  type        = bool
  description = "Prevent accidental deletion. Enable for prod."
  default     = false
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
