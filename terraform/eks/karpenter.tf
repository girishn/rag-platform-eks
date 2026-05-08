# ── Karpenter IAM + SQS ──────────────────────────────────────────────────────

module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.0"

  cluster_name = module.eks.cluster_name

  # Pod Identity (not IRSA) — matches platform-wide convention
  enable_pod_identity             = true
  create_pod_identity_association = true

  # Spot interruption handling via SQS
  enable_spot_termination = true
  queue_name              = "${var.name_prefix}-karpenter"

  tags = var.tags
}

# ── Karpenter Helm release ────────────────────────────────────────────────────

resource "helm_release" "karpenter" {
  namespace        = "kube-system"
  name             = "karpenter"
  repository       = "oci://public.ecr.aws/karpenter"
  chart            = "karpenter"
  version          = "1.3.3"
  create_namespace = false
  wait             = true
  wait_for_jobs    = true
  timeout          = 300

  values = [
    yamlencode({
      settings = {
        clusterName       = module.eks.cluster_name
        interruptionQueue = module.karpenter.queue_name
      }
      controller = {
        resources = {
          requests = { cpu = "100m", memory = "256Mi" }
          limits   = { memory = "512Mi" }
        }
      }
    })
  ]

  depends_on = [module.eks, module.karpenter]
}

# ── EC2NodeClass — CPU (AL2023) ───────────────────────────────────────────────

resource "kubectl_manifest" "karpenter_node_class_cpu" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata = { name = "cpu-al2023" }
    spec = {
      amiSelectorTerms = [{ alias = "al2023@latest" }]
      role             = module.karpenter.node_iam_role_name
      subnetSelectorTerms = [{
        tags = { "karpenter.sh/discovery" = module.eks.cluster_name }
      }]
      securityGroupSelectorTerms = [{
        tags = { "karpenter.sh/discovery" = module.eks.cluster_name }
      }]
      tags = var.tags
    }
  })

  depends_on = [helm_release.karpenter]
}

# ── NodePool — CPU ────────────────────────────────────────────────────────────

resource "kubectl_manifest" "karpenter_node_pool_cpu" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "cpu" }
    spec = {
      template = {
        spec = {
          nodeClassRef = {
            group = "karpenter.k8s.aws"
            kind  = "EC2NodeClass"
            name  = "cpu-al2023"
          }
          requirements = [
            { key = "kubernetes.io/arch", operator = "In", values = ["amd64"] },
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["spot", "on-demand"] },
            {
              key      = "node.kubernetes.io/instance-type"
              operator = "In"
              values   = ["m5.large", "m5.xlarge", "m5.2xlarge", "m5a.large", "m5a.xlarge", "m5a.2xlarge"]
            },
          ]
        }
      }
      limits = { cpu = "100", memory = "400Gi" }
      disruption = {
        consolidationPolicy = "WhenEmptyOrUnderutilized"
        consolidateAfter    = "1m"
      }
    }
  })

  depends_on = [kubectl_manifest.karpenter_node_class_cpu]
}

# ── EC2NodeClass — GPU (Bottlerocket Accelerated) ─────────────────────────────
# Karpenter auto-selects the Bottlerocket NVIDIA variant for GPU instance types.

resource "kubectl_manifest" "karpenter_node_class_gpu" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.k8s.aws/v1"
    kind       = "EC2NodeClass"
    metadata   = { name = "gpu-bottlerocket" }
    spec = {
      amiSelectorTerms = [{ alias = "bottlerocket@latest" }]
      role             = module.karpenter.node_iam_role_name
      subnetSelectorTerms = [{
        tags = { "karpenter.sh/discovery" = module.eks.cluster_name }
      }]
      securityGroupSelectorTerms = [{
        tags = { "karpenter.sh/discovery" = module.eks.cluster_name }
      }]
      tags = var.tags
    }
  })

  depends_on = [helm_release.karpenter]
}

# ── NodePool — GPU ────────────────────────────────────────────────────────────

resource "kubectl_manifest" "karpenter_node_pool_gpu" {
  yaml_body = yamlencode({
    apiVersion = "karpenter.sh/v1"
    kind       = "NodePool"
    metadata   = { name = "gpu" }
    spec = {
      template = {
        metadata = {
          labels = { "nvidia.com/gpu" = "true" }
        }
        spec = {
          nodeClassRef = {
            group = "karpenter.k8s.aws"
            kind  = "EC2NodeClass"
            name  = "gpu-bottlerocket"
          }
          requirements = [
            { key = "kubernetes.io/arch", operator = "In", values = ["amd64"] },
            { key = "karpenter.sh/capacity-type", operator = "In", values = ["spot", "on-demand"] },
            {
              key      = "node.kubernetes.io/instance-type"
              operator = "In"
              values   = ["g5.xlarge", "g5.2xlarge", "g5.4xlarge"]
            },
          ]
          taints = [{
            key    = "nvidia.com/gpu"
            value  = "true"
            effect = "NoSchedule"
          }]
        }
      }
      limits = {
        cpu              = "64"
        memory           = "256Gi"
        "nvidia.com/gpu" = "8"
      }
      disruption = {
        consolidationPolicy = "WhenEmpty"
        consolidateAfter    = "5m"
      }
    }
  })

  depends_on = [kubectl_manifest.karpenter_node_class_gpu]
}
