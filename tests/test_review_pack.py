"""tools/ops/review_pack.py: static review pack from a sentence-first run (no network)."""
import argparse
import json
from pathlib import Path

import pytest

from tools.ops import review_pack


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                    encoding="utf-8")


def make_run(root: Path, *, audio: bool = True) -> Path:
    run = root / "20261108-demo-zh"
    run.mkdir(parents=True)
    write_jsonl(run / "sentences.jsonl", [
        {"id": "s0001", "english": "Sure.", "start": 0.0, "end": 0.6, "sourceUnitId": "u0001"},
        {"id": "s0002", "english": "Here we go.", "start": 0.6, "end": 1.3,
         "sourceUnitId": "u0002", "speakerReview": "check"},
        {"id": "s0003", "english": "Chapter 3, verse 12.", "start": 1.3, "end": 3.0,
         "sourceUnitId": "u0003"},
    ])
    write_jsonl(run / "translations.jsonl", [
        {"id": "s0001", "locale": "zh-Hans", "target": "好的。", "reviewNote": "pass"},
        {"id": "s0002", "locale": "zh-Hans", "target": "开始吧。", "reviewNote": "revised: 精简"},
        {"id": "s0003", "locale": "zh-Hans", "target": "三章十二节。", "reviewNote": "pass"},
    ])
    write_jsonl(run / "speech.jsonl", [
        {"id": "s0001", "spokenText": "好的。", "speaker": "demo", "budgetSeconds": 0.6},
        {"id": "s0002", "spokenText": "开始吧。", "speaker": "demo", "budgetSeconds": 0.7},
        {"id": "s0003", "spokenText": "第三章 12 节。", "speaker": "demo", "budgetSeconds": 1.7},
    ])
    (run / "schedule.json").write_text(json.dumps({"summary": {}, "sentences": [
        {"id": "s0001", "actualStart": 0.0, "dubSeconds": 0.8, "lagSeconds": 0.0},
        {"id": "s0002", "actualStart": 0.8, "dubSeconds": 0.9, "lagSeconds": 1.2},
        {"id": "s0003", "actualStart": 1.7, "dubSeconds": 2.0, "lagSeconds": 0.1},
    ]}), encoding="utf-8")
    (run / "review.json").write_text(json.dumps({
        "revisions": {}, "notes": {"s0003": "note: 章号读法核对"},
    }), encoding="utf-8")
    (run / "decisions.json").write_text(json.dumps({
        "title": "演示证道", "sync": True, "clipSeconds": 3.0,
    }, ensure_ascii=False), encoding="utf-8")
    (run / "clip.json").write_text(json.dumps({"media": "/tmp/media.mp4", "windowStart": 0.0}),
                                  encoding="utf-8")
    if audio:
        (run / "review.mp3").write_bytes(b"ID3demo" * 32)
    return run


def build(run: Path, out: Path, **overrides) -> dict:
    options = dict(run=str(run), locale="zh-Hans", out=str(out), checkpoint="audio",
                   title=None, production_id=None, code=None, clips=0,
                   built_at="2026-11-16T00:00:00+00:00")
    options.update(overrides)
    pack = review_pack.build(argparse.Namespace(**options))
    return pack


def test_text_pack_has_no_audio_and_no_track(tmp_path):
    run = make_run(tmp_path, audio=False)
    pack = build(run, tmp_path / "out", checkpoint="text")
    assert pack["schemaVersion"] == review_pack.SCHEMA
    assert pack["checkpoint"] == "text"
    assert pack["track"] is None
    assert not (tmp_path / "out" / "audio" / "review.mp3").exists()
    assert (tmp_path / "out" / "index.html").exists()
    assert (tmp_path / "out" / "app.js").exists()
    assert (tmp_path / "out" / "styles.css").exists()


def test_audio_checkpoint_binds_the_track_hash(tmp_path):
    run = make_run(tmp_path)
    pack = build(run, tmp_path / "out")
    copied = tmp_path / "out" / "audio" / "review.mp3"
    assert copied.read_bytes() == (run / "review.mp3").read_bytes()
    assert pack["track"]["sha256"] == review_pack.sha256_file(copied)
    assert pack["track"]["bytes"] == copied.stat().st_size


def test_audio_checkpoint_without_track_fails(tmp_path):
    run = make_run(tmp_path, audio=False)
    with pytest.raises(SystemExit):
        build(run, tmp_path / "out")


def test_flags_cover_every_reason(tmp_path):
    run = make_run(tmp_path)
    pack = build(run, tmp_path / "out")
    flags = {row["id"]: row["flags"] for row in pack["sentences"]}
    assert flags["s0001"] == []
    assert "revised" in flags["s0002"] and "speaker" in flags["s0002"] and "lag" in flags["s0002"]
    assert "note" in flags["s0003"] and "digits" in flags["s0003"] and "spoken" in flags["s0003"]
    assert pack["counts"] == {"sentences": 3, "flagged": 2, "clips": 0}


def test_rows_carry_both_clocks(tmp_path):
    run = make_run(tmp_path)
    pack = build(run, tmp_path / "out")
    second = pack["sentences"][1]
    assert second["start"] == 0.6 and second["end"] == 1.3      # source window
    assert second["dubStart"] == 0.8 and second["dubSeconds"] == 0.9  # dub track
    assert second["spoken"] == "开始吧。"
    assert second["english"] == "Here we go."


def test_code_is_stable_and_short(tmp_path):
    run = make_run(tmp_path)
    first = build(run, tmp_path / "a")
    second = build(run, tmp_path / "b")
    assert first["code"] == second["code"]
    assert len(first["code"]) == 4
    assert first["code"].isalnum()
    assert build(run, tmp_path / "c", code="ZX9Q")["code"] == "ZX9Q"


def test_pack_json_is_written_sorted_and_compact(tmp_path):
    run = make_run(tmp_path)
    build(run, tmp_path / "out")
    text = (tmp_path / "out" / "pack.json").read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert '": ' not in text          # compact separators
    assert text.index('"checkpoint"') < text.index('"code"')  # sort_keys


def test_missing_sentences_is_a_clear_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit) as error:
        build(empty, tmp_path / "out")
    assert "sentences.jsonl" in str(error.value)
