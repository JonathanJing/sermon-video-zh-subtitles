#!/usr/bin/env python3
"""Run a production package command with this checkout's host bound.

    .venv/bin/python tools/ops/run.py <module> [arguments ...]

<module> is a module under tongxing_production, named without that prefix
(for example ``text.candidate``) and defining ``main()``. The checkout hosts
(scripts/tongxing_host.py, scripts/tracker_projection_host.py) are imported
first, as each scripts/ facade does, then the module's ``main()`` runs with
``sys.argv`` set to ``[<module>, *arguments]``; ``--help`` and every other
argument go to that command, and its return value or SystemExit is the exit
status. Works from any working directory. See docs/design/package-cli-entry.zh.md.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "tongxing_production"
# Bound in this order; the tracker host only configures lazy report ports.
HOSTS = ("scripts.tongxing_host", "scripts.tracker_projection_host")
NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
USAGE = "usage: run.py <module> [arguments ...]    e.g. run.py text.candidate --help"


class UnknownModule(LookupError):
    pass


def bind_host():
    # Run as a script, sys.path[0] is tools/ops; drop it so its files never shadow a module name.
    here = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if not p or Path(p).resolve() != here]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    for name in HOSTS:
        importlib.import_module(name)


def command(name):
    """The ``main`` of ``tongxing_production.<name>``; binds the host before importing it."""
    if not NAME.fullmatch(name):
        raise UnknownModule(f"not a package module name: {name!r}")
    if name.startswith(PACKAGE + "."):
        raise UnknownModule(f"name the module without the {PACKAGE}. prefix: {name[len(PACKAGE) + 1:]}")
    bind_host()
    qualified = f"{PACKAGE}.{name}"
    try:
        spec = importlib.util.find_spec(qualified)
    except ModuleNotFoundError:  # a parent package is missing, or a parent is not a package
        spec = None
    if spec is None:
        raise UnknownModule(f"no module {qualified}")
    if spec.submodule_search_locations is not None:
        raise UnknownModule(f"{qualified} is a package; name one of its modules")
    entry = getattr(importlib.import_module(qualified), "main", None)
    if not callable(entry):
        raise UnknownModule(f"{qualified} has no main()")
    return entry


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE + "\n\n" + __doc__.split("\n\n", 2)[2].strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    name, arguments = argv[0], argv[1:]
    try:
        entry = command(name)
    except UnknownModule as error:
        print(f"{USAGE}\nrun.py: {error}", file=sys.stderr)
        return 2
    sys.argv = [name, *arguments]
    return entry()


if __name__ == "__main__":
    raise SystemExit(main())
