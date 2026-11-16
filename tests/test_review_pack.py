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


# ---------------------------------------------------------------- OSS publishing

def oss_args(tmp_path, **overrides):
    values = dict(pack=str(tmp_path / "out"), bucket="tongxing-review-hk",
                  prefix="review/abc123", endpoint=review_pack.DEFAULT_ENDPOINT,
                  config=None, execute=False, show=5)
    values.update(overrides)
    return argparse.Namespace(**values)


def test_canonical_string_is_the_oss_v1_shape():
    text = review_pack.canonical_string(
        "PUT", "", "text/html; charset=utf-8", "Sun, 16 Nov 2026 00:00:00 GMT",
        {"x-oss-object-acl": "public-read"}, "b", "review/x/index.html")
    assert text == ("PUT\n\ntext/html; charset=utf-8\nSun, 16 Nov 2026 00:00:00 GMT\n"
                    "x-oss-object-acl:public-read\n/b/review/x/index.html")


def test_signature_is_stable_base64():
    first = review_pack.oss_signature("secret", "PUT\n\n\n\n/b/k")
    assert first == review_pack.oss_signature("secret", "PUT\n\n\n\n/b/k")
    assert first != review_pack.oss_signature("other", "PUT\n\n\n\n/b/k")
    assert len(first) == 28  # base64 of a 20-byte SHA-1 digest


def test_content_types_cover_the_pack():
    assert review_pack.content_type_for(Path("a/index.html")).startswith("text/html")
    assert review_pack.content_type_for(Path("a/app.js")).startswith("text/javascript")
    assert review_pack.content_type_for(Path("a/audio/review.mp3")) == "audio/mpeg"
    assert review_pack.content_type_for(Path("a/pack.json")).startswith("application/json")
    assert review_pack.content_type_for(Path("a/unknown.bin")) == "application/octet-stream"


def test_object_url_quotes_the_key():
    assert review_pack.object_url("b", "oss-cn-hongkong.aliyuncs.com", "review/a b/c.mp3") == (
        "https://b.oss-cn-hongkong.aliyuncs.com/review/a%20b/c.mp3")


def test_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_ID", "AK")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "SK")
    credentials = review_pack.load_credentials()
    assert credentials.key_id == "AK" and credentials.key_secret == "SK"
    assert "SK" not in repr(credentials)


def test_credentials_from_ossutil_config(tmp_path):
    config = tmp_path / "ossutilconfig"
    config.write_text("[Credentials]\nendpoint=oss-cn-hongkong.aliyuncs.com\n"
                      "accessKeyID=AK2\naccessKeySecret=SK2\n", encoding="utf-8")
    credentials = review_pack.load_credentials(config, environ={})
    assert credentials.key_id == "AK2" and credentials.key_secret == "SK2"


def test_missing_credentials_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit) as error:
        review_pack.load_credentials(tmp_path / "absent", environ={})
    assert "credentials" in str(error.value)


def test_publish_dry_run_makes_no_request(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    build(run, tmp_path / "out", clips=0)
    calls = []
    monkeypatch.setattr(review_pack, "_request", lambda *a, **k: calls.append(a) or (200, {}))
    result = review_pack.publish(oss_args(tmp_path))
    assert result["dryRun"] is True
    assert result["files"] >= 5          # html, js, css, pack.json, audio
    assert result["url"].endswith("/review/abc123/index.html")
    assert calls == []


def test_publish_execute_puts_every_file(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    build(run, tmp_path / "out", clips=0)
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_ID", "AK")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "SK")
    seen = []
    monkeypatch.setattr(review_pack, "_request",
                        lambda method, url, creds, bucket, key, **kw: seen.append((method, key, kw.get("content_type"))) or (200, {}))
    result = review_pack.publish(oss_args(tmp_path, execute=True))
    assert result["dryRun"] is False
    assert len(seen) == result["files"]
    assert all(method == "PUT" for method, _, _ in seen)
    assert ("PUT", "review/abc123/index.html", "text/html; charset=utf-8") in seen


def test_remove_executes_one_delete_per_file(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    build(run, tmp_path / "out", clips=0)
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_ID", "AK")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "SK")
    seen = []
    monkeypatch.setattr(review_pack, "_request",
                        lambda method, url, creds, bucket, key, **kw: seen.append((method, key)) or (204, {}))
    result = review_pack.remove(oss_args(tmp_path, execute=True))
    assert result["deleted"] == len(seen)
    assert all(method == "DELETE" for method, _ in seen)
