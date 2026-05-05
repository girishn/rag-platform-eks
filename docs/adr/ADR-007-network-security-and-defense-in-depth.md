# ADR-007: Network Security and Defense-in-Depth Strategy

**Date:** 2026-05-05
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

The RAG platform handles private enterprise documents and routes them through LLM inference. A
breach of tenant data isolation or credential compromise would be high severity. Three concrete
risks drive this ADR:

1. **Internet exposure of VPC Lattice** — Early architecture diagrams implied application users
   hit VPC Lattice directly. VPC Lattice is a private, VPC-scoped service with no public endpoint.
   Exposing it to internet traffic is architecturally impossible; the gap was an unmodelled
   internet ingress path.

2. **AWS API traffic over NAT** — Without VPC endpoints, all pod calls to Bedrock, ECR, S3, STS,
   and CloudWatch egress through a NAT Gateway onto the public internet. This increases attack
   surface, adds per-GB NAT cost, and makes traffic invisible to VPC flow logs.

3. **Missing admin access path** — No mechanism for platform admins to reach internal tooling
   (Grafana, LiteLLM admin UI, kubectl) in a fully-private EKS cluster.

## Decision

Implement a layered security model across network, identity, and data planes:

**Layer 1 — Internet ingress via ALB → VPC Lattice (not VPC Lattice directly)**
An internet-facing Application Load Balancer in public subnets terminates TLS (certificate via ACM)
and forwards to the VPC Lattice service network. There is no path where ALB routes directly to pods
— VPC Lattice is always in the path for all external traffic. VPC Lattice handles east-west
service-to-service routing inside the cluster and applies IAM AuthPolicies on every route.

**Layer 2 — Admin access (two tiers)**

*Developer/single-operator tier (this project):*
The EKS cluster runs with **public + private endpoint** enabled (EKS default). The developer runs
`aws eks update-kubeconfig` from their laptop and accesses the API server directly over the internet
via IAM-authenticated kubeconfig. Access is controlled by EKS access entries (no aws-auth ConfigMap).
Grafana and LiteLLM admin UI are accessed via `kubectl port-forward` — no VPN, no bastion required.

*Enterprise hardening (documented as the production pattern):*
Set the EKS cluster to **private endpoint only**. Platform admins connect via **AWS Client VPN**
authenticated by IAM Identity Center (SSO). Once in the VPC, kubectl reaches the private API server
endpoint; Grafana and LiteLLM admin UI are reached via VPC Lattice with IAM AuthPolicy scoping.
This eliminates the public API endpoint attack surface and provides MFA + audit trail for all
admin sessions. No bastion host, no long-lived SSH keys.

**Layer 3 — VPC Interface/Gateway Endpoints (no NAT for AWS API calls)**
All pod-to-AWS-service traffic is routed via VPC endpoints:

| Service | Endpoint type | Purpose |
|---|---|---|
| Bedrock (`bedrock-runtime`) | Interface | LLM inference + embeddings |
| ECR (`ecr.api`, `ecr.dkr`) | Interface | Image pulls |
| S3 | Gateway | Document storage, model weights |
| STS | Interface | Pod Identity credential exchange |
| CloudWatch (`logs`, `monitoring`) | Interface | Metrics + traces |
| SSM (`ssm`, `ssmmessages`) | Interface | Secrets + admin access |
| KMS | Interface | Envelope decryption |

NAT Gateway is retained in public subnets for OS package updates and third-party calls only.

**Layer 4 — Kubernetes NetworkPolicies (default deny)**
Each application namespace has a `default-deny-all` NetworkPolicy. Explicit allow rules are
added only where required (rag-api → litellm, litellm → vllm, monitoring scrape paths).

**Layer 5 — Security Groups for Pods (AWS-level network segmentation)**
VPC CNI `ENABLE_POD_ENI=true`. Each workload type (rag-api, litellm, vllm, monitoring) has a
dedicated pod security group. RDS security group allows inbound 5432 only from the rag-api and
litellm pod security groups — not from the node security group.

**Layer 6 — Encryption at rest (KMS customer-managed keys)**
- EKS etcd secrets: KMS envelope encryption via the KMS secrets provider.
- RDS: KMS customer-managed key; `require_secure_transport = 1` parameter group.
- S3: SSE-KMS with customer-managed key; bucket policy denies non-TLS requests.
- EBS node volumes: AWS KMS encryption enabled account-wide by default.

**Layer 7 — Encryption in transit**
- External: TLS 1.2+ via ALB (ACM certificate). HTTP listeners redirect to HTTPS.
- RDS: `sslmode=require` in all application connection strings.
- S3: Bucket policy condition `aws:SecureTransport: true` denies all non-HTTPS calls.
- Bedrock, ECR, SSM, STS: TLS enforced by the VPC Interface Endpoint policy; AWS SDK defaults to HTTPS.
- Pod-to-pod (east-west): Application-layer HTTPS between RAG API, LiteLLM, and vLLM. Full mTLS
  (service mesh) is deferred — the complexity of running App Mesh or Istio is not justified at
  this scale, but the decision is revisited if the cluster expands beyond 3 application services.

**Layer 8 — Least privilege Pod Identity roles (one role per workload)**

| Workload | IAM role | Allowed actions |
|---|---|---|
| rag-api | `rag-api-role` | `bedrock:InvokeModel`, `s3:GetObject` (documents bucket), `ssm:GetParameter` (own prefix), `cloudwatch:PutMetricData` |
| ingestion | `ingestion-role` | `bedrock:InvokeModel` (Titan embed), `s3:GetObject`+`ListBucket` (raw docs bucket), RDS access via SG |
| litellm | `litellm-role` | `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`, `ssm:GetParameter` (own prefix) |
| vllm | `vllm-role` | `s3:GetObject` (model weights prefix only) |
| monitoring | `monitoring-role` | `cloudwatch:GetMetricData`, `cloudwatch:DescribeAlarms` |

**Layer 9 — Audit trail**
CloudTrail enabled in all regions (global + regional). Data events enabled for the RAG documents
S3 bucket. KMS key usage audited via CloudTrail. EKS control plane logging enabled
(`api`, `audit`, `authenticator`, `controllerManager`, `scheduler`).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| ALB → VPC Lattice (chosen) | Managed TLS termination; WAF-attachable; familiar ops model | Slight additional hop; ALB per-LCU cost |
| NLB → VPC Lattice | Lower latency; supports TLS passthrough | No WAF; no content-based routing at internet layer |
| Public endpoint + kubeconfig + kubectl port-forward (chosen for dev) | Zero setup; no VPN client; works for a single operator | API server exposed publicly (mitigated by IAM auth + EKS access entries); port-forward is per-session |
| Client VPN + IAM Identity Center (enterprise hardening) | Private endpoint only; MFA via IdP; stable internal URLs; full audit trail | Requires VPN client + additional infra cost; overkill for single operator |
| Bastion host + SSH | Simple | Long-lived SSH keys; EC2 to patch; no MFA by default |
| Full mTLS (Istio/App Mesh) | Zero-trust east-west; automatic cert rotation | Significant operational complexity; sidecar overhead; deferred |
| Single shared Pod Identity role | Less Terraform | Violates least privilege; blast radius of credential leak is full cluster |

## Consequences

**Easier:**
- All AWS API traffic is private and visible in VPC flow logs.
- Credential compromise of one workload's Pod Identity role is contained to that role's permissions.
- RDS is unreachable from any pod that does not have its security group — no network policy
  misconfiguration can bypass this.
- CloudTrail provides a complete audit trail for compliance reporting.

**Harder:**
- VPC endpoints add ~$7–9/month per AZ per Interface endpoint. At 3 AZs and 7 Interface endpoints,
  that is ~$150–190/month additional cost. Documented in cost model.
- Enterprise hardening (Client VPN + private endpoint) requires distributing VPN client config to admin workstations and adds ~$70/month for the VPN endpoint.
- Per-workload Pod Identity roles increase Terraform IAM surface area.
- Pod security groups require `ENABLE_POD_ENI=true` on VPC CNI, which reduces the number of pods
  per node (ENI limits). Plan node sizing accordingly.

**Risks:**
- Pod ENI limits on `m5.xlarge` (4 ENIs × 14 IPs = up to 54 pods, minus 2 reserved = 52 pods).
  GPU `g5.xlarge` (3 ENIs = 36 pods). Karpenter NodePool `maxPods` must be set to match.
- VPC endpoint policies default to allow all — add resource-based policies to Bedrock and S3
  endpoints to restrict access to specific IAM roles only.

## References

- [VPC Lattice is not internet-facing — AWS docs](https://docs.aws.amazon.com/vpc-lattice/latest/ug/how-it-works.html)
- [External connectivity to VPC Lattice — AWS blog](https://aws.amazon.com/blogs/networking-and-content-delivery/external-connectivity-to-amazon-vpc-lattice/)
- [EKS network security best practices](https://aws.github.io/aws-eks-best-practices/security/docs/network/)
- [Security Groups for Pods](https://docs.aws.amazon.com/eks/latest/userguide/security-groups-for-pods.html)
- [Bedrock VPC Interface Endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)
- [EKS encryption best practices](https://aws.github.io/aws-eks-best-practices/security/docs/data/)
- [Client VPN + IAM Identity Center](https://aws.amazon.com/blogs/security/how-to-configure-aws-client-vpn-with-aws-single-sign-on/)
