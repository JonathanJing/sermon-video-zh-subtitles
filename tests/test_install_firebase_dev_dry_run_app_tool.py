"""Offline compatibility checks for the Firebase Dev App installer."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tools.ops import install_firebase_dev_dry_run_app as installer


ROOT = Path(__file__).resolve().parents[1]


def test_external_commands(tmp_path):
    assert installer.SOURCE == ROOT / "apps/listening-web/reader"
    assert (installer.SOURCE / "published-weeks-dry-run.mjs").is_file()
    assert (installer.SOURCE / "dry-run-app-weeks.mjs").is_file()
    env = {**os.environ, "PYTHONPATH": ""}
    result = subprocess.run([sys.executable, str(ROOT / "tools/ops/install_firebase_dev_dry_run_app.py"), "--help"],
                            cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert "--base-dev" in result.stdout
    module = subprocess.run([sys.executable, "-m", "tools.ops.install_firebase_dev_dry_run_app", "--help"],
                            cwd=tmp_path, env={**env, "PYTHONPATH": str(ROOT)},
                            text=True, capture_output=True)
    assert module.returncode == 0, module.stderr


def test_synthetic_inputs_rejected_before_snapshot_copy(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    receipt = tmp_path / "preflight.json"
    receipt.write_text(json.dumps({"status": "pass", "origin": installer.dry.DEV_ORIGIN}))
    out = tmp_path / "candidate"
    with pytest.raises(ValueError, match="page ID"):
        installer.install(base, receipt, "unexpected", out)
    assert not out.exists()

    (base / "firebase.json").write_text(json.dumps({"hosting": {"site": "wrong-site"}}))
    with pytest.raises(ValueError, match="complete Firebase Dev snapshot"):
        installer.install(base, receipt, "dryrun-synthetic", out)
    assert not out.exists()

    out.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        installer.install(base, receipt, "dryrun-synthetic", out)
