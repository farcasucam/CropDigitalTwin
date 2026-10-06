"""Run the local Agri-Twin frontend and API (current phase) with caller-injected operational timing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agri_twin.interfaces.frontend_api import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Agri-Twin frontend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port, timer=perf_counter)


if __name__ == "__main__":
    main()
