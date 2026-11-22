"""sfa_publish content carries the source window the field-audio alignment binder needs."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "sentence-first-agent"))
sys.path.insert(0, str(HERE / "packages" / "production" / "src"))

import sfa_publish as PUB  # noqa: E402
from tongxing_production.delivery.published_alignment_catalog import _window_matches  # noqa: E402


def test_source_window_block_shape():
    block = PUB.source_window_block(0.0, 2144.107333, "a" * 64)
    assert block == {"schemaVersion": "sermon-original-recording-window-v1",
                     "mediaSha256": "a" * 64, "startSeconds": 0.0, "endSeconds": 2144.107333}


def test_alignment_binder_accepts_the_block():
    media = "b" * 64
    block = PUB.source_window_block(0.0, 120.5, media)
    assert _window_matches(block, media, 0.0, 120.5, 120.5)


def test_alignment_binder_rejects_a_different_media():
    block = PUB.source_window_block(0.0, 120.5, "c" * 64)
    assert not _window_matches(block, "d" * 64, 0.0, 120.5, 120.5)


def test_alignment_binder_still_accepts_content_without_the_block():
    # pages published before this fix carry no sourceWindow; 0..duration is their window
    assert _window_matches(None, "e" * 64, 0.0, 2144.107333, 2144.107333)
    assert not _window_matches(None, "e" * 64, 0.0, 2144.107, 2144.107333)
