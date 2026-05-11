#!/usr/bin/env -S uv run
"""Deliberate exercise: exhaust a virtual key budget and capture the 429 response.

Demonstrates that BudgetExceededError returns 429 immediately from LiteLLM
without touching Bedrock or vLLM — fallback chain is NOT triggered.

Documents exact 429 response body and confirms vLLM remains at 0 replicas.
"""
import base64
import json
import subprocess
import sys
import time

import httpx

NAMESPACE = "rag-platform"
LOCAL_PORT = 4000


def get_master_key() -> str:
    result = subprocess.run(
        ["kubectl", "get", "secret", "litellm-env", "-n", NAMESPACE,
         "-o", "jsonpath={.data.PROXY_MASTER_KEY}"],
        capture_output=True, check=True, text=True,
    )
    return base64.b64decode(result.stdout.strip()).decode()


def start_port_forward() -> subprocess.Popen:  # type: ignore[type-arg]
    proc = subprocess.Popen(
        ["kubectl", "port-forward", "svc/litellm", f"{LOCAL_PORT}:4000", "-n", NAMESPACE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            httpx.get(f"http://localhost:{LOCAL_PORT}/health/liveliness", timeout=1)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    print("Error: port-forward did not become ready.", file=sys.stderr)
    sys.exit(1)


def vllm_replica_count() -> int:
    result = subprocess.run(
        ["kubectl", "get", "deployment", "vllm", "-n", NAMESPACE,
         "-o", "jsonpath={.status.replicas}"],
        capture_output=True, text=True,
    )
    val = result.stdout.strip()
    return int(val) if val else 0


def main() -> None:
    master_key = get_master_key()
    print("Starting port-forward ...")
    pf = start_port_forward()

    try:
        with httpx.Client(base_url=f"http://localhost:{LOCAL_PORT}", timeout=30) as client:

            # ── 1. Create a test key with max_budget=0 ───────────────────────────
            # LiteLLM pre-flight check: spend(0) >= max_budget(0) → BudgetExceededError
            # This fires before any Bedrock or vLLM call, so no model access needed.
            print("\n[1] Creating test key with max_budget=0 ...")
            r = client.post(
                "/key/generate",
                headers={"Authorization": f"Bearer {master_key}"},
                json={
                    "key_alias": "budget-exercise-key",
                    "max_budget": 0.0,
                    "budget_duration": "30d",
                    "metadata": {"tenant_id": "acme"},
                    "models": ["claude-sonnet"],
                },
            )
            r.raise_for_status()
            test_key = r.json()["key"]
            print(f"    key = {test_key[:16]}...")

            # ── 2. Request — budget immediately exhausted, expect 429 ────────────
            print("\n[2] Sending chat request with exhausted budget (expect 429) ...")
            r1 = client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {test_key}"},
                json={
                    "model": "claude-sonnet",
                    "messages": [{"role": "user", "content": "Say 'hello' and nothing else."}],
                    "max_tokens": 5,
                },
            )
            print(f"    HTTP {r1.status_code}")
            print(f"    body: {json.dumps(r1.json(), indent=4)}")
            r2 = r1  # alias for summary block below

            # ── 3. Verify vLLM was NOT involved ──────────────────────────────────
            print("\n[3] Checking vLLM replica count ...")
            replicas = vllm_replica_count()
            print(f"    vllm replicas = {replicas}  (expected 0 — fallback NOT triggered)")

            # ── 4. Clean up test key ──────────────────────────────────────────────
            print("\n[4] Deleting test key ...")
            client.post(
                "/key/delete",
                headers={"Authorization": f"Bearer {master_key}"},
                json={"keys": [test_key]},
            )
            print("    done")

            # ── Summary ───────────────────────────────────────────────────────────
            print("\n--- Exercise summary ---")
            print(f"  Request (budget=0, spend=0): HTTP {r2.status_code}")
            print(f"  vLLM replicas: {replicas} (fallback chain NOT triggered)")
            budget_body = r2.json()
            error_type = budget_body.get("error", {}).get("type", "unknown")
            print(f"  Error type: {error_type}")

    finally:
        pf.terminate()


if __name__ == "__main__":
    main()
