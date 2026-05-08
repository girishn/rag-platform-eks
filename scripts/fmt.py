#!/usr/bin/env -S uv run
"""Run ruff format across all source."""
import subprocess
import sys


def main() -> None:
    result = subprocess.run(["ruff", "format", "src/"], check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
