"""Refuse to start a machine-QC driver on code other than the run froze.

A weekly run records the waiver implementation hash (``machine_quality_waiver.
implementation_sha256``) in its run plan when it starts. Every driver that can
issue or extend a waiver takes ``--expected-implementation <that sha>`` and exits
with code 2 before any model call when the checkout differs, naming the files
whose bytes changed. On 2026-10-11 two unnoticed edits to hashed files
invalidated issued waivers and cost two re-issue rounds; a guard at the entry
turns that into an immediate, explained refusal.

Its package bytes join the physical closure, so changes
to the admission guard invalidate a frozen run.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import backend, waiver

SHA = re.compile(r"[a-f0-9]{64}")
EXIT_CODE = 2


def __getattr__(name):
    if name == "ROOT":
        return backend.current().core.repo_root
    raise AttributeError(name)


def file_hashes(root: Path | None = None) -> dict[str, str]:
    """Each hashed implementation file's own SHA-256, for explaining a mismatch."""
    root = root or backend.current().core.repo_root
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in waiver.IMPLEMENTATION_PHYSICAL_FILES}


def mismatch(expected: str, *, recorded_files: dict[str, str] | None = None, root: Path | None = None) -> dict | None:
    """``None`` when the checkout is the expected implementation; otherwise a
    report with the current hash and, when the run plan recorded per-file hashes,
    the files that differ."""
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError("--expected-implementation must be the 64-hex implementation sha256 the run plan recorded")
    root = root or backend.current().core.repo_root
    current = waiver.implementation_sha256(root)
    if current == expected:
        return None
    files = file_hashes(root)
    changed = sorted(name for name, digest in files.items()
                     if recorded_files is not None and recorded_files.get(name) != digest)
    return {"status": "implementation_mismatch", "expectedImplementationSha256": expected,
            "currentImplementationSha256": current, "files": files,
            "changedFiles": changed if recorded_files is not None else None,
            "exitCode": EXIT_CODE,
            "advice": "Run the driver from the checkout the run plan froze, or start a new run plan on this code."}



def add_argument(parser) -> None:
    parser.add_argument("--expected-implementation", metavar="SHA256",
                        help="Refuse to run unless machine_quality_waiver.implementation_sha256() equals this "
                             "value from the run plan (exit 2 before any model call)")


def closure_files(root: Path | None = None) -> list[Path]:
    """List every physical file used for frozen-code synchronization."""
    return [Path(name) for name in waiver.IMPLEMENTATION_PHYSICAL_FILES]
