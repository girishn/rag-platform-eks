# Runbook: pgvector Slow Queries and HNSW Index Degradation

## Symptoms
- RAG API `/metrics` shows `retrieval_latency_seconds_p99 > 500ms`
- Grafana retrieval latency panel trending upward over days (gradual degradation)
- Postgres `pg_stat_activity` shows long-running `SELECT ... ORDER BY embedding <=>` queries
- Connection pool exhaustion: RAG API logs `asyncpg: too many connections`

## Likely cause
Most common: HNSW index not being used (sequential scan fallback), connection pool exhausted
by slow queries holding connections, or `ef_search` too high for the latency budget.

## Investigation steps

1. Confirm index is being used (run via `psql` or RDS Query Editor):
   ```sql
   SET search_path = tenant_alpha;
   EXPLAIN ANALYZE
   SELECT chunk_id, chunk_text, 1 - (embedding <=> '[0.1, 0.2, ...]'::vector) AS similarity
   FROM embeddings
   ORDER BY embedding <=> '[0.1, 0.2, ...]'::vector
   LIMIT 5;
   -- Look for "Index Scan using embeddings_hnsw_idx" — if you see "Seq Scan", the index is broken
   ```

2. Check index build status and bloat:
   ```sql
   SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_analyze
   FROM pg_stat_user_tables
   WHERE relname = 'embeddings';
   ```

3. Check current `ef_search` setting:
   ```sql
   SHOW hnsw.ef_search;
   -- Default is 40; higher = better recall but slower queries
   ```

4. Check active connections and pool utilisation:
   ```sql
   SELECT count(*), state, wait_event_type, wait_event
   FROM pg_stat_activity
   WHERE datname = 'ragplatform'
   GROUP BY state, wait_event_type, wait_event;
   ```

5. Check for lock contention (ingestion holding locks during bulk upsert):
   ```sql
   SELECT pid, query, state, wait_event, pg_blocking_pids(pid) AS blocked_by
   FROM pg_stat_activity
   WHERE cardinality(pg_blocking_pids(pid)) > 0;
   ```

## Resolution

**Index not being used (sequential scan):**
- Run `ANALYZE tenant_schema.embeddings` — planner stats may be stale after bulk ingestion
- Verify `vector_dims` in the index matches the actual embedding dimension:
  `\d tenant_schema.embeddings` — check the `embedding` column type
- If dimension mismatch after embedding model change: `REINDEX INDEX CONCURRENTLY embeddings_hnsw_idx`

**Slow queries but index is used:**
- Lower `ef_search` for a latency/recall tradeoff: `SET hnsw.ef_search = 20`
  (measure recall degradation with a held-out test set before making permanent)
- Tune at session level in the RAG API connection setup, not globally

**Connection pool exhaustion:**
- Reduce RAG API `DB_POOL_MAX_SIZE` from 20 → 10 per pod, or scale down replica count
- Deploy PgBouncer as a connection pooler sidecar if connection count exceeds RDS limits
- Check for connection leaks: `pg_stat_activity` rows with `state=idle` held for >60s

## Prevention
- Run `VACUUM ANALYZE` on `embeddings` table after large ingestion batches (add to CronJob)
- Set `statement_timeout = 2000` (2s) on the RAG API DB user to prevent runaway queries from
  holding connections
- Alert on `retrieval_latency_seconds_p95 > 300ms` before it reaches user-visible degradation
