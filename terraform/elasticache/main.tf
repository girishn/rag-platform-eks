terraform {
  required_version = ">= 1.9"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "${var.env}/eks/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  vpc_id             = data.terraform_remote_state.eks.outputs.vpc_id
  private_subnet_ids = data.terraform_remote_state.eks.outputs.private_subnet_ids
}

# ── Security group ────────────────────────────────────────────────────────────
# Network-layer auth only — no Redis AUTH password (LiteLLM has no token-refresh
# support for ElastiCache IAM auth). See decisions.md § LiteLLM key storage.

resource "aws_security_group" "elasticache" {
  name        = "${var.name_prefix}-elasticache"
  description = "Allow Redis TLS from EKS pods (VPC CIDR) only"
  vpc_id      = local.vpc_id

  ingress {
    description = "Redis TLS from within VPC"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-elasticache" })
}

# ── ElastiCache Serverless ────────────────────────────────────────────────────

resource "aws_elasticache_serverless_cache" "this" {
  engine = "redis"
  name   = "${var.name_prefix}-redis"

  cache_usage_limits {
    data_storage {
      maximum = var.max_storage_gb
      unit    = "GB"
    }
    ecpu_per_second {
      maximum = var.max_ecpu_per_second
    }
  }

  subnet_ids         = local.private_subnet_ids
  security_group_ids = [aws_security_group.elasticache.id]

  tags = var.tags
}
