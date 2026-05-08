#!/usr/bin/env -S uv run
"""Run terraform fmt, validate, and tflint across all modules."""
import subprocess
import sys
from pathlib import Path


MODULES = ["bootstrap", "eks", "rds", "iam", "addons"]


def run(cmd: list[str], cwd: Path | None = None) -> int:
    result = subprocess.run(cmd, cwd=cwd, check=False)
    return result.returncode


def main() -> None:
    root = Path(__file__).parent.parent / "terraform"
    failures: list[str] = []

    fmt_result = run(["terraform", "fmt", "-check", "-recursive", str(root)])
    if fmt_result != 0:
        failures.append("terraform fmt: formatting issues found — run `terraform fmt -recursive terraform/`")

    for module in MODULES:
        module_dir = root / module
        if not module_dir.exists():
            print(f"  skipping {module} (not yet created)")
            continue

        print(f"\n--- {module} ---")
        if run(["terraform", "init", "-backend=false"], cwd=module_dir) != 0:
            failures.append(f"{module}: terraform init failed")
            continue

        if run(["terraform", "validate"], cwd=module_dir) != 0:
            failures.append(f"{module}: terraform validate failed")

        if run(["tflint", "--init"], cwd=module_dir) == 0:
            if run(["tflint"], cwd=module_dir) != 0:
                failures.append(f"{module}: tflint failed")

    if failures:
        print("\nFailures:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)

    print("\nAll Terraform checks passed.")


if __name__ == "__main__":
    main()
