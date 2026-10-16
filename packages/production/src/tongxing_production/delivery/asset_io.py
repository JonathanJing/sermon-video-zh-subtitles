"""Copy frozen Layer 4 bytes into a new staging tree; no approval or publication.

Callers retain their existing upstream validators and candidate transaction.
The expected digest must come from admitted evidence, not a post-copy re-read.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


def copy_bound_asset(source: Path, root: Path, public_path: str, expected_sha256: str) -> dict:
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_sha256):
        raise ValueError('invalid_asset_identity')
    if (not isinstance(public_path, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', public_path)
            or '//' in public_path or any(part in {'.', '..'} for part in public_path.split('/'))
            or public_path.endswith('/')):
        raise ValueError('invalid_public_asset_path')
    root = Path(root).absolute()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('invalid_asset_root')
    destination = root.joinpath(*PurePosixPath(public_path).parts[1:])
    parent = root
    for part in destination.relative_to(root).parts[:-1]:
        parent = parent / part
        parent.mkdir(exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError('invalid_asset_directory')
    if destination.exists() or destination.is_symlink():
        raise ValueError('asset_destination_already_exists')
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    temporary = None
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise ValueError('asset_source_not_regular')
        descriptor, name = tempfile.mkstemp(prefix='.asset-', dir=parent)
        temporary = Path(name)
        digest, size = hashlib.sha256(), 0
        with os.fdopen(descriptor, 'wb') as output:
            while chunk := os.read(source_fd, 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
            output.flush()
            if digest.hexdigest() != expected_sha256:
                raise ValueError('asset_bytes_differ_from_admitted_identity')
            os.fsync(output.fileno())
        # Atomic create-without-overwrite. A collision never replaces another
        # asset. These local staging trees live on a single filesystem.
        os.link(temporary, destination, follow_symlinks=False)
        return {'path': public_path, 'sha256': expected_sha256, 'sizeBytes': size}
    finally:
        os.close(source_fd)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
