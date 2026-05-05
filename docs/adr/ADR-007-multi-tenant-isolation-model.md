# ADR-006: Three-Layer Tenant Isolation Model (Namespace + Schema + Virtual Key)

**Date:** 2026-05-04
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

The platform serves multiple independent tenants from a shared EKS cluster and shared RDS
instance. Tenants must not be able to access each other's documents, query history, or incur
cost against each other's budgets. The isolation model must be enforceable at the infrastructure
level, not just at the application layer.

## Decision

Each tenant is isolated across three layers:
1. **Kubernetes namespace** — compute isolation; NetworkPolicy restricts cross-tenant pod traffic.
2. **PostgreSQL schema** (`tenant_{id}`) — data isolation; `search_path` ensures queries only
   touch the owning tenant's tables.
3. **LiteLLM virtual key** — budget isolation; each key has `max_budget` and `rpm_limit`; spend
   is tracked per key and reported per tenant.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| Three-layer (namespace + schema + virtual key) | Defence in depth; each layer independently enforceable; clear audit trail per tenant | More provisioning steps per tenant; namespace proliferation at scale |
| Shared namespace, row-level security (RLS) in PostgreSQL | Fewer Kubernetes resources | RLS is harder to audit; a single misconfigured policy leaks data; no compute isolation |
| Separate EKS cluster per tenant | Strongest isolation | Cost-prohibitive; operationally unsustainable at >5 tenants |
| Shared namespace, application-layer enforcement only | Simplest | Weakest isolation; application bugs can cause cross-tenant data access |

## Consequences

**Easier:**
- Offboarding a tenant is a clean delete: drop the Kubernetes namespace, drop the PostgreSQL
  schema, revoke the virtual key. No row-level cleanup required.
- Audit queries (which tenant called what model, how much did they spend) are trivially answered
  from LiteLLM's spend logs filtered by virtual key.
- NetworkPolicy in the tenant namespace prevents a compromised pod from reaching other tenants'
  services.

**Harder:**
- Tenant provisioning requires coordination across three systems (Kubernetes, PostgreSQL, LiteLLM
  API). This must be automated — manual provisioning is error-prone.
- Kubernetes namespace count grows linearly with tenants. At >50 tenants, namespace-level
  resource quotas and LimitRanges add management overhead. Consider a higher-level abstraction
  (e.g. Capsule or HNC) at that scale.

**Risks:**
- The application must correctly set `search_path` on every database connection. A connection
  pool that leaks a session with the wrong `search_path` could expose another tenant's data.
  Enforce `search_path` at the connection string level, not via application code.

## References

- [PostgreSQL schema-based multi-tenancy](https://www.postgresql.org/docs/current/ddl-schemas.html)
- [LiteLLM virtual keys and budgets](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [Kubernetes NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [Capsule multi-tenancy operator](https://capsule.clastix.io/)
