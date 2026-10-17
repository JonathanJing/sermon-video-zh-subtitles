"""Compatibility and offline behavior for the Firebase Dev snapshot preflight."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import preflight_firebase_dev_snapshot as legacy
from tools.ops import preflight_firebase_dev_snapshot as preflight


ROOT = Path(__file__).resolve().parents[1]


def test_old_and_new_module_are_same_and_cli_loads_outside_repo(tmp_path):
    assert legacy is preflight
    env = {**os.environ, "PYTHONPATH": ""}
    for path in (ROOT / "scripts/preflight_firebase_dev_snapshot.py",
                 ROOT / "tools/ops/preflight_firebase_dev_snapshot.py"):
        result = subprocess.run([sys.executable, str(path), "--help"], cwd=tmp_path,
                                env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert "--base-dev" in result.stdout
    module = subprocess.run([sys.executable, "-m", "scripts.preflight_firebase_dev_snapshot", "--help"],
                            cwd=tmp_path, env={**env, "PYTHONPATH": str(ROOT)},
                            text=True, capture_output=True)
    assert module.returncode == 0, module.stderr
    spec = importlib.util.spec_from_file_location("legacy_snapshot", ROOT / "scripts/preflight_firebase_dev_snapshot.py")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    assert sys.modules[spec.name] is preflight


def test_synthetic_full_and_incremental_preflight_without_network(tmp_path, monkeypatch):
    site = tmp_path / "site"
    public = site / "public"
    public.mkdir(parents=True)
    (site / "firebase.json").write_text(json.dumps({"hosting": {"site": preflight.dry.DEV_SITE}}))
    (public / "one.txt").write_bytes(b"one")
    (public / "two.txt").write_bytes(b"two")
    remote = {"one.txt": b"one", "two.txt": b"two"}

    class Response(io.BytesIO):
        status = 200
        headers = {"ETag": '"synthetic"'}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(request, timeout):
        name = request.full_url.rsplit("/", 1)[-1]
        assert request.full_url.startswith(preflight.dry.DEV_ORIGIN + "/")
        assert timeout in (30, 120)
        return Response(remote[name] if request.get_method() == "GET" else b"")

    monkeypatch.setattr(preflight, "urlopen", fake_urlopen)
    full = preflight.verify(site)
    assert full["status"] == "pass" and full["fileCount"] == 2
    assert full["verificationMode"] == "full_get"

    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(full))
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "two.txt").write_bytes(b"two")
    incremental = preflight.verify(site, receipt, staged)
    assert incremental["verificationMode"] == "incremental_complete"
    assert incremental["files"] == full["files"]

    (public / "two.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="differs"):
        preflight.verify(site, receipt, staged)
