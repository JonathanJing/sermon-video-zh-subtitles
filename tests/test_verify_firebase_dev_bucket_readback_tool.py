"""Offline compatibility checks for the Firebase Dev bucket readback tool."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.ops import verify_firebase_dev_four_layer_bucket_dry_run as readback


ROOT = Path(__file__).resolve().parents[1]


def test_external_commands(tmp_path):
    env = {**os.environ, "PYTHONPATH": ""}
    result = subprocess.run([sys.executable, str(ROOT / "tools/ops/verify_firebase_dev_four_layer_bucket_dry_run.py"), "--help"],
                            cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "--candidate" in result.stdout
    module = subprocess.run([sys.executable, "-m", "tools.ops.verify_firebase_dev_four_layer_bucket_dry_run", "--help"],
                            cwd=tmp_path, env={**env, "PYTHONPATH": str(ROOT)},
                            text=True, capture_output=True)
    assert module.returncode == 0, module.stderr


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
