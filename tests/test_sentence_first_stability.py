"""Stability fixes on the sentence-first line: job exit lines, audit merge, cache, gate default."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments" / "sentence-first-agent"


def load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    for entry in (str(EXPERIMENTS), str(ROOT), str(ROOT / "packages/production/src")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


def job():
    return load("spark_session_job", EXPERIMENTS / "spark_session_job.py")


def test_exit_line_of_another_job_never_ends_this_one():
    lines = ["tts exit zh-Hans 0 2026-11-18T01:00:00Z job=old-job",
             "tts exit zh-Hans 1 2026-11-18T02:00:00Z job=other-job"]
    assert job().own_exit_line(lines, "tts", "new-job") is None
    lines.append("tts exit zh-Hans 0 2026-11-18T03:00:00Z job=new-job")
    assert job().own_exit_line(lines, "tts", "new-job").endswith("job=new-job")


def test_untagged_log_keeps_the_old_last_line_rule():
    lines = ["tts exit ko 0 2026-11-18T01:00:00Z", "tts exit ko 1 2026-11-18T02:00:00Z"]
    assert job().own_exit_line(lines, "tts", "any").split()[3] == "1"


def test_memory_refusal_counts_as_a_pre_container_stop():
    out = "tts memory admission: need 33 GiB, MemAvailable 20 GiB\ntts refused: MemAvailable 20 GiB is below"
    assert any(word in out for word in job().PRE_CONTAINER_STOPS)


def audit():
    return load("audit_deepseek", EXPERIMENTS / "audit_deepseek.py")


TRANSLATIONS = [{"id": "s0001", "target": "你好"}]


def test_audit_keeps_two_speaker_map_notes_and_earlier_revisions():
    existing = {"locale": "ko", "speakers": {"eric_geiger": "eric_pilot", "steve_bang_lee": "steve_bang_lee"},
                "revisions": {"s0001": {"target": "earlier", "note": "agent"}},
                "notes": {"s0002": "keep"}, "spokenForms": {}}
    review = audit().merged_review(existing, {}, None, "ko",
                                   {"s0001": {"target": "audit", "note": "revised"},
                                    "s0003": {"target": "new", "note": "revised"}}, [], TRANSLATIONS)
    assert review["speakers"] == existing["speakers"] and "speaker" not in review
    assert review["revisions"]["s0001"]["target"] == "earlier"
    assert review["revisions"]["s0003"]["target"] == "new"
    assert review["notes"] == {"s0002": "keep"}
    assert review["rejectedRevisions"][-1]["reason"] == "existing_revision_kept"
    assert review["humanApproval"] is False


def test_audit_refuses_to_guess_a_voice():
    with pytest.raises(SystemExit, match="--speaker"):
        audit().merged_review({}, {}, None, "zh-Hans", {}, [], TRANSLATIONS)
    review = audit().merged_review({}, {}, "steve_bang_lee", "zh-Hans", {}, [], TRANSLATIONS)
    assert review["speaker"] == "steve_bang_lee"


def test_rejected_reply_leaves_the_cache(tmp_path):
    core = load("coherence_core", EXPERIMENTS / "coherence_core.py")
    client = core.DeepSeek(tmp_path / "cache", execute=False, label="translate", state_dir=tmp_path)
    user = {"sentences": [{"id": "s0001"}]}
    path = client._cache_path("system", json.dumps(user, ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"result": {"sentences": []}, "usage": {}}))
    assert client("system", user) == {"sentences": []}
    client.forget("system", user)
    assert not path.exists()
    with pytest.raises(SystemExit, match="--execute"):
        client("system", user)


def gate():
    return load("sfa_publish_gate", ROOT / "tools/ops/sfa_publish_gate.py")


def catalog(default: str) -> dict:
    return {"schemaVersion": "sermon-multilingual-catalog-v5", "defaultPageId": default, "pages": [
        {"id": "sermon-1115", "date": "2026-11-15", "contentKind": "sermon", "title": "S", "targets": {"zh-Hans": {}}},
        {"id": "podcast-1115", "date": "2026-11-15", "contentKind": "podcast", "title": "P", "targets": {"zh-Hans": {}}},
        {"id": "sermon-1108", "date": "2026-11-08", "contentKind": "sermon", "title": "O", "targets": {"zh-Hans": {}}}]}


@pytest.mark.parametrize("page_id", ["sermon-1115", "podcast-1115", "sermon-1108"])
def test_gate_accepts_the_latest_sermon_default_for_any_page(page_id):
    checks = gate().Gate()
    gate().check_catalog(checks, catalog("sermon-1115"), page_id)
    row = next(check for check in checks.checks if check["check"] == "catalog.defaultPageId")
    assert row["ok"], row


def test_gate_rejects_a_podcast_default():
    checks = gate().Gate()
    gate().check_catalog(checks, catalog("podcast-1115"), "podcast-1115")
    row = next(check for check in checks.checks if check["check"] == "catalog.defaultPageId")
    assert not row["ok"] and "sermon-1115" in row["detail"]


def test_legacy_driver_exits_non_zero_on_a_failed_readback():
    driver = load("publish_podcast_page", EXPERIMENTS / "publish_podcast_page.py")
    assert driver.failed({"pass": False, "checks": {}})
    assert driver.failed({"status": "fail", "checks": 3})
    assert not driver.failed({"pass": True})
    assert not driver.failed({"status": "deployed"})
