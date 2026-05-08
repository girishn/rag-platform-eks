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
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = "~> 1.14"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
    }
  }
}

provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  load_config_file       = false
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs         = slice(data.aws_availability_zones.available.names, 0, 3)
  cluster_name = "${var.name_prefix}-cluster"
}

# ── VPC ──────────────────────────────────────────────────────────────────────

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.name_prefix}-vpc"
  cidr = var.vpc_cidr

  azs             = local.azs
  private_subnets = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i, az in local.azs : cidrsubnet(var.vpc_cidr, 4, i + 4)]

  enable_nat_gateway   = true
  single_nat_gateway   = var.single_nat_gateway
  enable_dns_hostnames = true
  enable_dns_support   = true

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
    "karpenter.sh/discovery"          = local.cluster_name
  }
  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }

  tags = var.tags
}

# ── EKS Cluster ──────────────────────────────────────────────────────────────

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.cluster_name
  cluster_version = "1.35"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  # Required for Karpenter to join nodes and for initial bootstrap
  enable_cluster_creator_admin_permissions = true

  # System managed node group — runs kube-system + karpenter controller
  eks_managed_node_groups = {
    system = {
      instance_types = ["m5.large"]
      ami_type       = "AL2023_x86_64_STANDARD"

      min_size     = 2
      max_size     = 4
      desired_size = 2

      labels = {
        "node.kubernetes.io/purpose" = "system"
      }

      tags = var.tags
    }
  }

  # Pinned add-on versions — check `aws eks describe-addon-versions --kubernetes-version 1.35`
  cluster_addons = {
    coredns = {
      addon_version = "v1.14.2-eksbuild.4"
    }
    kube-proxy = {
      addon_version = "v1.35.0-eksbuild.2"
    }
    vpc-cni = {
      addon_version            = "v1.19.3-eksbuild.1"
      service_account_role_arn = module.vpc_cni_irsa.iam_role_arn
    }
    aws-ebs-csi-driver = {
      addon_version            = "v1.59.0-eksbuild.1"
      service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
    }
    # Required for Pod Identity to work — must be present before any Pod Identity association is used
    eks-pod-identity-agent = {
      addon_version = "v1.3.10-eksbuild.3"
    }
  }

  tags = merge(var.tags, {
    "karpenter.sh/discovery" = local.cluster_name
  })
}

# ── VPC Endpoints — AWS API traffic stays inside VPC (ADR-008) ───────────────
# NAT Gateway handles only OS updates + third-party calls.

data "aws_security_group" "default" {
  vpc_id = module.vpc.vpc_id
  name   = "default"
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.name_prefix}-vpce"
  description = "Allow HTTPS from within the VPC to Interface endpoints"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [module.vpc.vpc_cidr_block]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpce" })
}

# S3 Gateway endpoint — free, eliminates S3 NAT charges
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpce-s3" })
}

locals {
  interface_endpoints = toset([
    "bedrock-runtime",
    "ecr.api",
    "ecr.dkr",
    "sts",
    "logs",
    "monitoring",
    "ssm",
    "ssmmessages",
    "kms",
    "secretsmanager",
  ])
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_endpoints

  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = module.vpc.private_subnets
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpce-${each.value}" })
}

# ── IRSA — VPC CNI (no Pod Identity support) ─────────────────────────────────

module "vpc_cni_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name_prefix      = "${var.name_prefix}-vpc-cni-"
  attach_vpc_cni_policy = true
  vpc_cni_enable_ipv4   = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:aws-node"]
    }
  }

  tags = var.tags
}

# ── IRSA — EBS CSI (no Pod Identity support) ──────────────────────────────────

module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name_prefix      = "${var.name_prefix}-ebs-csi-"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }

  tags = var.tags
}
