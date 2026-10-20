"""tools/ops/run.py: the package command entry that binds the checkout host first."""
import importlib
import importlib.machinery
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

from tools.ops import run

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "tools/ops/run.py"
FAKE = "tongxing_production.run_entry_fake_for_test"


def _run(*arguments, cwd):
    env = {**os.environ, "PYTHONPATH": ""}
    return subprocess.run([sys.executable, str(ENTRY), *arguments], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def fake_command():
    """Register a package module whose main() the test controls."""
    module = types.ModuleType(FAKE)
    module.__spec__ = importlib.machinery.ModuleSpec(FAKE, None)
    sys.modules[FAKE] = module
    argv = list(sys.argv)
    try:
        yield module
    finally:
        sys.modules.pop(FAKE, None)
        sys.argv[:] = argv


def test_host_is_bound_before_the_target_is_imported(monkeypatch):
    imported = []
    real = importlib.import_module

    def record(name, *arguments):
        imported.append(name)
        return real(name, *arguments)

    monkeypatch.setattr(run.importlib, "import_module", record)
    entry = run.command("observability.progress")
    assert imported == [*run.HOSTS, "tongxing_production.observability.progress"]
    assert entry is sys.modules["tongxing_production.observability.progress"].main
    # The port the facade binds is configured once the host is imported.
    from tongxing_production.text import backend
    assert backend.current() is not None


@pytest.mark.parametrize("name, message", [
    ("text.no_such_module", "no module tongxing_production.text.no_such_module"),
    ("no_such_layer.module", "no module tongxing_production.no_such_layer.module"),
    ("text.candidate.main", "no module tongxing_production.text.candidate.main"),
    ("text", "is a package"),
    ("contracts.schemas", "has no main()"),
    ("tongxing_production.text.candidate", "without the tongxing_production. prefix: text.candidate"),
    ("../scripts/sermon_pipeline", "not a package module name"),
    ("os", "no module tongxing_production.os"),
    ("text._private", "not a package module name"),
])
def test_unknown_modules_are_rejected(name, message, capsys):
    assert run.main([name, "--help"]) == 2
    assert message in capsys.readouterr().err


def test_arguments_and_help_pass_through(fake_command):
    seen = []
    fake_command.main = lambda: seen.append(list(sys.argv))
    assert run.main(["run_entry_fake_for_test", "--help", "-x", "value"]) is None
    assert seen == [["run_entry_fake_for_test", "--help", "-x", "value"]]


@pytest.mark.parametrize("behaviour, status", [
    (lambda: None, None), (lambda: 0, 0), (lambda: 3, 3), (lambda: sys.exit(4), 4),
])
def test_exit_status_is_the_commands(fake_command, behaviour, status):
    fake_command.main = behaviour
    if status == 4:
        with pytest.raises(SystemExit) as raised:
            run.main(["run_entry_fake_for_test"])
        assert raised.value.code == 4
    else:
        assert run.main(["run_entry_fake_for_test"]) == status


def test_runs_from_any_directory_and_keeps_exit_codes(tmp_path):
    help_text = _run("observability.progress", "--help", cwd=tmp_path)
    assert help_text.returncode == 0, help_text.stderr
    assert help_text.stdout.startswith("usage: observability.progress")
    # argparse rejects the call inside the command; its status 2 reaches the shell.
    bad = _run("observability.progress", "--no-such-option", cwd=tmp_path)
    assert bad.returncode == 2 and "observability.progress: error:" in bad.stderr
    unknown = _run("text.no_such_module", cwd=tmp_path)
    assert unknown.returncode == 2 and "no module tongxing_production.text.no_such_module" in unknown.stderr


def test_own_usage(tmp_path):
    shown = _run("--help", cwd=tmp_path)
    assert shown.returncode == 0 and shown.stdout.startswith("usage: run.py <module>")
    missing = _run(cwd=tmp_path)
    assert missing.returncode == 2 and missing.stderr.startswith("usage: run.py <module>")


@pytest.mark.parametrize("facade, module", [
    ("scripts/produce_target_language_candidate.py", "text.candidate"),
])
def test_help_matches_the_facade(tmp_path, facade, module):
    old = subprocess.run([sys.executable, str(ROOT / facade), "--help"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=120)
    new = _run(module, "--help", cwd=tmp_path)
    assert old.returncode == new.returncode == 0, (old.stderr, new.stderr)
    normal = lambda text: " ".join(text.split())
    assert normal(old.stdout.replace(Path(facade).name, module)) == normal(new.stdout)


def test_spawned_children_bind_the_host_before_unpickling(tmp_path):
    """multiprocessing spawn re-runs the main script as __mp_main__ (spawn._fixup_main_from_path);
    the Spark TTS replica pool's workers then import audio.renderer, which reads host rules at import."""
    probe = ("import runpy, sys; runpy.run_path(sys.argv[1], run_name='__mp_main__'); "
             "from tongxing_production.audio import renderer; print(renderer.RENDERER_SOUND_IDENTITY_SHA256)")
    env = {**os.environ, "PYTHONPATH": ""}
    result = subprocess.run([sys.executable, "-c", probe, str(ENTRY)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert len(result.stdout.strip()) == 64


def test_orchestration_modules_get_the_unified_backend(tmp_path):
    """A prepared-workflow command needs the orchestration Backend its scripts/ facade used to bind."""
    probe = ("import runpy, sys; sys.argv = [sys.argv[1]]; g = runpy.run_path(sys.argv[0], run_name='probe'); "
             "g['command']('workflows.prepared.capabilities'); "
             "from tongxing_production.orchestration.unified import backend; backend.current(); "
             "print('scripts.sermon_unified' in sys.modules)")
    env = {**os.environ, "PYTHONPATH": ""}
    result = subprocess.run([sys.executable, "-c", probe, str(ENTRY)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("True")
