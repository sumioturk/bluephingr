#!/usr/bin/env python3
"""Import the example bundle (templates + flow + calibration) into a running server.

Run this once before bt_toggle_stress.py to load all the templates
and calibration data needed for the Watch flow.

Usage:
    python setup_bundle.py [--server http://localhost:8800] [--bundle bundle/watch-example.zip]
"""

import argparse
import asyncio
from pathlib import Path

from phingr import PhingrSession


async def main(server_url: str, bundle_path: Path):
    if not bundle_path.exists():
        raise SystemExit(f"Bundle not found: {bundle_path}")

    s = PhingrSession(server_url=server_url)
    try:
        print(f"Importing {bundle_path} ({bundle_path.stat().st_size:,} bytes)...")
        result = await s.import_all(bundle_path.read_bytes())
        print(f"  Flows:       {result.get('flows_imported', 0)}")
        print(f"  Templates:   {result.get('templates_imported', 0)}")
        print(f"  Calibration: {'yes' if result.get('calibration_restored') else 'no'}")
        print("Done.")
    finally:
        await s.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import example bundle")
    parser.add_argument("--server", default="http://localhost:8800")
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path(__file__).parent / "bundle" / "watch-example.zip",
    )
    args = parser.parse_args()
    asyncio.run(main(args.server, args.bundle))
