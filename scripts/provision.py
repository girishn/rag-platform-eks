#!/usr/bin/env -S uv run
"""Apply all Terraform modules in dependency order, then run helm installs."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REGION = "ap-southeast-2"
TF_ROOT = Path(__file__).parent.parent / "terraform"

# Applied in dependency order after bootstrap.
# elasticache and rds are independent; iam depends on eks cluster_name; addons depends on eks + iam.
MODULES = ["eks", "rds", "elasticache", "iam", "addons"]


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
            "Bootstrap outputs unavailable. Run bootstrap first:\n"
            "  cd terraform/bootstrap && terraform init && terraform apply",
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
    print(f"  (no environments/{env}.tfvars found — using module defaults)")
    return []


def apply_module(module: str, env: str, bucket: str, table: str) -> None:
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
        ["terraform", "apply", "-auto-approve"] + varfile_args(env),
        cwd=module_dir,
    )


def apply_bootstrap() -> None:
    bootstrap_dir = TF_ROOT / "bootstrap"
    print("\n--- bootstrap ---")
    run(["terraform", "init"], cwd=bootstrap_dir)
    run(["terraform", "apply", "-auto-approve"], cwd=bootstrap_dir)


def helm_installs(env: str) -> None:
    print("\n--- helm installs ---")
    # Add helm upgrade --install commands here as charts are built in Week 2-3.
    # Example pattern (uncomment when chart exists):
    #   run(["helm", "upgrade", "--install", "litellm", "helm/litellm",
    #        "--namespace", "rag-platform", "--create-namespace",
    #        "-f", f"helm/litellm/values-{env}.yaml"])
    print(f"  (no helm charts configured yet for env={env})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision RAG platform on EKS.")
    parser.add_argument(
        "--env",
        required=True,
        choices=["dev", "prod"],
        help="Environment to provision (drives var-file and state key prefix)",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Skip bootstrap apply (use when state backend already exists)",
    )
    args = parser.parse_args()

    if not args.skip_bootstrap:
        apply_bootstrap()

    outputs = bootstrap_outputs()
    bucket = outputs.get("state_bucket_name", "")
    table = outputs.get("lock_table_name", "")
    if not bucket or not table:
        print(
            "Error: bootstrap did not output state_bucket_name or lock_table_name",
            file=sys.stderr,
        )
        sys.exit(1)

    for module in MODULES:
        apply_module(module, args.env, bucket, table)

    helm_installs(args.env)

    print(f"\nProvision complete (env={args.env}).")


if __name__ == "__main__":
    main()
