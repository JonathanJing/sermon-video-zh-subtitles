"""Import the package sources of the tree these tests live in, not the shared venv's.

Worktrees share the main checkout's .venv, whose editable install puts the main
checkout's ``packages/production/src`` on ``sys.path``. Run from a worktree with
that interpreter, tests and the Python children they start would import the main
checkout's ``tongxing_production``. ``tests/conftest.py`` calls ``install()`` so
the pytest process and children that inherit its environment import this tree;
a test that gives a child a fresh environment passes it through ``child_env()``.
Entries on ``PYTHONPATH`` come before site-packages, so they win over the
editable .pth. Children started with ``python -I`` ignore ``PYTHONPATH``; for
those use ``tools/development/worktree_venv.py`` (see CONTRIBUTING.md).
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
# Package sources the shared venv installs in editable mode (requirements.txt).
SOURCES = (ROOT / 'packages/production/src', ROOT / 'services/api/src')


def pythonpath(existing: str | None = None) -> str:
    """``PYTHONPATH`` with this tree's sources first and ``existing`` entries after them."""
    first = [str(path) for path in SOURCES]
    rest = [entry for entry in (existing or '').split(os.pathsep) if entry and entry not in first]
    return os.pathsep.join(first + rest)


def child_env(env: dict[str, str]) -> dict[str, str]:
    """A copy of ``env`` whose Python children import this tree's sources."""
    return {**env, 'PYTHONPATH': pythonpath(env.get('PYTHONPATH'))}


def install() -> None:
    """Put this tree's sources first on ``sys.path`` and on the inherited ``PYTHONPATH``."""
    first = [str(path) for path in SOURCES]
    sys.path[:] = first + [entry for entry in sys.path if entry not in first]
    os.environ['PYTHONPATH'] = pythonpath(os.environ.get('PYTHONPATH'))
    loaded = sys.modules.get('tongxing_production')
    if loaded is not None and not Path(loaded.__file__).resolve().is_relative_to(SOURCES[0]):
        raise RuntimeError(f'tongxing_production was imported from {loaded.__file__} before tests/conftest.py '
                           f'could select {SOURCES[0]}')
