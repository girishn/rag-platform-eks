# ADR-005: vLLM over SageMaker or Triton for Self-Hosted GPU Inference

**Date:** 2026-05-04
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

The platform requires a self-hosted LLM inference backend to serve as a fallback when Bedrock
is throttled and as a cost-reduction path for high-volume tenants. The model is Llama 3.1 8B,
running on GPU nodes (g5 family, A10G) within the EKS cluster. The serving layer must expose an
OpenAI-compatible `/v1/chat/completions` endpoint so LiteLLM can route to it without code changes.

## Decision

Deploy vLLM on EKS GPU nodes using the AWS Deep Learning Container (DLC) image.
Model weights are stored in S3 and pulled at pod start by an init container.
KEDA scales the vLLM Deployment based on `vllm:num_requests_waiting` queue depth.
Tensor parallelism is controlled via environment variable (`--tensor-parallel-size`).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| vLLM on EKS | OpenAI-compatible API; PagedAttention maximises A10G VRAM utilisation; active development; native Prometheus metrics; runs anywhere with a GPU | Must manage GPU node lifecycle, CUDA dependencies, and model weight distribution |
| AWS SageMaker real-time inference | Fully managed; auto-scaling; no GPU node management | Not on EKS — separate data plane; higher per-hour cost than spot GPU nodes; proprietary invocation API (not OpenAI-compatible without adapter) |
| NVIDIA Triton Inference Server | High throughput for multi-model serving | More complex config (model repository, backend selection); less LLM-optimised than vLLM for autoregressive generation |
| Ollama | Simple local dev setup | Not designed for multi-user production serving; no PagedAttention; limited concurrency |

## Consequences

**Easier:**
- LiteLLM routes to vLLM using the same OpenAI-compatible client — no code changes in the router.
- `vllm:num_requests_waiting` is a directly observable scale signal that maps to actual user
  wait time, making KEDA scaling semantically meaningful.
- Scale-to-zero on GPU nodes eliminates idle GPU cost entirely during off-peak hours.
- Changing the model is an S3 upload + env var change — no image rebuild required.

**Harder:**
- GPU node provisioning (Karpenter) takes 2–4 minutes on a cold start — users experience
  elevated latency on the first request after scale-from-zero. Mitigate with a minimum replica
  of 1 during business hours via KEDA schedule.
- Model weights (~16GB for 8B in fp16) must download from S3 at pod start, adding 3–5 minutes
  to cold start. Use S3 Transfer Acceleration or a warmed PVC where possible.

**Risks:**
- vLLM's CUDA and Python dependencies are tightly versioned. Use the AWS DLC image
  (`763104351884.dkr.ecr.ap-southeast-2.amazonaws.com/vllm-inference:latest`) — it is tested
  on the A10G and keeps CUDA/cuDNN aligned. Do not build a custom base image.

## References

- [vLLM PagedAttention paper](https://arxiv.org/abs/2309.06180)
- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)
- [AWS DLC vLLM image](https://github.com/aws/deep-learning-containers)
- [KEDA Prometheus scaler](https://keda.sh/docs/2.13/scalers/prometheus/)
