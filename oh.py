#!/usr/bin/env python3
"""oh.py — CLI entry point. Stays at repo root; thin wrapper over harness.cli."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from harness.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
