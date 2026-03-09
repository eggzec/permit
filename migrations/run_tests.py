#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#     "psycopg[binary]>=3.1.13",
#     "pytest>=7.4.3",
#     "pytest-xdist>=3.2.0",
#     "testcontainers[postgres]>=4.0.0",
# ]
# ///

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

if __name__ == "__main__":
    base_dir = Path(__file__).parent
    os.chdir(base_dir)
    sys.exit(pytest.main(["tests", "-v", "--tb=short", *sys.argv[1:]]))
