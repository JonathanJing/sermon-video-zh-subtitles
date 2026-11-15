import subprocess

import pytest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery import snapshot_clone


def test_clone_tree_copies_the_tree_and_isolates_writes(tmp_path):
    source = tmp_path / 'source'
    (source / 'media').mkdir(parents=True)
    (source / 'catalog.json').write_bytes(b'{"pages": []}')
    (source / 'media' / 'episode.mp3').write_bytes(b'audio-bytes')

    target = snapshot_clone.clone_tree(source, tmp_path / 'target')

    assert (target / 'catalog.json').read_bytes() == b'{"pages": []}'
    assert (target / 'media' / 'episode.mp3').read_bytes() == b'audio-bytes'
    # A clone is still a copy: staging overlays catalogs on the baseline and must not reach it,
    # and an in-place write on the baseline must not reach the staged tree either.
    (target / 'catalog.json').write_bytes(b'{"pages": ["new"]}')
    (source / 'media' / 'episode.mp3').write_bytes(b'replaced-in-place')
    assert (source / 'catalog.json').read_bytes() == b'{"pages": []}'
    assert (target / 'media' / 'episode.mp3').read_bytes() == b'audio-bytes'


def test_clone_tree_refuses_an_existing_target(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a').write_bytes(b'a')
    (tmp_path / 'target').mkdir()
    with pytest.raises(FileExistsError):
        snapshot_clone.clone_tree(source, tmp_path / 'target')


def test_clone_tree_falls_back_to_a_plain_copy_when_clonefile_is_unavailable(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a').write_bytes(b'a')

    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(snapshot_clone.subprocess, 'run', unavailable)
    target = snapshot_clone.clone_tree(source, tmp_path / 'target')
    assert (target / 'a').read_bytes() == b'a'
