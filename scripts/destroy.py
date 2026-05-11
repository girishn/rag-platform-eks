#!/usr/bin/env -S uv run
"""Tear down all Terraform modules in reverse dependency order, then remove helm releases."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

LITELLM_SECRET_NAME = "rag-platform-litellm-db-url"

REGION = "ap-southeast-2"
TF_ROOT = Path(__file__).parent.parent / "terraform"

# Destroyed in reverse provision order — addons first, eks last.
MODULES = ["addons", "iam", "elasticache", "rds", "eks"]


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd, check=False)
    if result.returncode != 0:
        print(f"\nFailed: {' '.join(str(c) for c in cmd)}", file=sys.stderr)
        sys.exit(result.returncode)


def bootstrap_outputs() -> dict[str, str]:
    result = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=TF_ROOT / "bootstrap",
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(
            "Bootstrap outputs unavailable — cannot determine state bucket.\n"
            "If the bucket still exists, check: cd terraform/bootstrap && terraform output",
            file=sys.stderr,
        )
        sys.exit(1)
    raw: dict[str, dict[str, str]] = json.loads(result.stdout)
    return {k: v["value"] for k, v in raw.items()}


def backend_args(env: str, module: str, bucket: str, table: str) -> list[str]:
    return [
        f"-backend-config=bucket={bucket}",
        f"-backend-config=key={env}/{module}/terraform.tfstate",
        f"-backend-config=region={REGION}",
        f"-backend-config=dynamodb_table={table}",
        f"-backend-config=encrypt=true",
    ]


def varfile_args(env: str) -> list[str]:
    varfile = TF_ROOT / "environments" / f"{env}.tfvars"
    if varfile.exists():
        return [f"-var-file={varfile}"]
    return []


def destroy_module(module: str, env: str, bucket: str, table: str) -> None:
    module_dir = TF_ROOT / module
    if not module_dir.exists() or not list(module_dir.glob("*.tf")):
        print(f"\n--- {module}: skipping (no .tf files) ---")
        return

    print(f"\n--- {module} ---")
    run(
        ["terraform", "init", "-reconfigure"] + backend_args(env, module, bucket, table),
        cwd=module_dir,
    )
    run(
        ["terraform", "destroy", "-auto-approve"] + varfile_args(env),
        cwd=module_dir,
    )


def delete_litellm_db_secret() -> None:
    """Delete the litellm DATABASE_URL secret before IAM destroy removes the role that owned it."""
    print(f"\n--- litellm DATABASE_URL secret ---")
    check = subprocess.run(
        ["aws", "secretsmanager", "describe-secret", "--secret-id", LITELLM_SECRET_NAME, "--region", REGION],
        capture_output=True,
    )
    if check.returncode != 0:
        print(f"  {LITELLM_SECRET_NAME} not found — skipping")
        return
    run([
        "aws", "secretsmanager", "delete-secret",
        "--secret-id", LITELLM_SECRET_NAME,
        "--force-delete-without-recovery",
        "--region", REGION,
    ])
    print(f"  Deleted: {LITELLM_SECRET_NAME}")


def teardown_k8s_secrets() -> None:
    """Delete k8s Secrets and namespace created by bootstrap_k8s_secrets in provision.py."""
    print("\n--- k8s litellm secrets + namespace ---")
    for secret in ("litellm-db-url-sync", "litellm-env"):
        subprocess.run(
            ["kubectl", "delete", "secret", secret, "--namespace", "rag-platform",
             "--ignore-not-found"],
            check=False,
        )
    subprocess.run(
        ["kubectl", "delete", "secretproviderclass", "litellm-db-url",
         "--namespace", "rag-platform", "--ignore-not-found"],
        check=False,
    )
    subprocess.run(
        ["kubectl", "delete", "namespace", "rag-platform", "--ignore-not-found"],
        check=False,
    )
    print("  Done")


def helm_uninstalls(env: str) -> None:
    print("\n--- helm uninstalls ---")
    k8s_root = Path(__file__).parent.parent / "k8s"

    subprocess.run(
        ["kubectl", "delete", "-f", str(k8s_root / "keda" / "vllm-scaledobject.yaml"),
         "--ignore-not-found"],
        check=False,
    )
    for release in ("litellm", "vllm"):
        result = subprocess.run(
            ["helm", "uninstall", release, "--namespace", "rag-platform"],
            capture_output=True, text=True,
        )
        if result.returncode != 0 and "not found" not in result.stderr.lower():
            print(f"\nFailed: helm uninstall {release}\n{result.stderr}", file=sys.stderr)
            sys.exit(result.returncode)
    print("  Done")


def destroy_bootstrap() -> None:
    bootstrap_dir = TF_ROOT / "bootstrap"
    print("\n--- bootstrap (S3 bucket + DynamoDB lock table) ---")
    run(["terraform", "init"], cwd=bootstrap_dir)
    run(["terraform", "destroy", "-auto-approve"], cwd=bootstrap_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tear down RAG platform on EKS.")
    parser.add_argument(
        "--env",
        required=True,
        choices=["dev", "prod"],
        help="Environment to destroy (drives var-file and state key prefix)",
    )
    parser.add_argument(
        "--include-bootstrap",
        action="store_true",
        help="Also destroy the S3 state bucket and DynamoDB lock table (irreversible)",
    )
    args = parser.parse_args()

    outputs = bootstrap_outputs()
    bucket = outputs.get("state_bucket_name", "")
    table = outputs.get("lock_table_name", "")
    if not bucket or not table:
        print(
            "Error: bootstrap did not output state_bucket_name or lock_table_name",
            file=sys.stderr,
        )
        sys.exit(1)

    helm_uninstalls(args.env)
    teardown_k8s_secrets()

    for module in MODULES:
        destroy_module(module, args.env, bucket, table)
        # Delete SM secret after IAM is gone — IAM module has a data source that reads
        # this secret ARN during refresh; deleting it earlier causes terraform destroy to fail.
        if module == "iam":
            delete_litellm_db_secret()

    if args.include_bootstrap:
        destroy_bootstrap()
    else:
        print(
            "\nBootstrap (S3 + DynamoDB) preserved. "
            "Re-run with --include-bootstrap to remove it."
        )

    print(f"\nDestroy complete (env={args.env}).")


if __name__ == "__main__":
    main()
