# Runbook: LiteLLM Fallback Triggered — Diagnosing Which Backend is Serving

## Symptoms
- Grafana `fallback_events_total` counter non-zero
- Response latency increased (vLLM cold path adds ~500ms vs Bedrock)
- Users reporting different response style (Llama 3.1 8B vs Claude 3.5 Sonnet)
- Alert: `fallback_events_total rate > 0.1/min for 5 minutes`

## Likely cause
Bedrock ThrottlingException (quota exhaustion) or transient Bedrock service error triggering
the automatic fallback chain to vLLM. Could also indicate misconfiguration if fallback fires
at unexpected times.

## Investigation steps

1. Identify which backend is currently serving requests:
   ```bash
   kubectl logs -n rag-platform -l app=litellm --since=5m \
     | grep -E '"model"|"backend"|fallback|ThrottlingException' | tail -30
   ```

2. Check LiteLLM spend logs to see backend split in real time:
   ```bash
   # Port-forward to LiteLLM admin port
   kubectl port-forward -n rag-platform svc/litellm 4000:4000
   curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
     http://localhost:4000/spend/logs?limit=20 | jq '.[].model'
   ```

3. Verify Bedrock is actually throttling (not a LiteLLM config issue):
   ```bash
   # Check AWS Bedrock throttle metric
   aws cloudwatch get-metric-statistics \
     --namespace AWS/Bedrock \
     --metric-name InvocationsThrottled \
     --dimensions Name=ModelId,Value=anthropic.claude-3-5-sonnet-20241022-v2:0 \
     --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
     --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
     --period 60 --statistics Sum --region ap-southeast-2
   ```

4. Distinguish fallback from budget exhaustion:
   ```bash
   kubectl logs -n rag-platform -l app=litellm --since=5m \
     | grep -c "Budget"      # budget 429 — fallback NOT triggered
   kubectl logs -n rag-platform -l app=litellm --since=5m \
     | grep -c "fallback"    # real fallback to vLLM
   ```

5. Confirm vLLM is healthy and serving fallback traffic:
   ```bash
   kubectl get pods -n rag-platform -l app=vllm
   kubectl logs -n rag-platform -l app=vllm --since=5m | grep -E "request|error" | tail -20
   curl -s http://vllm-service.rag-platform.svc.cluster.local:8000/metrics \
     | grep "vllm:num_requests_running"
   ```

6. Check LiteLLM routing config is correct (fallback model must match vLLM deployment name):
   ```bash
   kubectl get configmap -n rag-platform litellm-config -o jsonpath='{.data.config\.yaml}' \
     | grep -A 10 fallbacks
   ```

## Resolution

**Fallback is healthy and this is expected behaviour:**
- No action required — fallback is working as designed
- File a Bedrock quota increase if throttling is sustained (see bedrock-quota-exhausted runbook)
- Monitor `fallback_events_total` for normalisation once Bedrock quota resets

**Fallback triggered but vLLM is not serving (both backends down):**
- Users receive 503 — this is a P1
- Check vLLM pod status and GPU node health (see gpu-node-troubleshooting runbook)
- Check KEDA has not scaled vLLM to 0 pods unexpectedly:
  `kubectl get scaledobject -n rag-platform vllm-scaler`

**Fallback triggering unexpectedly (Bedrock not actually throttling):**
- Check LiteLLM `config.yaml` for incorrectly set `max_retries` or `timeout_s` values
  that might cause premature fallback on transient latency spikes
- Verify Bedrock model ID in config matches the deployed region/model alias

## Prevention
- Dashboard panel: display `backend=bedrock` vs `backend=vllm` as a stacked bar — makes
  fallback events immediately visible without reading logs
- Alert: `fallback_events_total rate > 1/min` for sustained fallback (not transient blip)
