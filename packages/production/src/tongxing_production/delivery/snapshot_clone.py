"""Stage a Hosting snapshot tree by cloning it, not by duplicating its bytes.

One weekly snapshot is 2.9 GB, mostly the episode audio, and a publish run stages several of
them (baseline, stage1, stage2, the English reference). A byte-for-byte copy costs 2.9 GB each:
the 2026-11-15 run left six trees and 17 GB under ``artifacts/``. ``cp -Rc`` asks APFS for a
clone instead -- the copy reads as an ordinary directory, a write to either tree allocates new
blocks for the bytes it touches, and the untouched bytes stay shared. (Measured on this
machine: copying a 300 MB file costs ~1 MB, a plain copy costs 300 MB.)

A clone is a copy, not a hardlink: writing into the clone cannot reach the source, which is
what the staging writers rely on when they overlay catalogs and new assets on a baseline.
Where clonefile is unavailable the helper falls back to ``shutil.copytree``, so the caller
keeps identical behaviour at the cost of the duplicate bytes.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def clone_tree(source, target):
    """Copy ``source`` to a new ``target`` tree, sharing blocks with APFS when available."""
    source, target = Path(source), Path(target)
    if target.exists():
        raise FileExistsError(str(target))
    if sys.platform == 'darwin' and shutil.which('cp'):
        try:
            subprocess.run(['cp', '-Rc', str(source), str(target)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return target
        except (OSError, subprocess.CalledProcessError):
            if target.exists():
                shutil.rmtree(target)  # never hand the caller a half-written tree
    shutil.copytree(source, target)
    return target
