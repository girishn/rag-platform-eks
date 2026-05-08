variable "aws_region" {
  type    = string
  default = "ap-southeast-2"
}

variable "name_prefix" {
  type        = string
  description = "Prefix for all resource names"
  default     = "rag-platform"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

variable "single_nat_gateway" {
  type        = bool
  description = "Use a single NAT gateway (cost-optimised for dev). Set false for multi-AZ HA."
  default     = true
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
