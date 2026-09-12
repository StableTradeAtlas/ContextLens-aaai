from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from app.vercel_api import dispatch

ROOT = Path(__file__).resolve().parents[1]


def resolve(address="霞飞路436号"):
    status, body = dispatch("POST", "/api/place/resolve", {"address": address, "era_hint": "1934"})
    assert status == 200
    return body


def test_snapshot_health_has_real_counts():
    status, body = dispatch("GET", "/api/health")
    assert status == 200 and body["ok"]
    assert body["official_records"] == 154
    assert sum(body["snapshot"]["datasets"].values()) == 154
    assert not body["deepseek_available"] and body["seed_records"] == 0


def test_hosted_investigation_finishes_without_job_storage():
    candidate = resolve()["candidates"][0]
    with patch("app.place_investigation.INVESTIGATION_STORE.create", side_effect=AssertionError("Persistent jobs are forbidden")):
        status, body = dispatch("POST", "/api/investigations", {
            "address": "霞飞路436号", "era_hint": 1934, "candidate": candidate,
        })
    assert status == 200 and body["status"] == "complete"
    assert body["result"]["quality"]["live_feature_count"] == 0
    assert body["result"]["claims"]
    evidence = {card["evidence_id"] for card in body["result"]["evidence"]}
    assert all(set(claim["evidence_ids"]) <= evidence for claim in body["result"]["claims"])
    assert "id" not in body
    assert dispatch("GET", "/api/investigations/expired")[0] == 410


def test_client_candidate_content_cannot_inject_evidence():
    candidate = resolve()["candidates"][0]
    candidate["canonical_name"] = "FAKE ROAD"
    candidate["source_uri"] = "https://invalid.example/injected"
    status, body = dispatch("POST", "/api/investigations", {
        "address": "霞飞路436号", "candidate": candidate, "era_hint": 1934,
    })
    assert status == 200
    assert "invalid.example" not in json.dumps(body)
    assert body["result"]["candidate"]["canonical_name"] != "FAKE ROAD"


def test_unknown_candidate_is_rejected():
    assert dispatch("POST", "/api/investigations", {
        "address": "霞飞路436号", "candidate_id": "not-a-candidate",
    })[0] == 400


def test_ambiguity_and_unresolved_inputs_do_not_create_dossiers():
    assert resolve("南京路百货公司")["status"] == "ambiguous"
    assert resolve("9999 Mars Road")["status"] == "unresolved"
    for address in ("南京路百货公司", "9999 Mars Road"):
        assert dispatch("POST", "/api/investigations", {"address": address})[0] == 409


def test_bad_json_objects_are_rejected():
    for payload in (None, [], {"address": []}, {"address": "x" * 181}, {"address": "外滩", "era_hint": {}}):
        assert dispatch("POST", "/api/place/resolve", payload)[0] == 400


def test_public_flags_do_not_enable_live_or_model_calls(monkeypatch):
    monkeypatch.setenv("SHLIB_API_KEY", "unused-test-key")
    with patch("app.place_investigation.ShanghaiLibraryClient", side_effect=AssertionError("No live calls")):
        candidate = resolve()["candidates"][0]
        status, body = dispatch("POST", "/api/investigations", {
            "address": "霞飞路436号", "candidate": candidate, "allow_live": True, "use_deepseek": True,
        })
    assert status == 200 and body["result"]["quality"]["live_feature_count"] == 0


def test_vercel_paths_do_not_write_to_bundled_data(tmp_path):
    import os
    env = dict(os.environ, VERCEL="1", CONTEXTLENS_RUNTIME_DIR=str(tmp_path / "runtime"))
    code = (
        "from app.config import RAW_DIR, PROCESSED_DIR, INDEX_DIR; "
        "from app.vercel_api import dispatch; "
        "assert '/runtime/' in str(RAW_DIR); "
        "assert '/runtime/' in str(INDEX_DIR); "
        "assert '/runtime/' not in str(PROCESSED_DIR); "
        "assert dispatch('POST','/api/place/resolve',{'address':'霞飞路436号'})[0] == 200"
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True)
