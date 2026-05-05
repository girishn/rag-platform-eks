# ADR-002: LiteLLM as Dual-Provider LLM Router (Bedrock Primary, vLLM Fallback)

**Date:** 2026-05-04
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

The platform needs to serve LLM inference to multiple tenants with different cost profiles and
availability requirements. Two backends are available: AWS Bedrock (managed, pay-per-token, subject
to service quotas) and a self-hosted vLLM cluster on EKS GPU nodes (fixed cost, full control).

We need a routing layer that can:
- Present a single OpenAI-compatible API surface to upstream callers
- Automatically failover from Bedrock to vLLM when Bedrock is throttled or unavailable
- Enforce per-tenant budget caps and RPM limits
- Track token spend per tenant for cost allocation

## Decision

Use LiteLLM Proxy as the unified LLM routing layer, deployed as a Kubernetes Deployment.
Bedrock (Claude 3.5 Sonnet) is the primary model group. vLLM (Llama 3.1 8B) is the fallback.
All routing config lives in a ConfigMap-mounted `config.yaml`. Virtual keys enforce per-tenant
budget and rate limits.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| LiteLLM Proxy | OpenAI-compatible, built-in fallback chains, virtual keys, spend tracking, active OSS project | Additional network hop; config complexity grows with tenant count |
| Custom FastAPI router | Full control, no extra dependency | Must re-implement retry logic, spend tracking, key management — significant ongoing maintenance |
| AWS Bedrock only (no fallback) | Simplest architecture | Single point of failure; quota exhaustion has no mitigation; no cost for idle GPU nodes |
| OpenRouter (external) | No self-hosting | Sends all prompts to a third party; not viable for enterprise data isolation requirements |

## Consequences

**Easier:**
- Adding new LLM providers (Anthropic direct, OpenAI, Azure) is a config change, not a code change.
- **Swapping primary and fallback** (e.g. promoting vLLM to primary when Bedrock costs are too high,
  or during a Bedrock outage) is also a config change — edit `helm/litellm/config.yaml`, run
  `helm upgrade`, pods roll. No application code changes anywhere in the stack.
- Per-tenant cost allocation is built-in via `/spend/logs`.
- Fallback logic is declarative and testable without changing application code.

**Harder:**
- LiteLLM adds a latency hop (~5–15ms) on every request.
- Config changes to `config.yaml` require a pod rollout to take effect.
- Budget exhaustion (429) must be handled differently from backend errors (5xx) — callers must
  distinguish these two failure modes. A 429 from LiteLLM does NOT trigger fallback to vLLM.

**Risks:**
- LiteLLM is an OSS project; breaking changes between minor versions have occurred historically.
  Pin the Helm chart image tag and test upgrades in a staging namespace before rolling to prod.

## References

- [LiteLLM routing docs](https://docs.litellm.ai/docs/routing)
- [LiteLLM virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [AWS Bedrock service quotas](https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html)
