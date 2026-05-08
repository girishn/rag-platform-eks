#!/usr/bin/env -S uv run
"""Create ECR repositories and docker login. Run once per session before docker_build.py."""
import subprocess
import sys
import boto3


REGION = "ap-southeast-2"
REPOS = ["rag-api", "ingestion"]


def main() -> None:
    ecr = boto3.client("ecr", region_name=REGION)
    account_id = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    registry = f"{account_id}.dkr.ecr.{REGION}.amazonaws.com"

    for repo in REPOS:
        try:
            ecr.create_repository(
                repositoryName=repo,
                imageScanningConfiguration={"scanOnPush": True},
                encryptionConfiguration={"encryptionType": "AES256"},
            )
            print(f"Created: {repo}")
        except ecr.exceptions.RepositoryAlreadyExistsException:
            print(f"Exists:  {repo}")

    result = subprocess.run(
        ["aws", "ecr", "get-login-password", "--region", REGION],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=result.stdout, text=True, check=True,
    )
    print(f"\nDocker logged in to: {registry}")
    print(f"Set REGISTRY={registry} before running docker_build.py")


if __name__ == "__main__":
    main()
