# Documentation Conventions

## ADR rules
- Write before implementing. Immutable once Accepted.
- Decision changes → new ADR + mark old as `Superseded by ADR-NNN`. Never edit Accepted ADRs.
- File: `docs/adr/ADR-NNN-short-slug.md`. Keep `docs/adr/README.md` current.

## ADR template
```markdown
# ADR-NNN: <Title>
**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Superseded by ADR-NNN
**Deciders:** Girish Narayanan

## Context
## Decision
## Options considered
| Option | Pros | Cons |
|---|---|---|
## Consequences
## References
```

## Architecture diagrams
- All Mermaid, in `docs/architecture/`. One concern per diagram.
- Prose description above each code block. `%%` comments for section labels.
- Use `flowchart LR` for internal service diagrams. Omit Prometheus scrape-back edges.
- Update affected diagram(s) in same PR as the code change.

## Runbook template
```markdown
# Runbook: <Title>
## Symptoms
## Likely cause
## Investigation steps
1. Exact command to run
2. What to look for
## Resolution
## Prevention
```

## Cost model (`docs/cost-model.md`)
Per-component cost table + baseline load assumption + optimisation levers.
Components: EKS cluster, GPU nodes, RDS, Bedrock tokens, S3, VPC Lattice, VPC endpoints.
