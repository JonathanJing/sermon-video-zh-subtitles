"""Entry compatibility for the weekly announcement binder (its scripts/ facade was removed in facade batch E)."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_implementation_and_command_entry_run_from_an_external_working_directory(tmp_path):
    env = {**os.environ, "PYTHONPATH": ""}
    for command in ([sys.executable, str(ROOT / "packages/production/src/tongxing_production/delivery/posters/announcement_sidecar.py"), "--help"],
                    [sys.executable, str(ROOT / "tools/ops/run.py"), "delivery.posters.announcement_sidecar", "--help"]):
        result = subprocess.run(command, cwd=tmp_path, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert "--poster-receipt" in result.stdout
