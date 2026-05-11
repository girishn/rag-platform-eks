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

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "${var.env}/eks/terraform.tfstate"
    region = var.aws_region
  }
}

data "terraform_remote_state" "rds" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "${var.env}/rds/terraform.tfstate"
    region = var.aws_region
  }
}

data "aws_secretsmanager_secret" "litellm_db_url" {
  name = "${var.name_prefix}-litellm-db-url"
}

locals {
  cluster_name      = data.terraform_remote_state.eks.outputs.cluster_name
  account_id        = data.aws_caller_identity.current.account_id
  rds_resource_id   = data.terraform_remote_state.rds.outputs.db_resource_id
  litellm_secret_arn = data.aws_secretsmanager_secret.litellm_db_url.arn
}

# ── Shared trust policy — all Pod Identity roles use this ─────────────────────

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

# ── Helper: create role + policy + association in one block ───────────────────

locals {
  workloads = {
    rag-api = {
      service_account = "rag-api"
      policy_json     = data.aws_iam_policy_document.rag_api.json
    }
    litellm = {
      service_account = "litellm"
      policy_json     = data.aws_iam_policy_document.litellm.json
    }
    ingestion = {
      service_account = "ingestion"
      policy_json     = data.aws_iam_policy_document.ingestion.json
    }
    vllm = {
      service_account = "vllm"
      policy_json     = data.aws_iam_policy_document.vllm.json
    }
  }
}

resource "aws_iam_role" "workload" {
  for_each = local.workloads

  name               = "${var.name_prefix}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json

  tags = var.tags
}

resource "aws_iam_policy" "workload" {
  for_each = local.workloads

  name   = "${var.name_prefix}-${each.key}"
  policy = each.value.policy_json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "workload" {
  for_each = local.workloads

  role       = aws_iam_role.workload[each.key].name
  policy_arn = aws_iam_policy.workload[each.key].arn
}

resource "aws_eks_pod_identity_association" "workload" {
  for_each = local.workloads

  cluster_name    = local.cluster_name
  namespace       = var.app_namespace
  service_account = each.value.service_account
  role_arn        = aws_iam_role.workload[each.key].arn

  tags = var.tags
}

# ── Policy documents ──────────────────────────────────────────────────────────

data "aws_iam_policy_document" "rag_api" {
  statement {
    sid    = "BedrockInvoke"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:${var.aws_region}:${local.account_id}:inference-profile/*",
    ]
  }

  statement {
    sid     = "S3Documents"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${var.name_prefix}-documents",
      "arn:aws:s3:::${var.name_prefix}-documents/*",
    ]
  }

  statement {
    sid     = "RdsIamAuth"
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:aws:rds-db:${var.aws_region}:${local.account_id}:dbuser:${local.rds_resource_id}/rag_api",
    ]
  }
}

data "aws_iam_policy_document" "litellm" {
  statement {
    sid    = "BedrockInvoke"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      # Wildcard region required: cross-region inference profiles (au., apac.) route
      # requests to target regions (e.g. ap-southeast-4) chosen by Bedrock at invocation time.
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:${var.aws_region}:${local.account_id}:inference-profile/*",
    ]
  }

  statement {
    sid     = "SecretsManagerDbUrl"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [local.litellm_secret_arn]
  }
}

data "aws_iam_policy_document" "ingestion" {
  statement {
    sid     = "BedrockEmbeddings"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"]
  }

  statement {
    sid     = "S3Documents"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${var.name_prefix}-documents",
      "arn:aws:s3:::${var.name_prefix}-documents/*",
    ]
  }

  statement {
    sid     = "RdsIamAuth"
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:aws:rds-db:${var.aws_region}:${local.account_id}:dbuser:${local.rds_resource_id}/ingestion",
    ]
  }

  statement {
    sid    = "Textract"
    effect = "Allow"
    actions = [
      "textract:DetectDocumentText",
      "textract:StartDocumentTextDetection",
      "textract:GetDocumentTextDetection",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "vllm" {
  statement {
    sid     = "S3ModelWeights"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.models.arn,
      "${aws_s3_bucket.models.arn}/*",
    ]
  }
}

# ── S3 buckets ────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "models" {
  bucket = "${var.name_prefix}-models"
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "models" {
  bucket = aws_s3_bucket.models.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "models" {
  bucket = aws_s3_bucket.models.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "models" {
  bucket                  = aws_s3_bucket.models.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
