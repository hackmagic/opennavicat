#!/usr/bin/env python
"""Setup script — install dev dependencies and init local config."""

from __future__ import annotations

import subprocess
import sys


def main() -> None:
    print("=== OpenNavicat Development Setup ===\n")

    # 1. Install dependencies
    print("[1/3] Installing dependencies via Poetry...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "poetry"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Warning: poetry install: {result.stderr}")

    result = subprocess.run(
        ["poetry", "install"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("  ✓ Dependencies installed")
    else:
        print(f"  ✗ Failed: {result.stderr}")

    # 2. Create local config directory
    print("\n[2/3] Creating config directories...")
    from open_navicat.config import CONFIG_DIR, DATA_DIR
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Config dir: {CONFIG_DIR}")
    print(f"  ✓ Data dir: {DATA_DIR}")

    # 3. Run tests
    print("\n[3/3] Running unit tests...")
    result = subprocess.run(
        ["poetry", "run", "pytest", "tests/unit/", "-v"],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode == 0:
        print("  ✓ All tests passed!")
    else:
        print(f"  ✗ Some tests failed: {result.stderr}")

    print("\n=== Setup complete ===")
    print("Run 'poetry run opennavicat' to start the application.")


if __name__ == "__main__":
    main()
