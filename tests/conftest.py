import pytest


@pytest.fixture(autouse=True)
def no_hosting_propagation_wait(monkeypatch):
    """A positive budget shorter than the retry interval permits one read; real Hosting reads wait for CDN propagation.

    Tests of the waiting itself set the timeout back explicitly."""
    from scripts import guarded_hosting_publish
    monkeypatch.setattr(guarded_hosting_publish, 'PROPAGATION_TIMEOUT_SECONDS', 1.0)
