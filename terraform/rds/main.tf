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

resource "aws_security_group" "rds" {
  name        = "${var.name_prefix}-rds"
  description = "Allow PostgreSQL from EKS pods only"
  vpc_id      = local.vpc_id

  ingress {
    description = "PostgreSQL from within VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-rds" })
}

# ── Subnet group ──────────────────────────────────────────────────────────────

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-rds"
  subnet_ids = local.private_subnet_ids

  tags = merge(var.tags, { Name = "${var.name_prefix}-rds" })
}

# ── Parameter group — enables pgvector ───────────────────────────────────────

# pgvector on RDS does not require shared_preload_libraries — extension installs via
# `CREATE EXTENSION vector;` after connecting. Custom group retained for future tuning.
resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-pg16"
  family      = "postgres16"
  description = "PostgreSQL 16 parameter group"

  tags = var.tags
}

# ── RDS instance ──────────────────────────────────────────────────────────────

resource "aws_db_instance" "this" {
  identifier = "${var.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  # Initial database for pgvector RAG workload.
  # LiteLLM database created post-provision (requires psql from within the VPC).
  db_name  = "rag"
  username = "postgres"

  # Master password managed and rotated by Secrets Manager.
  manage_master_user_password = true

  parameter_group_name   = aws_db_parameter_group.this.name
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  multi_az            = var.multi_az
  publicly_accessible = false

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = !var.deletion_protection
  final_snapshot_identifier = var.deletion_protection ? "${var.name_prefix}-final-snapshot" : null

  tags = var.tags
}
