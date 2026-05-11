#!/usr/bin/env -S uv run
"""Apply all Terraform modules in dependency order, then run helm installs."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

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


def run_capture(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"\nFailed: {' '.join(str(c) for c in cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout.strip()


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


def create_litellm_db_secret(env: str, bucket: str, table: str) -> str:
    """Read RDS master secret, construct DATABASE_URL, store in Secrets Manager.

    Must run after rds module apply and before iam module apply (iam data source looks
    up this secret by name). Returns the DATABASE_URL string.
    """
    print("\n--- litellm DATABASE_URL secret ---")
    rds_dir = TF_ROOT / "rds"

    raw = run_capture(
        ["terraform", "output", "-json"],
        cwd=rds_dir,
    )
    rds_outputs: dict[str, dict] = json.loads(raw)
    endpoint: str = rds_outputs["endpoint"]["value"]          # host:port
    master_secret_arn: str = rds_outputs["master_secret_arn"]["value"]

    # Read master credentials from Secrets Manager
    creds_raw = run_capture([
        "aws", "secretsmanager", "get-secret-value",
        "--secret-id", master_secret_arn,
        "--region", REGION,
        "--query", "SecretString",
        "--output", "text",
    ])
    creds: dict[str, str] = json.loads(creds_raw)
    username = creds["username"]
    password = quote(creds["password"], safe="")   # RFC 3986 percent-encode

    # endpoint is "host:port" — split for the URL
    host_port = endpoint  # already includes :5432
    db_url = f"postgresql://{username}:{password}@{host_port}/litellm"

    secret_name = "rag-platform-litellm-db-url"

    # Create or update
    check = subprocess.run(
        ["aws", "secretsmanager", "describe-secret", "--secret-id", secret_name, "--region", REGION],
        capture_output=True,
    )
    if check.returncode == 0:
        print(f"  Updating existing secret: {secret_name}")
        run([
            "aws", "secretsmanager", "put-secret-value",
            "--secret-id", secret_name,
            "--secret-string", db_url,
            "--region", REGION,
        ])
    else:
        print(f"  Creating secret: {secret_name}")
        run([
            "aws", "secretsmanager", "create-secret",
            "--name", secret_name,
            "--description", "LiteLLM DATABASE_URL (postgresql://postgres:<pw>@<host>/litellm)",
            "--secret-string", db_url,
            "--region", REGION,
        ])
    print(f"  Done: {secret_name}")
    return db_url


def create_litellm_database(cluster_name: str) -> None:
    """Create the 'litellm' database on RDS via a one-shot in-cluster pod.

    Reads master credentials from Secrets Manager (same source as the DATABASE_URL secret).
    """
    print("\n--- litellm database ---")
    rds_dir = TF_ROOT / "rds"

    raw = run_capture(["terraform", "output", "-json"], cwd=rds_dir)
    rds_outputs: dict[str, dict] = json.loads(raw)
    host_port: str = rds_outputs["endpoint"]["value"]
    host = host_port.split(":")[0]
    master_secret_arn: str = rds_outputs["master_secret_arn"]["value"]

    creds_raw = run_capture([
        "aws", "secretsmanager", "get-secret-value",
        "--secret-id", master_secret_arn,
        "--region", REGION,
        "--query", "SecretString",
        "--output", "text",
    ])
    creds = json.loads(creds_raw)
    password: str = creds["password"]

    print(f"  $ kubectl run litellm-db-init (creates litellm database on {host})")
    result = subprocess.run(
        [
            "kubectl", "run", "litellm-db-init",
            "--image=postgres:16-alpine",
            "--rm", "--restart=Never",
            "--namespace=default",
            "--attach",
            f"--env=PGPASSWORD={password}",
            "--command", "--",
            "sh", "-c",
            (
                f"psql -h {host} -U postgres -d rag --set=sslmode=require "
                "-c 'CREATE DATABASE litellm;' 2>&1 || true; "
                f"psql -h {host} -U postgres -d rag --set=sslmode=require "
                "-c \"SELECT datname FROM pg_database WHERE datname='litellm';\" 2>&1"
            ),
        ],
        check=False,
    )
    if result.returncode not in (0, 1):  # psql exits 1 if CREATE DATABASE already exists
        print("  Warning: litellm-db-init pod returned non-zero. Check if database exists.")


def run_litellm_migrations(db_url: str) -> None:
    """Run Prisma migrations via a one-shot in-cluster pod using the litellm-database image.

    The chart's built-in migrations Job is disabled (migrationJob.disableSchemaUpdate: true)
    because it builds DATABASE_URL from parts and breaks with special-char passwords.
    This function runs the same migration script with the full DATABASE_URL directly.
    """
    print("\n--- litellm Prisma migrations ---")
    result = subprocess.run(
        [
            "kubectl", "run", "litellm-prisma-migrate",
            f"--image=ghcr.io/berriai/litellm-database:main-v1.82.3",
            "--rm", "--restart=Never",
            "--namespace=rag-platform",
            "--attach",
            f"--env=DATABASE_URL={db_url}",
            "--command", "--",
            "python", "litellm/proxy/prisma_migration.py",
        ],
        check=False,
    )
    if result.returncode not in (0, 1):
        print("  Warning: litellm-prisma-migrate returned non-zero. Check migration status.")


def kubectl_apply_secret(name: str, namespace: str, literals: dict[str, str]) -> None:
    """Create-or-update a k8s Secret using dry-run + apply (idempotent)."""
    args = ["kubectl", "create", "secret", "generic", name, "--namespace", namespace]
    for k, v in literals.items():
        args += [f"--from-literal={k}={v}"]
    args += ["--dry-run=client", "-o", "yaml"]
    manifest = subprocess.run(args, capture_output=True, check=True).stdout
    result = subprocess.run(["kubectl", "apply", "-f", "-"], input=manifest, check=False)
    if result.returncode != 0:
        print(f"\nFailed to apply secret {name}", file=sys.stderr)
        sys.exit(result.returncode)


def bootstrap_k8s_secrets(db_url: str, redis_url: str) -> None:
    """Create the rag-platform namespace and pre-seed k8s Secrets LiteLLM needs on startup.

    litellm-db-url-sync is managed here (not by the CSI driver) to avoid a Pod Identity
    dependency at mount time. provision.py keeps it current on every run.

    PROXY_MASTER_KEY is generated once and never regenerated on re-runs (idempotent).
    """
    import secrets as _secrets
    print("\n--- k8s namespace + litellm secrets ---")
    k8s_root = Path(__file__).parent.parent / "k8s"

    # Namespace — idempotent via dry-run | apply
    run_capture(["kubectl", "create", "namespace", "rag-platform",
                 "--dry-run=client", "-o", "yaml"])
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=subprocess.run(
            ["kubectl", "create", "namespace", "rag-platform", "--dry-run=client", "-o", "yaml"],
            capture_output=True, check=True,
        ).stdout,
        check=False,
    )
    print("  namespace rag-platform: ready")

    # DATABASE_URL synced secret — always update to match current RDS password
    kubectl_apply_secret("litellm-db-url-sync", "rag-platform", {"DATABASE_URL": db_url})

    # litellm-env: only create if it doesn't exist (preserves PROXY_MASTER_KEY across re-runs)
    exists = subprocess.run(
        ["kubectl", "get", "secret", "litellm-env", "--namespace", "rag-platform"],
        capture_output=True,
    )
    if exists.returncode != 0:
        master_key = _secrets.token_hex(32)
        kubectl_apply_secret("litellm-env", "rag-platform", {
            "REDIS_URL": redis_url,
            "PROXY_MASTER_KEY": master_key,
        })
        print(f"  PROXY_MASTER_KEY={master_key}  (save this for virtual key management)")
    else:
        print("  litellm-env already exists — PROXY_MASTER_KEY preserved")


def helm_installs(env: str) -> None:
    print("\n--- helm installs ---")
    helm_root = Path(__file__).parent.parent / "helm"
    k8s_root = Path(__file__).parent.parent / "k8s"

    # vLLM — GPU inference server. KEDA minReplicaCount=0 so no GPU node provisioned until load arrives.
    run([
        "helm", "upgrade", "--install", "vllm", str(helm_root / "vllm"),
        "--namespace", "rag-platform", "--create-namespace",
    ])

    # Migrations Job spec is immutable — delete before upgrade so Helm can recreate it.
    subprocess.run(
        ["kubectl", "delete", "job", "litellm-migrations", "-n", "rag-platform", "--ignore-not-found"],
        check=False,
    )

    # LiteLLM — proxy (Bedrock primary, vLLM fallback). Secrets pre-created by bootstrap_k8s_secrets.
    run([
        "helm", "upgrade", "--install", "litellm",
        "oci://ghcr.io/berriai/litellm-helm",
        "--version", "1.82.3",
        "--namespace", "rag-platform",
        "-f", str(helm_root / "litellm" / "values.yaml"),
    ])

    # KEDA ScaledObject — scale vLLM on vllm:num_requests_waiting queue depth
    run(["kubectl", "apply", "-f", str(k8s_root / "keda" / "vllm-scaledobject.yaml")])


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

    litellm_db_url: str = ""

    for module in MODULES:
        apply_module(module, args.env, bucket, table)
        if module == "rds":
            litellm_db_url = create_litellm_db_secret(args.env, bucket, table)

    # Fallback: read db_url from Secrets Manager if create_litellm_db_secret returned empty
    # (can happen if the rds module was a no-op on a re-run with an older script version)
    if not litellm_db_url:
        litellm_db_url = run_capture([
            "aws", "secretsmanager", "get-secret-value",
            "--secret-id", "rag-platform-litellm-db-url",
            "--region", REGION,
            "--query", "SecretString", "--output", "text",
        ])

    # Read cluster name + ElastiCache endpoint for post-provision steps
    eks_raw = run_capture(["terraform", "output", "-json"], cwd=TF_ROOT / "eks")
    eks_outputs: dict[str, dict] = json.loads(eks_raw)
    cluster_name: str = eks_outputs.get("cluster_name", {}).get("value", "rag-platform-cluster")

    ec_raw = run_capture(["terraform", "output", "-json"], cwd=TF_ROOT / "elasticache")
    ec_outputs: dict[str, dict] = json.loads(ec_raw)
    redis_url: str = ec_outputs["redis_endpoint"]["value"]

    # Update kubeconfig
    run(["aws", "eks", "update-kubeconfig", "--name", cluster_name, "--region", REGION])

    create_litellm_database(cluster_name)
    bootstrap_k8s_secrets(litellm_db_url, redis_url)
    helm_installs(args.env)
    run_litellm_migrations(litellm_db_url)

    print(f"\nProvision complete (env={args.env}).")


if __name__ == "__main__":
    main()
