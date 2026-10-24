"""The named Layer 2 code closure: the files ``text.controller.code_identity()`` binds.

``config/layer2-code-closure.json`` lists every repository file a Layer 2 run can
execute: the modules the Layer 2 entries (``text.candidate``, ``text.controller``,
the per-group ``orchestration.group_worker`` and its runner, the language review
plugins, ``tools/ops/run.py`` and the unified preflight) import, the host code that
binds the text layer's ports, the schemas those modules read and the shared
terminology table. The list is traced statically by
``tools/development/layer2_code_closure.py``; ``tests/test_layer2_code_closure.py``
fails when a file is missing or when the import graph and the manifest differ, so a
new dependency has to be reviewed into the closure instead of entering it unseen.

Before 2026-10-24 the identity hashed every ``scripts/**/*.py``,
``packages/production/src/**/*.py`` and ``schemas/*.json``, so any commit changed
it (docs/design/codebase-complexity-and-identity-scope.zh.md §3.1, backlog
``DEV-GOV-002``). Runs frozen on that identity keep it; new runs bind this manifest.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST = 'config/layer2-code-closure.json'
SCHEMA = 'sermon-layer2-code-closure-v1'


def load(root: Path) -> dict:
    """The manifest as written, after a shape check."""
    value = json.loads((Path(root) / MANIFEST).read_text(encoding='utf-8'))
    if not (isinstance(value, dict) and value.get('schemaVersion') == SCHEMA
            and isinstance(value.get('files'), list) and value['files']
            and all(_relative(name) for name in value['files'])):
        raise ValueError('invalid_layer2_code_closure')
    return value


def _relative(name) -> bool:
    return (isinstance(name, str) and bool(name) and not name.startswith('/')
            and '..' not in Path(name).parts and '\\' not in name)


def files(root: Path) -> tuple[str, ...]:
    """Repository-relative paths of the closure, the manifest itself included, sorted."""
    return tuple(sorted(set(load(root)['files']) | {MANIFEST}))


def paths(root: Path) -> tuple[Path, ...]:
    root = Path(root)
    return tuple(root / name for name in files(root))


def manifest_sha256(root: Path) -> str:
    return hashlib.sha256((Path(root) / MANIFEST).read_bytes()).hexdigest()
