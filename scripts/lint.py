#!/usr/bin/env -S uv run
"""Run ruff check and mypy across all source."""
import subprocess
import sys


def main() -> None:
    errors: list[str] = []

    result = subprocess.run(["ruff", "check", "src/"], check=False)
    if result.returncode != 0:
        errors.append("ruff check failed")

    result = subprocess.run(["mypy", "src/"], check=False)
    if result.returncode != 0:
        errors.append("mypy failed")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    print("All lint checks passed.")


if __name__ == "__main__":
    main()
