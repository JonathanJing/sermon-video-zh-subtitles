from __future__ import annotations

from dataclasses import replace

import pytest

from tools.ops.production_path_sim import (
    Resource,
    SCENARIOS,
    simulate,
    simulate_once,
)


def test_resource_serializes_single_capacity() -> None:
    resource = Resource(1)
    assert resource.earliest(0, 5) == 0
    resource.reserve(0, 5)
    assert resource.earliest(0, 3) == 5
    assert resource.earliest(2, 3) == 5


def test_family_page_waits_for_all_locales() -> None:
    family = simulate_once(SCENARIOS["batch_family_clean"], seed=1)
    separate = simulate_once(SCENARIOS["batch_separate_clean"], seed=1)
    assert family.first_page > separate.first_page


def test_streaming_beats_barrier_for_first_page() -> None:
    batch = simulate_once(SCENARIOS["batch_separate_clean"], seed=1)
    stream = simulate_once(SCENARIOS["stream_separate"], seed=1)
    assert stream.first_page < batch.first_page


def test_text_first_page_comes_before_audio() -> None:
    result = simulate_once(SCENARIOS["stream_textfirst"], seed=1)
    first_audio = min(result.pages.values())
    assert result.first_page < first_audio
    assert result.text_pages


def test_full_audio_review_adds_about_thirty_minutes() -> None:
    spot = simulate_once(SCENARIOS["stream_separate"], seed=1)
    full = simulate_once(
        replace(SCENARIOS["stream_separate"], audio_review="full"), seed=1
    )
    assert full.first_page - spot.first_page == pytest.approx(30.0, abs=0.2)


def test_calibrated_actual_matches_observed_158_minutes() -> None:
    result = simulate_once(SCENARIOS["batch_family_actual"], seed=1)
    assert 155.0 <= result.first_page <= 162.0


def test_group_rework_has_a_shorter_tail_than_whole_rework() -> None:
    batch = simulate(SCENARIOS["batch_family_rework"], trials=120, seed=7)
    stream = simulate(SCENARIOS["stream_separate"], trials=120, seed=7)
    assert stream["first_p90"] < batch["first_p90"]
    assert stream["first_p90"] < 75.0


def test_machine_checked_text_first_is_faster_than_reviewed() -> None:
    reviewed = simulate_once(SCENARIOS["stream_textfirst"], seed=1)
    machine = simulate_once(
        replace(SCENARIOS["stream_textfirst"], text_review=False), seed=1
    )
    assert machine.first_page < reviewed.first_page
