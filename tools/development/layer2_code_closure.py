#!/usr/bin/env python3
"""Trace the Layer 2 code closure and write or check ``config/layer2-code-closure.json``.

    python3 tools/development/layer2_code_closure.py --check    # exit 1 and list the difference
    python3 tools/development/layer2_code_closure.py --write    # regenerate the manifest
    python3 tools/development/layer2_code_closure.py --list     # every file with what reached it

The trace is static (``ast``), from the Layer 2 entries, and resolves imports against the
package source, the checkout root (``scripts``, ``tools``, ``backend``) and the API
package. What it follows:

- a module's module-level imports, which Python loads whenever the module loads;
- the function-level imports of Layer 2's own modules (``text/``, the per-group
  ``orchestration/group_*`` modules, the language review plugins and the unified
  preflight), which run when Layer 2 runs; a function-level import elsewhere is on a
  code path Layer 2 does not call, so a module outside Layer 2 that Layer 2 starts
  calling into is added as an entry or moves its import to module level;
- in ``scripts/tongxing_host.py``, the functions and assignments its
  ``text_backend.configure(...)`` call reaches, transitively, with their string-literal
  loaders (``_module('…')``, ``_scripts_module('…')``, ``importlib.import_module('…')``):
  that wiring is how Layer 2 reaches code it does not import itself; plus
  ``ENTRY_LOAD_TIME_IMPORTS`` for entries that are in the closure;
- the other hosts ``tools/ops/run.py`` imports (``scripts.tracker_projection_host``,
  ``scripts.sermon_unified``) by their module-level imports only;
- every ``*.py`` in ``scripts/language_review_plugins/``, as the plugin directory;
- every ``schemas/<name>.schema.json`` that a closure module names as a string literal;
- ``docs/series-terminology.zh.md``, which the translation prompts read.

The manifest is a list of names; the hashes are taken at run time
(``text.controller.code_identity()``, ``text.code_closure``).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'packages/production/src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'packages/production/src'))

from tongxing_production.text import code_closure  # noqa: E402

# Import roots, in the order a bound Layer 2 process searches them ('' is the checkout root).
SEARCH = ('packages/production/src', '', 'services/api/src')
PACKAGE = 'packages/production/src/tongxing_production/'
ENTRIES = (
    PACKAGE + 'text/candidate.py',
    PACKAGE + 'text/controller.py',
    PACKAGE + 'orchestration/group_worker.py',
    PACKAGE + 'orchestration/group_pipeline.py',
    'tools/ops/run.py',
    'tools/ops/sermon_unified_preflight.py',
)
PLUGIN_DIR = 'scripts/language_review_plugins'
# tools/ops/run.py binds these before any package command (its HOSTS and ORCHESTRATION_HOST).
RUN_HOSTS = ('scripts.tongxing_host', 'scripts.tracker_projection_host', 'scripts.sermon_unified')
# Hosts bind every layer's ports: only their module-level imports are followed.
HOSTS = frozenset({'scripts/tongxing_host.py', 'scripts/tracker_projection_host.py',
                   'scripts/sermon_unified/__init__.py', 'tools/ops/run.py'})
TEXT_HOST = 'scripts/tongxing_host.py'
# Layer 2's own modules: their function-level imports run when Layer 2 runs.
FULL_PREFIXES = (PACKAGE + 'text/', PACKAGE + 'orchestration/group_', PLUGIN_DIR + '/',
                 'tools/ops/sermon_unified_preflight.py')
SINGLE = ('docs/series-terminology.zh.md',)
LITERAL_LOADERS = {'import_module': '', '_module': '', '_scripts_module': 'scripts.'}
SCHEMA_NAME = re.compile(r'[a-z0-9][a-z0-9.-]*')


def module_files(name: str, root: Path = ROOT) -> list[str]:
    """The file a dotted module name resolves to, then the ``__init__.py`` of each parent package."""
    parts = name.split('.')
    for search in SEARCH:
        base = root / search if search else root
        leaf = base.joinpath(*parts)
        found = next((c for c in (leaf.with_suffix('.py'), leaf / '__init__.py') if c.is_file()), None)
        if found is None:
            continue
        files = [str(found.relative_to(root))]
        for depth in range(1, len(parts)):
            init = base.joinpath(*parts[:depth]) / '__init__.py'
            if init.is_file():
                files.append(str(init.relative_to(root)))
        return files
    return []


def _package_of(rel: str, root: Path) -> list[str]:
    path = root / rel
    for search in SEARCH:
        base = root / search if search else root
        if path.is_relative_to(base):
            parts = list(path.relative_to(base).with_suffix('').parts)
            return parts[:-1]
    return []


def _module_level(node):
    """Statements and expressions that run when the module loads: everything but function bodies."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _module_level(child)


def _mode(rel: str) -> str:
    return 'module' if rel in HOSTS else 'full' if rel.startswith(FULL_PREFIXES) else 'module'


def imported_names(nodes, rel: str, root: Path) -> list[str]:
    """Dotted module names the given AST nodes import, relative imports resolved."""
    names = []
    for node in nodes:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = _package_of(rel, root)
                package = package[:len(package) - (node.level - 1)] if node.level > 1 else package
                base = '.'.join(package + ([node.module] if node.module else []))
            else:
                base = node.module
            for alias in node.names:
                if alias.name != '*' and module_files(f'{base}.{alias.name}', root):
                    names.append(f'{base}.{alias.name}')  # ``from package import submodule``
                else:
                    names.append(base)
        elif isinstance(node, ast.Call):
            func = node.func
            attr = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if attr in LITERAL_LOADERS and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                names.append(LITERAL_LOADERS[attr] + node.args[0].value)
    return names


def text_wiring(tree: ast.Module) -> list[ast.AST]:
    """The host's functions and assignments that its ``text_backend.configure(...)`` call reaches."""
    definitions, assignments = {}, {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
                elif isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple) \
                        and len(target.elts) == len(node.value.elts):
                    for name, value in zip(target.elts, node.value.elts):
                        if isinstance(name, ast.Name):
                            assignments[name.id] = value
    start = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == 'configure' and isinstance(node.func.value, ast.Name)
             and node.func.value.id == 'text_backend']
    if len(start) != 1:
        raise ValueError(f'{TEXT_HOST}: expected one text_backend.configure(...) call, found {len(start)}')
    seen, pending, selected = set(), list(start), []
    while pending:
        node = pending.pop()
        selected.append(node)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id not in seen:
                seen.add(sub.id)
                if sub.id in definitions:
                    pending.append(definitions[sub.id])
                elif sub.id in assignments:
                    pending.append(assignments[sub.id])
    return selected


def _entry_load_time_imports(tree: ast.Module) -> dict:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ENTRY_LOAD_TIME_IMPORTS'
                                                for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f'{TEXT_HOST}: ENTRY_LOAD_TIME_IMPORTS not found')


def trace(root: Path = ROOT) -> dict[str, str]:
    """Every closure file, mapped to the file (or rule) that reached it first."""
    root = Path(root)
    closure, pending = {}, []

    def add(rel, via):
        if rel not in closure:
            closure[rel] = via
            pending.append(rel)

    for rel in ENTRIES:
        add(rel, 'entry')
    for path in sorted((root / PLUGIN_DIR).glob('*.py')):
        add(str(path.relative_to(root)), 'plugin directory')
    for name in RUN_HOSTS:
        for rel in module_files(name, root):
            add(rel, 'tools/ops/run.py host')
    entry_load_time = {}
    while pending:
        rel = pending.pop()
        if not rel.endswith('.py'):
            continue
        tree = ast.parse((root / rel).read_text(encoding='utf-8'), filename=rel)
        nodes = list(ast.walk(tree)) if _mode(rel) == 'full' else list(_module_level(tree))
        if rel == TEXT_HOST:
            for node in text_wiring(tree):
                nodes.extend(ast.walk(node))
            entry_load_time = _entry_load_time_imports(tree)
        for name in imported_names(nodes, rel, root):
            for target in module_files(name, root):
                add(target, rel)
        if not pending:  # a fixpoint: entries that reached the closure load these at identity capture
            for entry, names in entry_load_time.items():
                found = module_files(entry, root)
                if found and found[0] in closure:
                    for name in names:
                        for target in module_files(name, root):
                            add(target, f'ENTRY_LOAD_TIME_IMPORTS[{entry}]')
    for rel in sorted(name for name in closure if name.endswith('.py')):
        for node in ast.walk(ast.parse((root / rel).read_text(encoding='utf-8'), filename=rel)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literal = node.value
                if literal.endswith('.schema.json') and (root / 'schemas' / literal).is_file():
                    closure.setdefault('schemas/' + literal, rel)
                elif SCHEMA_NAME.fullmatch(literal) and (root / 'schemas' / (literal + '.schema.json')).is_file():
                    closure.setdefault('schemas/' + literal + '.schema.json', rel)
    for rel in SINGLE:
        closure.setdefault(rel, 'single file')
    return closure


def manifest(root: Path = ROOT) -> dict:
    return {
        'schemaVersion': code_closure.SCHEMA,
        'purpose': 'Every repository file a Layer 2 run can execute; text.controller.code_identity() and the '
                   'unified CLI execution admission hash these files and no others.',
        'generator': 'tools/development/layer2_code_closure.py',
        'entries': list(ENTRIES),
        'files': sorted(trace(root)),
    }


def difference(root: Path = ROOT) -> tuple[list[str], list[str]]:
    """(files the trace reaches that the manifest lacks, manifest files the trace no longer reaches)."""
    traced = set(trace(root))
    listed = set(code_closure.load(root)['files'])
    return sorted(traced - listed), sorted(listed - traced)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--write', action='store_true', help=f'write {code_closure.MANIFEST}')
    action.add_argument('--check', action='store_true', help='exit 1 when the manifest differs from the trace')
    action.add_argument('--list', action='store_true', help='print every closure file with what reached it')
    args = parser.parse_args(argv)
    if args.list:
        for rel, via in sorted(trace().items()):
            print(f'{rel}  <- {via}')
        return 0
    if args.write:
        value = manifest()
        (ROOT / code_closure.MANIFEST).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n',
                                                  encoding='utf-8')
        print(f'{code_closure.MANIFEST}: {len(value["files"])} files')
        return 0
    missing, stale = difference()
    for rel in missing:
        print(f'not in manifest: {rel}')
    for rel in stale:
        print(f'no longer reached: {rel}')
    if missing or stale:
        print(f'review the change, then: python3 {Path(__file__).relative_to(ROOT)} --write', file=sys.stderr)
        return 1
    print(f'{code_closure.MANIFEST} matches the traced closure')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
