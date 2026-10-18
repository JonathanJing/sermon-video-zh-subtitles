"""Offline compatibility checks for the Firebase Dev bucket readback tool."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import verify_firebase_dev_four_layer_bucket_dry_run as legacy
from tools.ops import verify_firebase_dev_four_layer_bucket_dry_run as readback


ROOT = Path(__file__).resolve().parents[1]


def test_old_and_new_module_identity_and_external_commands(tmp_path):
    assert legacy is readback
    env = {**os.environ, "PYTHONPATH": ""}
    for path in (ROOT / "scripts/verify_firebase_dev_four_layer_bucket_dry_run.py",
                 ROOT / "tools/ops/verify_firebase_dev_four_layer_bucket_dry_run.py"):
        result = subprocess.run([sys.executable, str(path), "--help"], cwd=tmp_path,
                                env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert "--candidate" in result.stdout
    module = subprocess.run([sys.executable, "-m", "scripts.verify_firebase_dev_four_layer_bucket_dry_run",
                             "--help"], cwd=tmp_path, env={**env, "PYTHONPATH": str(ROOT)},
                            text=True, capture_output=True)
    assert module.returncode == 0, module.stderr
    spec = importlib.util.spec_from_file_location("legacy_bucket_readback",
                                                  ROOT / "scripts/verify_firebase_dev_four_layer_bucket_dry_run.py")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    assert sys.modules[spec.name] is readback


def test_synthetic_unpublished_candidate_refuses_before_http(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    receipt = tmp_path / "baseline.json"
    receipt.write_text(json.dumps({"status": "pass", "origin": readback.dry.DEV_ORIGIN}))
    report = candidate / "dry-run-report.json"
    report.write_text(json.dumps({"schemaVersion": "wrong", "status": "validated_not_deployed",
                                  "origin": readback.dry.DEV_ORIGIN, "formalCatalogUpdated": False}))
    monkeypatch.setattr(readback, "get", lambda *_args, **_kwargs: pytest.fail("HTTP called"))
    monkeypatch.setattr(readback.urllib.request, "urlopen",
                        lambda *_args, **_kwargs: pytest.fail("HTTP called"))
    with pytest.raises(ValueError, match="unpublished simulated Dev candidate"):
        readback.verify(candidate, receipt)

    report.write_text(json.dumps({"schemaVersion": "sermon-dev-four-layer-bucket-dry-run-v2",
                                  "status": "validated_not_deployed", "origin": readback.dry.DEV_ORIGIN,
                                  "formalCatalogUpdated": False, "baselinePreflightSha256": "wrong"}))
    with pytest.raises(ValueError, match="receipt differs"):
        readback.verify(candidate, receipt)
