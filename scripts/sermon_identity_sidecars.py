"""Carry referenced, validated private code identities into derived ledgers."""

import json
from pathlib import Path
import re

from scripts import sermon_accounting as accounting
from scripts import sermon_trace_artifacts as artifacts
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.orchestration import jobs


def rows_in_snapshot(data):
    """Find references in intact rows; canonical readers diagnose bad rows."""
    rows = []
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except (ValueError, UnicodeError):
            pass
    return rows


def collect(source, events):
    """Freeze only sidecars named by workflow starts, before writing an output."""
    references = set()
    for event in events:
        if not isinstance(event, dict) or event.get('event') != 'workflow_started':
            continue
        identity = event.get('executionIdentity')
        if not isinstance(identity, dict):
            # Legacy rows can carry non-object identities. They have no
            # content-addressed reference to preserve.
            continue
        digest = identity.get('loadedProjectCodeManifestSha256')
        if digest is not None:
            # Leave invalid references and conflicts in the byte snapshot so
            # the canonical reader can count the damaged row.
            if (not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
                    or identity.get('loadedProjectCodeSha256') != {}):
                continue
            references.add(digest)
    manifests = {}
    for digest in sorted(references):
        try:
            modules = accounting.load_execution_identity_sidecar(source, digest)
        except (ValueError, UnicodeError, OSError, TypeError):
            # Missing or damaged source sidecars remain absent in the copy;
            # read_event_snapshot diagnoses their referencing rows there.
            continue
        manifests[digest] = json.dumps({
            'schemaVersion': 'sermon-loaded-project-code-v1',
            'loadedProjectCodeSha256': modules,
        }, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return manifests


def write(destination, manifests):
    """Use private, atomic files and check each new reference with the reader."""
    if not manifests:
        return
    folder = Path(destination) / '.execution-identities'
    jobs._reject_link(folder, directory=True)
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.stat().st_mode & 0o077:
        raise ValueError('execution_identity_sidecar_directory_permissions')
    for digest, content in manifests.items():
        artifacts.write(folder / (digest + '.json'), content)
        accounting.load_execution_identity_sidecar(destination, digest)
