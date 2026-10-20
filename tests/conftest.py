import pytest

from tests import tree_paths

# Before any test module imports the package: a worktree's tests import its own sources.
tree_paths.install()


def pytest_report_header(config):
    """Name the package source; warn when ``python -I`` children would import another tree."""
    import subprocess
    import sys
    probe = subprocess.run([sys.executable, '-I', '-c', 'import tongxing_production as p; print(p.__file__)'],
                           capture_output=True, text=True)
    isolated = probe.stdout.strip() or 'not importable'
    lines = [f'tongxing_production: {tree_paths.SOURCES[0]}']
    if not isolated.startswith(str(tree_paths.SOURCES[0])):
        lines.append(f'  children started with python -I import {isolated}; '
                     'run python3 tools/development/worktree_venv.py (CONTRIBUTING.md)')
    return lines


@pytest.fixture(autouse=True)
def no_hosting_propagation_wait(monkeypatch):
    """A positive budget shorter than the retry interval permits one read; real Hosting reads wait for CDN propagation.

    Tests of the waiting itself set the timeout back explicitly."""
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
    from tongxing_production.delivery import publication as guarded_hosting_publish
    monkeypatch.setattr(guarded_hosting_publish, 'PROPAGATION_TIMEOUT_SECONDS', 1.0)
