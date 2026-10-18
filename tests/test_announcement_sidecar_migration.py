"""Entry compatibility for the weekly announcement binder."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

from scripts import build_weekly_announcement_sidecar as legacy
from tongxing_production.delivery.posters import announcement_sidecar as implementation


ROOT = Path(__file__).resolve().parents[1]


def test_module_alias_and_external_working_directory(tmp_path):
    assert legacy is implementation
    env = {**os.environ, "PYTHONPATH": ""}
    for path in (ROOT / "scripts/build_weekly_announcement_sidecar.py",
                 ROOT / "packages/production/src/tongxing_production/delivery/posters/announcement_sidecar.py"):
        result = subprocess.run([sys.executable, str(path), "--help"], cwd=tmp_path,
                                env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert "--poster-receipt" in result.stdout
    module = subprocess.run([sys.executable, "-m", "scripts.build_weekly_announcement_sidecar", "--help"],
                            cwd=tmp_path, env={**env, "PYTHONPATH": str(ROOT)},
                            text=True, capture_output=True)
    assert module.returncode == 0, module.stderr
    spec = importlib.util.spec_from_file_location("weekly_announcements_alias",
                                                  ROOT / "scripts/build_weekly_announcement_sidecar.py")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    assert sys.modules[spec.name] is implementation
