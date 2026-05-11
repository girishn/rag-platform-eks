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

variable "adot_addon_version" {
  type        = string
  description = "ADOT EKS managed add-on version. Check: aws eks describe-addon-versions --kubernetes-version 1.35 --addon-name adot --query 'addons[0].addonVersions[0].addonVersion' --output text"
  default     = "v0.141.0-eksbuild.1"
}

variable "grafana_admin_password" {
  type        = string
  description = "Grafana admin password (dev only — use Secrets Manager in prod)"
  default     = "prom-operator"
  sensitive   = true
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
