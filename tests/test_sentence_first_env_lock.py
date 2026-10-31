"""Tests for the locked local environment (``requirements-sfa.lock`` + bootstrap script)."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "sentence-first-agent"
LOCK = EXP / "requirements-sfa.lock"
IN = EXP / "requirements-sfa.in"
BOOTSTRAP = ROOT / "tools" / "ops" / "bootstrap_sentence_first_env.sh"


def test_the_lock_is_pinned_and_covers_the_direct_dependencies():
    lines = [line.strip() for line in LOCK.read_text(encoding="utf-8").splitlines() if line.strip()]
    pinned = [line for line in lines if not line.startswith("#")]
    assert pinned, "lock has no requirements"
    assert all("==" in line for line in pinned), f"unpinned requirement in lock: {[l for l in pinned if '==' not in l]}"
    joined = "\n".join(pinned)
    for name in ("jsonschema==", "google-auth==", "reportlab=="):
        assert name in joined, f"{name} missing from the lock"
    assert "jsonschema" in IN.read_text(encoding="utf-8")


def test_bootstrap_script_parses_and_checks_the_existing_venv():
    assert BOOTSTRAP.is_file()
    syntax = subprocess.run(["bash", "-n", str(BOOTSTRAP)], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        return
    result = subprocess.run(["bash", str(BOOTSTRAP), "--check", ".venv"], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "environment OK" in result.stdout
    assert str(ROOT / "packages" / "production" / "src" / "tongxing_production") in result.stdout
