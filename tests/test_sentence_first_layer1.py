"""The Layer 1 scripts of the sentence-first route: transcribe, sentence table, review rows, English package."""
import json
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "sentence-first-agent"))
import l1_anchor  # noqa: E402
import l1_english_source  # noqa: E402
import l1_review_rows  # noqa: E402
import l1_transcribe  # noqa: E402
from weekly_auto_helpers import SENTENCES, make_raw, write_transcript, write_wav  # noqa: E402

SHA = "ab" * 32


def build(tmp_path, *extra, sentences=SENTENCES):
    raw = write_transcript(tmp_path, sentences)
    out = tmp_path / "candidate"
    l1_anchor.main(["build", "--raw", str(tmp_path / "raw-whisper.json"), "--media-sha256", SHA, "--media-duration", str(raw["duration"]),
                    "--out", str(out), "--source-url", "https://example.invalid/folder", "--date", "2026-11-29",
                    "--speaker-source", "single speaker; test", "--text-chunks", str(tmp_path / "gpt-4o-chunks.json"), *extra])
    return json.loads((out / "anchor-manifest.json").read_text()), out


def test_units_follow_sentence_ends_and_keep_word_times(tmp_path):
    manifest, out = build(tmp_path)
    units = manifest["sourceUnits"]
    assert [u["english"] for u in units] == SENTENCES
    assert [u["sourceUnitId"] for u in units] == [f"u{i:04d}" for i in range(1, len(SENTENCES) + 1)]
    assert units[0]["start"] == 1.0 and units[0]["words"][0] == {"text": "Good", "start": 1.0, "end": 1.3}
    assert all(u["boundary"]["pauseAfterSeconds"] > 0 for u in units[:-1]) and units[-1]["boundary"]["pauseAfterSeconds"] == 0
    assert manifest["status"] == "machine_anchor_candidate_requires_review" and manifest["releaseEligible"] is False
    assert manifest["input"]["mediaSha256"] == SHA and manifest["counts"] == {"sourceUnits": 7, "sourceWords": 47}
    summary = json.loads((out / "layer1-summary.json").read_text())
    assert summary["anchorManifestJsonSha256"] == l1_anchor.json_sha(manifest)
    assert (out / "english-review.csv").read_text(encoding="utf-8-sig").splitlines()[1].startswith("s0001,u0001,1.00,")


def test_a_long_sentence_is_split_at_its_longest_pause():
    words = [{"text": f"w{i}", "start": i * 1.0 + (3.0 if i >= 8 else 0.0), "end": i * 1.0 + 0.5 + (3.0 if i >= 8 else 0.0)} for i in range(16)]
    words[-1]["text"] = "end."
    groups = l1_anchor.sentences(words, 12.0)
    assert [len(g) for g in groups] == [8, 8]


def test_second_pass_marks_only_the_units_the_two_passes_read_differently(tmp_path):
    _, out = build(tmp_path)
    check = json.loads((out / "english-crosscheck.json").read_text())["units"]
    assert [unit for unit, row in check.items() if not row["agrees"]] == ["u0004"]
    assert "who's at the center of it all" in check["u0004"]["secondPass"]
    assert check["u0001"] == {"secondPass": "Good evening, everyone, and welcome.", "agrees": True}


def test_machine_fixes_merge_drop_and_renumber(tmp_path):
    fixes = tmp_path / "fixes.json"
    fixes.write_text(json.dumps({"global": [{"pattern": r"\b12\b", "replacement": "twelve"}],
                                 "text": {"u0005": [{"pattern": "walls", "replacement": "walls or the gold"}]},
                                 "merge": [["u0001", "u0002"]], "drop": ["u0007"]}))
    manifest, out = build(tmp_path, "--fixes", str(fixes))
    english = [u["english"] for u in manifest["sourceUnits"]]
    assert english[0] == "Good evening, everyone, and welcome. We are continuing our series in chapter 21."
    assert english[1] == "The writer says the city had twelve gates." and english[3] == "It is not the walls or the gold."
    assert len(english) == 5 and [u["sourceUnitId"] for u in manifest["sourceUnits"]] == ["u0001", "u0002", "u0003", "u0004", "u0005"]
    applied = json.loads((out / "english-fixes-applied.json").read_text())
    assert applied["merges"][0]["absorbed"] == ["u0002"] and applied["dropped"] == ["u0007"] and len(applied["fixes"]) == 2


def test_reviewer_edits_are_applied_to_the_candidate_they_saw(tmp_path):
    manifest, _ = build(tmp_path)
    edits = {"replace": {"u0003": "The writer says the city had twelve gates."}, "mergeWithPrevious": ["u0005", "u0006"], "drop": ["u0007"]}
    revised, record = l1_anchor.revise_manifest(manifest, edits)
    english = [u["english"] for u in revised["sourceUnits"]]
    assert english == [SENTENCES[0], SENTENCES[1], "The writer says the city had twelve gates.",
                       "And I want you to notice who is at the center. It is not the walls. It means your ordinary work is not wasted."]
    assert revised["sourceUnits"][3]["end"] == manifest["sourceUnits"][5]["end"] and revised["counts"]["sourceUnits"] == 4
    assert record["candidateAnchorManifestJsonSha256"] == l1_anchor.json_sha(manifest) != record["revisedAnchorManifestJsonSha256"]
    assert record["replaced"] == [{"sourceUnitId": "u0003", "before": SENTENCES[2], "after": "The writer says the city had twelve gates."}]
    assert manifest["sourceUnits"][2]["english"] == SENTENCES[2], "the candidate itself is not changed"
    same, untouched = l1_anchor.revise_manifest(manifest, {})
    assert same["sourceUnits"] == manifest["sourceUnits"] and untouched["replaced"] == [] == untouched["merges"]


@pytest.mark.parametrize("edits", [{"mergeWithPrevious": ["u0001"]}, {"mergeWithPrevious": ["u0005"], "drop": ["u0005"]},
                                   {"mergeWithPrevious": ["u0005"], "drop": ["u0004"]}, {"replace": {"u0099": "x"}},
                                   {"replace": {"u0001": "  "}}, {"drop": ["u0099"]}])
def test_edits_that_cannot_be_applied_are_refused(tmp_path, edits):
    manifest, _ = build(tmp_path)
    with pytest.raises(SystemExit):
        l1_anchor.revise_manifest(manifest, edits)


def test_review_rows_flag_what_to_look_at_and_cut_one_clip_per_unit(tmp_path):
    fixes = tmp_path / "fixes.json"
    fixes.write_text(json.dumps({"text": {"u0005": [{"pattern": "walls", "replacement": "walls or the gold"}]}}))
    manifest, out = build(tmp_path, "--fixes", str(fixes))
    write_wav(tmp_path / "source.wav", manifest["input"]["mediaDurationSeconds"])
    review = tmp_path / "review"
    (review / "slices").mkdir(parents=True)
    (review / "slices" / "u0099.wav").write_bytes(b"left over from an earlier candidate")
    l1_review_rows.main(["--manifest", str(out / "anchor-manifest.json"), "--audio", str(tmp_path / "source.wav"), "--out", str(review),
                         "--fixes-applied", str(out / "english-fixes-applied.json"), "--crosscheck", str(out / "english-crosscheck.json"),
                         "--file-name", "x.mp4", "--long-seconds", "2.5"])
    data = json.loads((review / "rows.json").read_text())
    flags = {row["id"]: row["flags"] for row in data["rows"]}
    assert flags["u0002"] == ["number", "long"] and flags["u0003"] == ["number", "long"]
    assert flags["u0004"] == ["disagree", "long"] and flags["u0005"] == ["edited", "disagree"] and flags["u0001"] == []
    row = next(r for r in data["rows"] if r["id"] == "u0005")
    assert row["before"] == "It is not the walls." and row["audio"] == "slices/u0005.wav"
    assert data["summary"]["window"] == {"start": 0.0, "end": manifest["input"]["mediaDurationSeconds"]}
    assert sorted(p.name for p in (review / "slices").glob("*.wav")) == [f"u{i:04d}.wav" for i in range(1, 8)]
    import wave
    with wave.open(str(review / "slices" / "u0001.wav")) as clip:
        assert clip.getnframes() == int(manifest["sourceUnits"][0]["end"] * 16000) - 16000


def decision_record(manifest, **changes):
    decision = {"schemaVersion": "sermon-review-decision-v1", "gateId": "l1.english-review", "kind": "english", "production": "p",
                "locale": None, "revision": 1, "verdict": "approved", "note": "",
                "bindings": {"anchorManifestJsonSha256": l1_anchor.json_sha(manifest), "sourceMediaSha256": SHA},
                "checks": {name: True for name in (*l1_english_source.CHECKS, "window")},
                "payload": {"edits": {}, "heardUnitIds": ["u0001"]}, "idempotencyKey": "k" * 20,
                "client": {"submittedAt": "2026-11-29T04:00:00Z", "userAgent": "t"}}
    decision.update(changes)
    return {"decisionId": "d-1", "receivedAt": "2026-11-29T04:00:05+00:00", "decision": decision,
            "reviewer": {"login": "me@example.com", "name": "Me", "source": "tailscale"}}


def english_source(tmp_path, record, *extra):
    manifest, out = build(tmp_path)
    for name, data in (("upload.mp3", b"mp3"), ("episode.mp4", b"mp4")):
        (tmp_path / name).write_bytes(data)
    (tmp_path / "decision.json").write_text(json.dumps(record(manifest) if callable(record) else record))
    args = ["--anchor", str(out / "anchor-manifest.json"), "--words", str(tmp_path / "words.json"),
            "--raw-text", str(tmp_path / "raw-gpt-4o-transcribe.txt"), "--upload", str(tmp_path / "upload.mp3"),
            "--media", str(tmp_path / "episode.mp4"), "--review-csv", str(out / "english-review.csv"),
            "--decision", str(tmp_path / "decision.json"), "--authority", "config/x.json#a", "--root", str(tmp_path),
            "--out", str(out / "english-source.json"), *extra]
    l1_english_source.main(args)
    return json.loads((out / "english-source.json").read_text()), out, manifest


def test_english_package_binds_the_decision_and_passes_the_published_reference_checks(tmp_path, monkeypatch):
    package, out, manifest = english_source(tmp_path, decision_record)
    assert (package["status"], package["translationEligible"], package["review"]["humanApproval"]) == ("ready_for_translation", True, True)
    assert package["review"]["reviewer"] == "Me (tailscale, review page)" and package["review"]["reviewedAt"] == "2026-11-29T04:00:05+00:00"
    assert package["review"]["decision"]["decisionId"] == "d-1" and package["review"]["decision"]["authority"] == "config/x.json#a"
    assert package["review"]["reviewScope"] == {"mode": "page_checks", "candidateUnits": 7, "heardUnits": 1, "editedUnits": 0,
                                                "lookedAtUnits": 1, "approvedByDefaultUnits": 0, "flaggedUnits": None, "flaggedUnheard": None}
    assert package["source"]["approvedWindow"]["status"] == "approved" and package["source"]["approvedWindow"]["end"] == manifest["input"]["mediaDurationSeconds"]
    # the same requirements tongxing_production.delivery.published_english_reference.build_reference enforces
    reference = pytest.importorskip("tongxing_production.delivery.published_english_reference")
    monkeypatch.chdir(tmp_path)
    reference.read_evidence(package["source"]["approvedWindow"]["evidence"])
    reference.read_evidence(package["transcript"]["artifact"] | {"jsonSha256": l1_anchor.json_sha(json.loads((out / "aligned-words.json").read_text()))})
    anchors = reference.read_evidence(package["anchors"]["artifact"])
    receipt = reference.read_evidence(package["review"]["evidence"])
    ids = [unit["sourceUnitId"] for unit in anchors["sourceUnits"]]
    assert receipt["humanApproval"] is True and all(receipt["checks"][name] == "approved" for name in l1_english_source.CHECKS)
    assert receipt["anchorManifestJsonSha256"] == package["anchors"]["artifact"]["jsonSha256"]
    assert receipt["alignedSegmentsSha256"] == package["transcript"]["artifact"]["sha256"] == package["anchors"]["input"]["mfaSegmentsSha256"]
    assert package["review"]["reviewedSourceUnitIds"] == receipt["reviewedSourceUnitIds"] == ids and len(ids) == package["anchors"]["sourceUnitCount"]
    sys.path.insert(0, str(ROOT / "experiments" / "sentence-first-agent"))
    import preflight
    report = preflight.Report()
    preflight.check_english_package(out / "english-source.json", {"sentences": [{"sourceUnitId": i} for i in ids]}, report, tmp_path)
    assert report.result()["status"] == "pass", report.result()["errors"]


def test_an_approval_without_reviewing_every_sentence_says_how_many_were_approved_by_default(tmp_path):
    def record(manifest):
        value = decision_record(manifest)
        value["decision"]["payload"] = {"edits": {"replace": {"u0003": "The writer says the city had 12 gates, each named."}},
                                        "heardUnitIds": ["u0001", "u0003"],
                                        "approval": {"mode": "default_approve_unreviewed", "units": 7, "heardUnits": 2, "editedUnits": 1,
                                                     "lookedAtUnits": 2, "flaggedUnits": 3, "flaggedUnheard": 2}}
        return value
    package, out, _ = english_source(tmp_path, record)
    receipt = json.loads((out / "english-approval-receipt.json").read_text())
    assert package["review"]["humanApproval"] is True and package["status"] == "ready_for_translation"
    assert receipt["reviewScope"] == {"mode": "default_approve_unreviewed", "candidateUnits": 7, "heardUnits": 2, "editedUnits": 1,
                                      "lookedAtUnits": 2, "approvedByDefaultUnits": 5, "flaggedUnits": 3, "flaggedUnheard": 2}
    assert "其余 5 句按默认批准" in receipt["note"] and len(receipt["reviewedSourceUnitIds"]) == 7


def test_a_rehearsal_writes_the_package_but_approves_nothing(tmp_path):
    package, out, _ = english_source(tmp_path, decision_record, "--rehearsal")
    receipt = json.loads((out / "english-approval-receipt.json").read_text())
    assert (package["status"], package["translationEligible"]) == ("rehearsal_not_for_translation", False)
    assert package["review"]["humanApproval"] is False and receipt["humanApproval"] is False
    assert package["source"]["approvedWindow"]["humanApproval"] is False and package["source"]["approvedWindow"]["status"] == "rehearsal"
    assert set(receipt["checks"].values()) == {"rehearsal"} and "演练" in receipt["note"] and receipt["reviewer"].startswith("rehearsal")


@pytest.mark.parametrize("change", [{"verdict": "changes_requested"}, {"kind": "track"},
                                    {"checks": {"sourceIdentity": True, "transcriptCompleteness": True, "wordAlignment": True,
                                                "sentenceAndPauseBoundaries": True, "window": False}}])
def test_no_package_without_a_full_approval_of_the_english_table(tmp_path, change):
    with pytest.raises(SystemExit):
        english_source(tmp_path, lambda manifest: decision_record(manifest, **change))
    assert not (tmp_path / "candidate" / "english-source.json").exists()


def test_transcription_pays_only_for_what_is_missing(tmp_path, monkeypatch):
    raw = make_raw()
    calls = []

    class Transcriptions:
        def create(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["response_format"] == "verbose_json":
                return types.SimpleNamespace(model_dump=lambda: raw)
            return " ".join(SENTENCES)

    api = types.SimpleNamespace(audio=types.SimpleNamespace(transcriptions=Transcriptions()))
    monkeypatch.setattr(l1_transcribe, "duration", lambda path: raw["duration"])
    monkeypatch.setattr(l1_transcribe.subprocess, "run", lambda command, **kw: Path(command[-1]).write_bytes(b"mp3"))
    (tmp_path / "audio.mp3").write_bytes(b"mp3")
    args = l1_transcribe.build_parser().parse_args(["--audio", str(tmp_path / "audio.mp3"), "--out", str(tmp_path / "layer1"), "--prompt", "names"])
    args.out.mkdir()
    first = l1_transcribe.run_timing(args, api)
    text = l1_transcribe.run_text(args, api)
    assert calls == ["whisper-1", "gpt-4o-transcribe"] and first["words"] == 47 and text["shortChunks"] == []
    usage = json.loads((args.out / "transcribe-usage.json").read_text())["models"]
    assert usage["whisper-1"] == {"audioSeconds": raw["duration"], "calls": 1} and usage["gpt-4o-transcribe"]["calls"] == 1
    assert l1_transcribe.run_timing(args, api)["skipped"] is True and l1_transcribe.run_text(args, api)["chunks"] == 1
    assert calls == ["whisper-1", "gpt-4o-transcribe"], "a rerun sends nothing"
    assert json.loads((args.out / "words.json").read_text())[0] == {"text": "Good", "start": 1.0, "end": 1.3}


def test_chunks_are_cut_at_segment_starts():
    segments = [{"start": float(s), "end": float(s) + 9.0} for s in range(0, 600, 10)]
    windows = l1_transcribe.chunk_windows(600.0, segments, 240.0)
    assert windows == [(0.0, 240.0), (240.0, 480.0), (480.0, 600.0)]
    assert l1_transcribe.chunk_windows(100.0, segments, 240.0) == [(0.0, 100.0)]


def test_transcription_refuses_to_run_without_the_launcher_environment(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_PROJECT_ID", raising=False)
    with pytest.raises(SystemExit):
        l1_transcribe.client()
