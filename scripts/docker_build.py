#!/usr/bin/env python3
"""Build and push all container images to ECR.

Usage:
    REGISTRY=<account>.dkr.ecr.ap-southeast-2.amazonaws.com uv run scripts/docker_build.py
"""
import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Image:
    name: str
    dockerfile: str
    context: str


IMAGES = [
    Image("rag-api", "src/rag_api/Dockerfile", "."),
    Image("ingestion", "src/ingestion/Dockerfile", "."),
]


def main() -> None:
    registry = os.environ.get("REGISTRY")
    if not registry:
        print("Error: REGISTRY env var not set. Run ecr_setup.py first.", file=sys.stderr)
        sys.exit(1)

    tag = os.environ.get("TAG", "latest")
    failures: list[str] = []

    for image in IMAGES:
        full_tag = f"{registry}/{image.name}:{tag}"
        print(f"\nBuilding {full_tag}...")

        build = subprocess.run(
            ["docker", "build", "-f", image.dockerfile, "-t", full_tag, image.context],
            check=False,
        )
        if build.returncode != 0:
            failures.append(f"build failed: {image.name}")
            continue

        push = subprocess.run(["docker", "push", full_tag], check=False)
        if push.returncode != 0:
            failures.append(f"push failed: {image.name}")

    if failures:
        for f in failures:
            print(f"  FAILED: {f}", file=sys.stderr)
        sys.exit(1)

    print("\nAll images built and pushed.")


if __name__ == "__main__":
    main()
