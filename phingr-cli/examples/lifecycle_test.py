#!/usr/bin/env python3
"""Full phingr lifecycle test — export, wipe, verify, import, verify, run.

Proves the entire config/flow/template/calibration bundle can be
backed up and restored from scratch, then a flow runs successfully.

Usage:
    pip install -e /path/to/phingr-cli
    python lifecycle_test.py [--server http://localhost:8800]
"""

import argparse
import asyncio
import sys

from phingr import PhingrSession


async def main(server_url: str):
    # No `async with` — we only need server CRUD, not device actions
    s = PhingrSession(server_url=server_url)
    try:
        # ── 1. Snapshot current state ────────────────────────────
        print("=== Step 1: Snapshot current state ===")
        flows = await s.list_flows()
        templates = await s.list_templates()
        print(f"  Flows:     {len(flows)} — {[f['name'] for f in flows]}")
        print(f"  Templates: {len(templates)} — {[t['name'] for t in templates]}")

        if not flows:
            print("\n  ERROR: No flows on server. Nothing to test with.")
            sys.exit(1)

        # ── 2. Export everything (flows + templates + calibration) ─
        print("\n=== Step 2: Export all ===")
        bundle = await s.export_all()
        print(f"  Bundle size: {len(bundle):,} bytes")

        # ── 3. Delete everything ─────────────────────────────────
        print("\n=== Step 3: Delete everything ===")
        for t in templates:
            await s.delete_template(t["name"])
            print(f"  Deleted template: {t['name']}")
        for f in flows:
            await s.delete_flow(f["filename"])
            print(f"  Deleted flow: {f['filename']}")

        # ── 4. Verify empty ──────────────────────────────────────
        print("\n=== Step 4: Verify empty ===")
        flows_after = await s.list_flows()
        templates_after = await s.list_templates()
        assert len(flows_after) == 0, f"Expected 0 flows, got {len(flows_after)}"
        assert len(templates_after) == 0, f"Expected 0 templates, got {len(templates_after)}"
        print("  OK — 0 flows, 0 templates")

        # ── 5. Import saved bundle ───────────────────────────────
        print("\n=== Step 5: Import bundle ===")
        result = await s.import_all(bundle)
        print(f"  Imported: {result.get('flows_imported', 0)} flows, "
              f"{result.get('templates_imported', 0)} templates, "
              f"calibration={'yes' if result.get('calibration_restored') else 'no'}")

        # ── 6. Verify restored ───────────────────────────────────
        print("\n=== Step 6: Verify restored ===")
        flows_restored = await s.list_flows()
        templates_restored = await s.list_templates()
        print(f"  Flows:     {len(flows_restored)} — {[f['name'] for f in flows_restored]}")
        print(f"  Templates: {len(templates_restored)} — {[t['name'] for t in templates_restored]}")
        assert len(flows_restored) == len(flows), \
            f"Flow count mismatch: had {len(flows)}, restored {len(flows_restored)}"
        assert len(templates_restored) == len(templates), \
            f"Template count mismatch: had {len(templates)}, restored {len(templates_restored)}"
        print("  OK — counts match")

        # ── 7. Run first flow ────────────────────────────────────
        print(f"\n=== Step 7: Run flow '{flows_restored[0]['name']}' ===")
        filename = flows_restored[0]["filename"]
        result = await s.run_flow(filename, log_callback=lambda msg: print(f"  {msg}"))
        print(f"\n  Result: {result.status}")

        if result.status == "success":
            print("\n=== PASS — Full lifecycle completed ===")
        else:
            print("\n=== FAIL — Flow did not succeed ===")
            sys.exit(1)
    finally:
        await s.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="phingr lifecycle test")
    parser.add_argument("--server", default="http://localhost:8800")
    args = parser.parse_args()
    asyncio.run(main(args.server))
