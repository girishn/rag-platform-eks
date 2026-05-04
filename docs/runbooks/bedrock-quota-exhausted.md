# Runbook: Bedrock Quota Exhaustion and Fallback Verification

## Symptoms
- LiteLLM returning 429 errors with `ThrottlingException` in logs
- Grafana `fallback_events_total` counter rising
- Users receiving higher latency than baseline (vLLM cold path is slower)
- `bedrock_requests_total{backend="bedrock"}` flat while `fallback_events_total` spikes

## Likely cause
AWS Bedrock service quota for `claude-3-5-sonnet` tokens-per-minute (TPM) or
requests-per-minute (RPM) exhausted. Bedrock quotas are per-account per-region.

## Investigation steps

1. Confirm fallback is triggering (not a LiteLLM budget 429):
   ```bash
   kubectl logs -n rag-platform -l app=litellm --since=5m | grep -E "fallback|ThrottlingException|429"
   # If you see "Budget exceeded" — this is a virtual key 429, fallback should NOT trigger
   # If you see "ThrottlingException" — this is a Bedrock quota, fallback SHOULD trigger
   ```

2. Check current Bedrock quota utilisation in CloudWatch:
   ```bash
   aws cloudwatch get-metric-statistics \
     --namespace AWS/Bedrock \
     --metric-name InvocationsThrottled \
     --dimensions Name=ModelId,Value=anthropic.claude-3-5-sonnet-20241022-v2:0 \
     --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
     --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
     --period 60 --statistics Sum \
     --region ap-southeast-2
   ```

3. Verify vLLM fallback is healthy:
   ```bash
   kubectl get pods -n rag-platform -l app=vllm
   curl -s http://vllm-service.rag-platform.svc.cluster.local:8000/health
   ```

4. Check LiteLLM routing config to confirm fallback chain is correctly defined:
   ```bash
   kubectl get configmap -n rag-platform litellm-config -o yaml | grep -A 20 fallbacks
   ```

5. Confirm budget exhaustion is NOT the cause (they look similar):
   ```bash
   kubectl logs -n rag-platform -l app=litellm --since=5m | grep -c "Budget"
   # If non-zero: some tenants hitting budget cap — this is expected behaviour, not an incident
   ```

## Resolution

**Immediate (quota exhaustion in progress):**
- Fallback to vLLM is automatic — verify it is serving correctly (step 3 above)
- If vLLM is also degraded, file a P1 and notify users of degraded service
- Request a Bedrock quota increase via AWS console: Service Quotas → Bedrock → RPM/TPM

**Short-term:**
- Implement Bedrock Provisioned Throughput for predictable high-volume tenants:
  PTUs guarantee quota and reduce per-token cost at scale (break-even ~50K tokens/day)
- Review LiteLLM `max_retries` config — excessive retries amplify throttling

**Medium-term:**
- Add a per-tenant RPM limit in LiteLLM virtual keys to prevent single tenants from exhausting
  the shared Bedrock quota

## Prevention
- Alert on `InvocationsThrottled > 10 per minute` in CloudWatch → triggers before users notice
- Monitor `fallback_events_total` in Grafana — a rising baseline (not spike) signals creeping quota pressure
