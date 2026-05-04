# ADR-003: AWS Gateway API Controller (VPC Lattice) over Kong or Envoy Gateway

**Date:** 2026-05-04
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

The platform requires an ingress/routing layer for all external and inter-service HTTP traffic
into EKS. Kubernetes Ingress (NGINX) is being retired across the organisation in March 2026.
The replacement must implement the Kubernetes Gateway API spec (`gateway.networking.k8s.io/v1`)
and support per-tenant auth policies, traffic splitting for canary deployments, and TLS termination.

## Decision

Use the AWS Gateway API Controller, which provisions AWS VPC Lattice resources from Gateway API
objects. All external routing uses `HTTPRoute`. `GatewayClass` is `amazon-vpc-lattice`.
No Ingress NGINX, no Kong, no standalone Envoy deployment.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| AWS Gateway API Controller (VPC Lattice) | AWS-managed data plane (no pods to maintain), native IAM AuthPolicies, cross-VPC routing without VPN, Gateway API compliant | Newer service; some advanced HTTPRoute features still in preview; VPC Lattice per-request pricing |
| Kong Gateway (self-hosted) | Feature-rich, mature, large plugin ecosystem | Another stateful workload; custom CRDs diverge from Gateway API standard; operator overhead |
| Envoy Gateway | Gateway API compliant, CNCF project, flexible | Self-managed control plane and data plane pods; no AWS-native IAM integration |
| AWS Load Balancer Controller (ALB) | AWS-managed, well understood | Ingress-based (deprecated path); no native Gateway API support; ALB per-rule pricing |

## Consequences

**Easier:**
- Zero data-plane pods to manage — VPC Lattice is a fully managed AWS service.
- IAM-based `AuthPolicy` on `HTTPRoute` provides tenant isolation without a separate API gateway
  auth service.
- Traffic weight splits (canary) are declarative `HTTPRoute` config changes.

**Harder:**
- VPC Lattice is not available in all AWS regions — `ap-southeast-2` is supported.
- Debugging routing issues requires understanding both Kubernetes Gateway API events and
  VPC Lattice service network logs in CloudWatch.
- Not portable off AWS: `GatewayClass: amazon-vpc-lattice` is AWS-specific. A cloud-agnostic
  migration would need to swap the controller and GatewayClass only (HTTPRoute manifests are portable).

**Risks:**
- VPC Lattice pricing ($0.0025/LCU) can surprise at high request volume. Monitor via CloudWatch
  VPC Lattice metrics and set a billing alert.

## References

- [AWS Gateway API Controller docs](https://www.gateway-api-controller.eks.aws.dev/)
- [VPC Lattice pricing](https://aws.amazon.com/vpc/lattice/pricing/)
- [Gateway API spec v1](https://gateway-api.sigs.k8s.io/)
- [Kubernetes Ingress deprecation context](https://kubernetes.io/blog/2023/10/31/gateway-api-ga/)
