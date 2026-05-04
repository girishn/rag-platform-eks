# Runbook: GPU Node Provisioning and vLLM Pod Failures

## Symptoms
- vLLM pods stuck in `Pending` state for >5 minutes
- Karpenter not provisioning a new GPU node despite pending pod
- vLLM pod in `OOMKilled` state after apparent startup
- KEDA not scaling vLLM Deployment despite queue depth alert firing

## Likely cause
Most common: Karpenter NodePool instance type constraints too narrow (no `g5` capacity in AZ),
or vLLM pod requesting more GPU memory than available on the provisioned node.

## Investigation steps

1. Check pending pod events and resource requests:
   ```bash
   kubectl describe pod -n rag-platform -l app=vllm | grep -A 20 Events
   kubectl get pod -n rag-platform -l app=vllm -o jsonpath='{.items[0].spec.containers[0].resources}'
   ```

2. Check Karpenter logs for provisioning decision:
   ```bash
   kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --since=10m | grep -i "g5\|gpu\|provisioning\|error"
   ```

3. Verify NodePool GPU configuration:
   ```bash
   kubectl get nodepool gpu-nodepool -o yaml | grep -A 30 requirements
   ```

4. Check EC2 spot availability in ap-southeast-2 (if using spot):
   ```bash
   aws ec2 describe-spot-instance-requests --region ap-southeast-2 \
     --filters Name=status-code,Values=capacity-not-available \
     --query 'SpotInstanceRequests[*].{Type:LaunchSpecification.InstanceType,AZ:LaunchedAvailabilityZone}'
   ```

5. If node provisioned but pod still OOMKilled, check vLLM memory usage:
   ```bash
   kubectl logs -n rag-platform -l app=vllm --previous | tail -50
   # Look for: CUDA out of memory / torch.cuda.OutOfMemoryError
   ```

6. Check KEDA ScaledObject status:
   ```bash
   kubectl get scaledobject -n rag-platform vllm-scaler -o yaml | grep -A 10 status
   kubectl describe hpa -n rag-platform keda-hpa-vllm-scaler
   ```

## Resolution

**Karpenter not provisioning:**
- Verify `amiFamily: Bottlerocket` is set on the GPU NodePool (not AL2023 — it lacks NVIDIA drivers)
- Widen instance type constraints: add `g5.2xlarge` alongside `g5.xlarge` if single-AZ capacity is exhausted
- Check `karpenter.sh/do-not-disrupt` annotation is not set on an existing node blocking consolidation

**vLLM OOMKilled:**
- Reduce `--gpu-memory-utilization` from `0.90` to `0.80` in the vLLM Deployment env vars
- If running Llama 3.1 8B in fp16 on a single A10G (24GB VRAM), the model weights consume ~16GB
  leaving only 8GB for KV cache. Reduce `--max-model-len` to limit context window.

**KEDA not scaling:**
- Confirm Prometheus is scraping vLLM `/metrics` endpoint:
  `curl http://vllm-service.rag-platform.svc.cluster.local:8000/metrics | grep num_requests_waiting`
- Verify KEDA Prometheus scaler URL in ScaledObject matches Prometheus service address

## Prevention
- Set `minReplicas: 1` in ScaledObject during business hours using KEDA schedule to avoid
  cold-start delays for the first request after scale-from-zero.
- Add a `PodDisruptionBudget` with `minAvailable: 1` to prevent Karpenter from consolidating
  the only vLLM node while a request is in flight.
