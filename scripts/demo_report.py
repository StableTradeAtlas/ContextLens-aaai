"""Write measured acceptance outputs; these are demonstration checks, not accuracy estimates."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.vercel_api import dispatch

CASES = [
    ("joffre-1934", "霞飞路436号", "1934"),
    ("bund-1930s", "外滩20号", "1930年代"),
    ("ambiguous-nanjing", "南京路百货公司", "1940年代"),
    ("unresolved", "9999 Mars Road", "1934"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reproducibility/demo-report.json")
    args = parser.parse_args()
    started = time.perf_counter()
    rows = []
    for case_id, address, era in CASES:
        before = time.perf_counter()
        status, resolution = dispatch("POST", "/api/place/resolve", {"address": address, "era_hint": era})
        row = {"case_id": case_id, "address": address, "era": era, "http_status": status,
               "resolution": resolution["status"], "candidates": len(resolution["candidates"])}
        if resolution["status"] == "resolved":
            _, response = dispatch("POST", "/api/investigations", {
                "address": address, "era_hint": era, "candidate": resolution["candidates"][0],
            })
            result = response["result"]
            row.update(timeline_nodes=len(result["timeline"]), evidence_cards=len(result["evidence"]),
                       direct_claims=result["quality"]["direct_claim_count"],
                       unique_feature_sources=result["quality"]["source_count"],
                       names=len(result["candidate"]["name_periods"]),
                       result=result)
        row["elapsed_ms"] = round((time.perf_counter() - before) * 1000, 3)
        rows.append(row)
    paths = [
        "data/processed/shlibrary_official_snapshot.json",
        "app/place_investigation.py", "app/historical_maps.py", "package-lock.json",
    ]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unavailable"
    report = {
        "scope": "Four curated acceptance cases; no held-out accuracy or user-study claim.",
        "git_commit": commit, "python": platform.python_version(), "platform": platform.platform(),
        "snapshot_mode": "Bundled curated place features; library snapshot counted separately.",
        "sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
        "cases": rows, "elapsed_ms": round((time.perf_counter()-started)*1000, 3),
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "cases": [{k:v for k,v in row.items() if k != "result"} for row in rows]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
