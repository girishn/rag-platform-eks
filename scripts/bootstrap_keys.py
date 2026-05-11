#!/usr/bin/env -S uv run
"""Create per-tenant virtual keys in LiteLLM.

Idempotent: existing keys (tracked in infra/virtual-keys.json) are skipped.
Requires: cluster running, kubectl context pointing at rag-platform-cluster.

Usage:
    uv run scripts/bootstrap_keys.py
    uv run scripts/bootstrap_keys.py --litellm-url http://localhost:4000  # skip port-forward
"""
import argparse
import base64
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

NAMESPACE = "rag-platform"
LOCAL_PORT = 4000
KEYS_FILE = Path(__file__).parent.parent / "infra" / "virtual-keys.json"

# Dev tenants — add entries here when onboarding new tenants.
# tenant_id maps to the pgvector schema name: tenant_{tenant_id}
TENANTS: list[dict] = [
    {
        "tenant_id": "acme",
        "alias": "dev-acme",
        "max_budget": 10.0,
        "budget_duration": "30d",
    },
    {
        "tenant_id": "globex",
        "alias": "dev-globex",
        "max_budget": 10.0,
        "budget_duration": "30d",
    },
]


def get_master_key() -> str:
    result = subprocess.run(
        [
            "kubectl", "get", "secret", "litellm-env",
            "-n", NAMESPACE,
            "-o", "jsonpath={.data.PROXY_MASTER_KEY}",
        ],
        capture_output=True, check=True, text=True,
    )
    return base64.b64decode(result.stdout.strip()).decode()


def start_port_forward() -> subprocess.Popen:  # type: ignore[type-arg]
    proc = subprocess.Popen(
        ["kubectl", "port-forward", "svc/litellm", f"{LOCAL_PORT}:4000", "-n", NAMESPACE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait until the port accepts connections (up to 15s)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            httpx.get(f"http://localhost:{LOCAL_PORT}/health/liveliness", timeout=1)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    print("Error: LiteLLM port-forward did not become ready within 15s.", file=sys.stderr)
    sys.exit(1)


def load_existing_keys() -> dict[str, str]:
    """Return {alias: key} from local state file."""
    if KEYS_FILE.exists():
        data: dict[str, str] = json.loads(KEYS_FILE.read_text())
        return data
    return {}


def save_keys(keys: dict[str, str]) -> None:
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps(keys, indent=2))


def create_key(client: httpx.Client, master_key: str, tenant: dict) -> str:
    resp = client.post(
        "/key/generate",
        headers={"Authorization": f"Bearer {master_key}"},
        json={
            "key_alias": tenant["alias"],
            "max_budget": tenant["max_budget"],
            "budget_duration": tenant["budget_duration"],
            "metadata": {"tenant_id": tenant["tenant_id"]},
            "models": ["claude-sonnet", "llama-3-1-8b"],
        },
        timeout=15,
    )
    resp.raise_for_status()
    return str(resp.json()["key"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap LiteLLM virtual keys for dev tenants.")
    parser.add_argument(
        "--litellm-url",
        default=None,
        help="LiteLLM base URL. If omitted, port-forward is started automatically.",
    )
    args = parser.parse_args()

    master_key = get_master_key()
    print(f"Master key retrieved from k8s secret litellm-env")

    pf_proc = None
    if args.litellm_url:
        base_url = args.litellm_url.rstrip("/")
    else:
        print("Starting kubectl port-forward svc/litellm 4000:4000 ...")
        pf_proc = start_port_forward()
        base_url = f"http://localhost:{LOCAL_PORT}"
        print(f"Port-forward ready at {base_url}")

    existing = load_existing_keys()

    try:
        with httpx.Client(base_url=base_url) as client:
            for tenant in TENANTS:
                alias = tenant["alias"]
                if alias in existing:
                    print(f"  {alias}: already exists — skipping")
                    continue
                key = create_key(client, master_key, tenant)
                existing[alias] = key
                print(f"  {alias}: created  key={key[:12]}...")

        save_keys(existing)
        print(f"\nKeys saved to {KEYS_FILE}")
        print("\n--- Virtual Keys (store securely) ---")
        for alias, key in existing.items():
            print(f"  {alias}: {key}")

    finally:
        if pf_proc is not None:
            pf_proc.terminate()


if __name__ == "__main__":
    main()
