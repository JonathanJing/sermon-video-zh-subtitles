#!/usr/bin/env python3
"""Give a git worktree its own .venv that imports the worktree's package.

The shared repo-root .venv installs ``tongxing_production`` in editable mode,
and its ``__editable__`` .pth points at the main checkout's
``packages/production/src``. A test run from a worktree therefore imports the
main checkout's package. ``PYTHONPATH`` only fixes the parent process: workers
started with ``python -I`` (for example the mock TTS worker ``compute/mock_tts/control.py`` launches)
ignore it.

This creates ``<worktree>/.venv`` from the shared venv's interpreter, without
pip, and writes one .pth that lists ``<worktree>/packages/production/src`` and
``<worktree>/services/api/src`` first and then the shared venv's site-packages.
The shared venv's .pth files are not processed, so the main checkout's source
never lands on ``sys.path``.
``python -I`` still reads site-packages .pth files, so child processes started
with ``sys.executable`` import the worktree package too, and scripts that look
for ``$REPO/.venv/bin/python`` find this venv. Install dependencies into the
shared venv; rerun this after its Python version changes.

    python3 tools/development/worktree_venv.py             create or refresh <worktree>/.venv
    python3 tools/development/worktree_venv.py --check     only report what .venv/bin/python -I imports
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SRC = Path('packages/production/src')
# The API package requirements.txt also installs in editable mode (tests/test_backend_app.py imports it).
API_SRC = Path('services/api/src')
MARKER = 'worktree-venv.txt'
PTH_NAME = '_worktree_paths.pth'


def _run(args: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def main_checkout(worktree: Path) -> Path:
    common = Path(_run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=worktree))
    return common.parent


def site_packages(python: Path) -> Path:
    return Path(_run([str(python), '-I', '-c', "import sysconfig; print(sysconfig.get_paths()['purelib'])"]))


def imported_package(python: Path) -> Path:
    return Path(_run([str(python), '-I', '-c', 'import tongxing_production; print(tongxing_production.__file__)']))


def build(worktree: Path, shared_venv: Path) -> Path:
    """Create or refresh worktree/.venv; return its python."""
    shared_python = shared_venv / 'bin' / 'python'
    if not shared_python.exists():
        raise SystemExit(f'no shared venv python at {shared_python}')
    target = worktree / '.venv'
    if target.exists() and not (target / MARKER).exists():
        raise SystemExit(f'{target} exists and was not made by this script; move it aside first')
    subprocess.run([str(shared_python), '-m', 'venv', '--clear', '--without-pip', str(target)], check=True)
    python = target / 'bin' / 'python'
    lines = [str(worktree / PACKAGE_SRC), str(worktree / API_SRC), str(site_packages(shared_python))]
    (site_packages(python) / PTH_NAME).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (target / MARKER).write_text(f'shared venv: {shared_venv}\n', encoding='utf-8')
    return python


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--shared-venv', type=Path, help='default: <main checkout>/.venv')
    parser.add_argument('--check', action='store_true', help='report only; change nothing')
    args = parser.parse_args()

    main_root = main_checkout(ROOT)
    if main_root == ROOT:
        print('this is the main checkout; its .venv already imports its own package', file=sys.stderr)
        return 1
    python = ROOT / '.venv' / 'bin' / 'python'
    if not args.check:
        python = build(ROOT, (args.shared_venv or main_root / '.venv').resolve())
    if not python.exists():
        print(f'no {python}; run without --check', file=sys.stderr)
        return 1
    package = imported_package(python)
    expected = ROOT / PACKAGE_SRC
    print(f'{python} -I imports tongxing_production from {package.parent}')
    if not package.is_relative_to(expected):
        print(f'expected it under {expected}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
