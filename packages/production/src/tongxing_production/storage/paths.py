"""Configuration and output path constraints (infrastructure I2).

Extracted from scripts/sermon_release_workflow.py, which imports it back as ``_safe_path``.
"""
import os
from pathlib import Path


def safe_path(path, *, recursive=False):
    """Reject redirected config/output paths, allowing macOS system aliases."""
    path = Path(os.path.abspath(Path(path).expanduser()))
    aliases = {Path('/var'): Path('/private/var'), Path('/tmp'): Path('/private/tmp'), Path('/etc'): Path('/private/etc')}
    for item in (path, *path.parents):
        if item.is_symlink() and not (item in aliases and item.resolve() == aliases[item]):
            raise ValueError("Symlink configuration/output paths are not supported")
    if recursive and path.is_dir() and any(item.is_symlink() for item in path.rglob('*')):
        raise ValueError("Symlink entries in workflow outputs are not supported")
    return path.resolve()
