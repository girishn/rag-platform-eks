terraform {
  required_version = ">= 1.9"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.20"
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
  cluster_name      = data.terraform_remote_state.eks.outputs.cluster_name
  cluster_endpoint  = data.terraform_remote_state.eks.outputs.cluster_endpoint
  cluster_ca        = data.terraform_remote_state.eks.outputs.cluster_certificate_authority_data
  oidc_provider_arn = data.terraform_remote_state.eks.outputs.oidc_provider_arn
}

provider "helm" {
  kubernetes {
    host                   = local.cluster_endpoint
    cluster_ca_certificate = base64decode(local.cluster_ca)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", local.cluster_name, "--region", var.aws_region]
    }
  }
}

provider "kubernetes" {
  host                   = local.cluster_endpoint
  cluster_ca_certificate = base64decode(local.cluster_ca)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", local.cluster_name, "--region", var.aws_region]
  }
}

# ── EKS Blueprints Addons ─────────────────────────────────────────────────────

module "addons" {
  source  = "aws-ia/eks-blueprints-addons/aws"
  version = "~> 1.23"

  cluster_name      = local.cluster_name
  cluster_endpoint  = local.cluster_endpoint
  cluster_version   = "1.35"
  oidc_provider_arn = local.oidc_provider_arn

  enable_aws_gateway_api_controller = true
  enable_kube_prometheus_stack      = true
  enable_metrics_server             = true

  kube_prometheus_stack = {
    set = [
      {
        name  = "grafana.adminPassword"
        value = var.grafana_admin_password
      },
      {
        name  = "grafana.persistence.enabled"
        value = "false"
      },
    ]
  }

  helm_releases = {
    keda = {
      name             = "keda"
      repository       = "https://kedacore.github.io/charts"
      chart            = "keda"
      version          = "2.16.1"
      namespace        = "keda"
      create_namespace = true
    }
  }

  tags = var.tags
}

# ── Secrets Store CSI Driver ──────────────────────────────────────────────────
# Required for DATABASE_URL injection from Secrets Manager into LiteLLM pod.

resource "helm_release" "secrets_store_csi_driver" {
  name             = "secrets-store-csi-driver"
  repository       = "https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts"
  chart            = "secrets-store-csi-driver"
  version          = "1.4.7"
  namespace        = "kube-system"
  create_namespace = false
  wait             = true
  timeout          = 300

  set {
    name  = "syncSecret.enabled"
    value = "true"
  }
}

resource "helm_release" "secrets_store_csi_driver_provider_aws" {
  name             = "secrets-store-csi-driver-provider-aws"
  repository       = "https://aws.github.io/secrets-store-csi-driver-provider-aws"
  chart            = "secrets-store-csi-driver-provider-aws"
  version          = "0.3.11"
  namespace        = "kube-system"
  create_namespace = false
  wait             = true
  timeout          = 300

  depends_on = [helm_release.secrets_store_csi_driver]
}

# ── cert-manager ─────────────────────────────────────────────────────────────
# Required by ADOT (OpenTelemetry Operator) for webhook TLS certificate management.

resource "helm_release" "cert_manager" {
  name             = "cert-manager"
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = "v1.20.2"
  namespace        = "cert-manager"
  create_namespace = true
  wait             = true
  timeout          = 300

  set {
    name  = "crds.enabled"
    value = "true"
  }
}

# ── ADOT EKS managed add-on ───────────────────────────────────────────────────
# Deploys OpenTelemetry Operator. Collector configuration happens in Week 4.
# To find the latest version:
#   aws eks describe-addon-versions --kubernetes-version 1.35 --addon-name adot \
#     --query 'addons[0].addonVersions[0].addonVersion' --output text

resource "aws_eks_addon" "adot" {
  cluster_name                = local.cluster_name
  addon_name                  = "adot"
  addon_version               = var.adot_addon_version
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [helm_release.cert_manager]

  tags = var.tags
}
