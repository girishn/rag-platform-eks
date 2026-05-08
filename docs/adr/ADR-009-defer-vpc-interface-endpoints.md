# ADR-009: Defer VPC Interface Endpoints to Production

**Date:** 2026-05-08
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

ADR-008 specified VPC Interface Endpoints for Bedrock, ECR, STS, CloudWatch, SSM, KMS, and
Secrets Manager as part of the network defense-in-depth strategy. The intent was to keep all
AWS API traffic inside the VPC, eliminating NAT Gateway as a path for credential exfiltration
or data exfiltration via AWS APIs.

When implemented, 10 interface endpoints were provisioned across 3 Availability Zones.
The actual cost was $0.013/AZ-hour per endpoint:

- 10 endpoints × 3 AZs × $0.013/hr × 720 hrs = **~$281/month**

At portfolio/development load, this exceeds the NAT Gateway data transfer charges these endpoints
would replace. The breakeven point — where endpoint hourly fees are outweighed by eliminated NAT
data transfer costs — requires sustained high-volume traffic to AWS APIs (roughly >1TB/month
through NAT, or heavy ECR pull volume).

## Decision

Remove VPC Interface Endpoints from the dev environment. Retain only the S3 Gateway endpoint
(free, eliminates S3 NAT egress charges entirely).

Re-add interface endpoints in production when traffic volume justifies the fee. Priority order
when adding back:

1. `ecr.dkr` + `ecr.api` — high-volume on node scale-up (image pulls bypass NAT)
2. `bedrock-runtime` — LLM inference traffic stays inside VPC
3. `secretsmanager` + `sts` — credential path hardening
4. Remaining (`logs`, `monitoring`, `kms`, `ssm`, `ssmmessages`) — lower priority

## Options considered

| Option | Pros | Cons |
|---|---|---|
| Keep all 10 endpoints (ADR-008 intent) | Strongest network isolation | $281/month fixed cost regardless of load |
| Remove all endpoints including S3 | Simplest, cheapest | S3 Gateway is free — no reason to remove it |
| Keep only highest-value endpoints | Balanced | Partial isolation is harder to reason about |
| **Defer all interface endpoints to prod** | $0 cost in dev, full control when justified | AWS API traffic exits via NAT in dev |

## Consequences

- Dev environment saves ~$281/month
- AWS API calls (Bedrock, ECR, Secrets Manager) route via NAT Gateway in dev
- NAT Gateway data charges will apply for ECR image pulls and Bedrock API calls
- ADR-008 network isolation goals are preserved for production; dev is explicitly a lower-security tier
- S3 Gateway endpoint retained — free and eliminates S3 NAT egress

## References

- ADR-008: Network security and defense-in-depth strategy (partially superseded for dev)
- AWS VPC endpoint pricing: $0.013/AZ-hour for interface endpoints in ap-southeast-2
