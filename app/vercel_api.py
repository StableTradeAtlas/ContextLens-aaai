"""Stateless, credential-free adapter for the four-view address demo.

Both deployments call the same resolver and investigation functions. This adapter
never uses InvestigationStore, SQLite, live library services, or model APIs.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from app.config import PROCESSED_DIR
from app.place_investigation import FALLBACK_CANDIDATES, investigate_address, resolve_place

MAX_ADDRESS = 180


@lru_cache(maxsize=1)
def snapshot_metadata() -> dict[str, Any]:
    path = PROCESSED_DIR / "shlibrary_official_snapshot.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload["records"]
    if payload["record_count"] != len(records):
        raise ValueError("Snapshot record count mismatch")
    return {
        "record_count": len(records),
        "source_file_count": payload["source_file_count"],
        "generated_at": payload["generated_at"],
        "datasets": dict(Counter(record["dataset"] for record in records)),
    }


def health_payload() -> dict[str, Any]:
    snapshot = snapshot_metadata()
    return {
        "ok": True,
        "version": "contextlens-vercel-snapshot-1",
        "deployment_mode": "stateless_bundled_evidence",
        "records": snapshot["record_count"],
        "official_records": snapshot["record_count"],
        "official_snapshot_records": snapshot["record_count"],
        "live_records": 0,
        "seed_records": 0,
        "demo_seed_active": False,
        "api_key_configured": False,
        "deepseek_available": False,
        "investigation_mode": "synchronous",
        "curated_place_count": len({
            candidate.canonical_name
            for candidates in FALLBACK_CANDIDATES.values()
            for candidate in candidates
        }),
        "snapshot": snapshot,
    }


def dispatch(method: str, path: str, payload: Any = None) -> tuple[int, dict[str, Any]]:
    """Return an HTTP status and JSON payload without persistent request state."""
    if method == "GET" and path == "/api/health":
        return 200, health_payload()
    if method == "GET" and path.startswith("/api/investigations/"):
        return 410, {"error": "Hosted results are returned by POST /api/investigations; job IDs are not stored."}
    if method != "POST" or path not in {"/api/place/resolve", "/api/investigations"}:
        return 404, {"error": "Unknown demo endpoint"}

    if not isinstance(payload, dict):
        return 400, {"error": "The request must be a JSON object."}
    address = payload.get("address")
    era = payload.get("era_hint")
    if not isinstance(address, str) or not address.strip() or len(address) > MAX_ADDRESS:
        return 400, {"error": f"Use an address of 1 to {MAX_ADDRESS} characters."}
    if era is not None and not isinstance(era, (str, int)):
        return 400, {"error": "era_hint must be a year or a short string."}
    if isinstance(era, str) and len(era) > 80:
        return 400, {"error": "era_hint is too long."}

    # Keys and browser flags cannot turn a public demo request into a paid/live call.
    resolution = resolve_place(address.strip(), era, allow_live=False)
    if path == "/api/place/resolve":
        return 200, resolution

    submitted = payload.get("candidate")
    candidate_id = submitted.get("candidate_id") if isinstance(submitted, dict) else payload.get("candidate_id")
    candidates = resolution["candidates"]
    if candidate_id:
        candidate = next((item for item in candidates if item["candidate_id"] == candidate_id), None)
        if candidate is None:
            return 400, {"error": "Choose a candidate returned for this address."}
    elif len(candidates) == 1:
        candidate = candidates[0]
    else:
        return 409, {"error": "Resolve and confirm the address first.", "resolution": resolution}

    # Re-resolve server-side: user-provided descriptions/URIs never become evidence.
    result = investigate_address(candidate, address=address.strip(), era_hint=era, allow_live=False)
    result["deployment_mode"] = "stateless_bundled_evidence"
    return 200, {"status": "complete", "progress": 100, "result": result}
