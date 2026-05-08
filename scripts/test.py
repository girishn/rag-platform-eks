#!/usr/bin/env -S uv run
"""Run the full test suite or a specific test path.

Usage:
    uv run scripts/test.py                                     # all tests
    uv run scripts/test.py src/rag_api/tests/test_foo.py::bar  # single test
"""
import subprocess
import sys


def main() -> None:
    extra_args = sys.argv[1:]
    cmd = ["pytest", "-v", "--tb=short"] + (extra_args if extra_args else ["src/"])
    result = subprocess.run(cmd, check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
