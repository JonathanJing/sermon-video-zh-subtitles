import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_full_sermon_dataset_preparation as subject


def test_default_selection_is_train_and_dev_and_can_select_all():
    rows = [
        {"videoId": "a", "split": "train"},
        {"videoId": "b", "split": "test"},
        {"videoId": "c", "split": "dev"},
        {"videoId": "d", "split": "poc"},
    ]
    selected = subject.select_assignments(
        rows, splits={"train", "dev"}, video_ids=[], max_videos=0
    )
    assert [row["videoId"] for row in selected] == ["a", "c"]


def test_plan_estimates_audio_cost(tmp_path):
    manifest = tmp_path / "splits.json"
    manifest.write_text('{"assignments": []}\n', encoding="utf-8")
    existing = tmp_path / "segments"
    calibration = tmp_path / "calibration" / "v"
    calibration.mkdir(parents=True)
    for video_id, duration_ms in (("a", 2_400_000), ("b", 1_200_000)):
        path = existing / video_id / "segments.en.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({
                "id": f"{video_id}_seg_0001",
                "startMs": 0,
                "endMs": duration_ms,
                "en": "Caption source.",
            }) + "\n",
            encoding="utf-8",
        )
    (calibration / "model-second-pass-audit.jsonl").write_text(
        "".join(json.dumps({"severity": value}) + "\n" for value in [
            "pass", "pass", "pass", "needs_audio_review"
        ]),
        encoding="utf-8",
    )
    plan = subject.build_plan(
        [
            {"videoId": "a", "split": "train", "durationSeconds": 3600},
            {"videoId": "b", "split": "dev", "durationSeconds": 1800},
        ],
        split_manifest=manifest,
        raw_root=tmp_path / "raw",
        existing_segment_root=existing,
        calibration_root=tmp_path / "calibration",
        asr_price_per_minute=0.0045,
        audio_audit_sample_rate=0.05,
    )
    assert plan["selectedVideoCount"] == 2
    assert plan["durationHours"] == 1.5
    assert plan["fullAudioUpperBoundCostUsd"] == 0.4
    assert plan["selectiveAudioAudit"]["observedNeedsAudioReviewRate"] == 0.25
    assert plan["selectiveAudioAudit"]["preTeacherSelectedSegmentShare"] == 1.0
    assert plan["selectiveAudioAudit"]["preTeacherSelectedDurationShare"] == 1.0
    assert plan["selectiveAudioAudit"]["projectedAuditMinutes"] == 60.0
    assert plan["selectiveAudioAudit"]["projectedAsrCostUsd"] == 0.27
    assert plan["teacherModels"]["reviewer"] == {
        "model": "gpt-5.6-sol",
        "reasoningEffort": "high",
    }


def test_audio_commands_are_public_bounded_and_mono(tmp_path):
    download = subject.audio_download_command(
        yt_dlp="yt-dlp",
        url="https://www.youtube.com/watch?v=abc",
        output_template=tmp_path / "abc.%(ext)s",
    )
    assert "--no-playlist" in download
    assert "--cookies-from-browser" not in download
    assert download[download.index("-f") + 1] == "ba/bestaudio"
    assert download[-1].startswith("https://www.youtube.com/")

    fallback = subject.audio_download_command(
        yt_dlp="yt-dlp",
        url="https://www.youtube.com/watch?v=abc",
        output_template=tmp_path / "abc.%(ext)s",
        format_selector="18",
    )
    assert fallback[fallback.index("-f") + 1] == "18"
    assert "--cookies-from-browser" not in fallback

    mobile_web = subject.audio_download_command(
        yt_dlp="yt-dlp",
        url="https://www.youtube.com/watch?v=abc",
        output_template=tmp_path / "abc.%(ext)s",
        format_selector="18",
        extractor_args="youtube:player_client=mweb",
    )
    assert mobile_web[mobile_web.index("-f") + 1] == "18"
    assert mobile_web[mobile_web.index("--extractor-args") + 1] == (
        "youtube:player_client=mweb"
    )
    assert "--cookies-from-browser" not in mobile_web

    embedded = subject.audio_download_command(
        yt_dlp="yt-dlp",
        url="https://www.youtube.com/watch?v=abc",
        output_template=tmp_path / "abc.%(ext)s",
        format_selector="140/251/ba/bestaudio",
        extractor_args="youtube:player_client=web_embedded",
    )
    assert embedded[embedded.index("--extractor-args") + 1] == (
        "youtube:player_client=web_embedded"
    )
    assert "--cookies-from-browser" not in embedded

    clip = subject.clip_command(
        ffmpeg="ffmpeg",
        audio_path=tmp_path / "abc.m4a",
        clip_path=tmp_path / "seg.mp3",
        start_ms=1000,
        end_ms=26000,
    )
    assert clip[clip.index("-ac") + 1] == "1"
    assert clip[clip.index("-ar") + 1] == "16000"
    assert clip[clip.index("-t") + 1] == "25.000"


def test_asr_quality_excludes_empty_and_flags_disagreement():
    empty = subject.asr_quality("God is good and faithful.", "", 20)
    assert empty["status"] == "excluded"
    assert "asr_text_too_short" in empty["fatalIssues"]

    mismatch = subject.asr_quality(
        "God is good and faithful to every generation.",
        "Today we are reading a completely different sentence.",
        20,
    )
    assert mismatch["status"] == "pass_with_warning"
    assert "caption_asr_disagreement" in mismatch["warnings"]


def test_caption_source_is_primary_and_never_human_gold(tmp_path):
    source_dir = tmp_path / "source"
    report = subject.materialize_caption_source(
        assignment={"videoId": "v", "split": "train", "durationSeconds": 25},
        manifest={"asset": {"title": "Sermon"}},
        segments=[{
            "id": "v_seg_0001",
            "sermonId": "v",
            "startMs": 0,
            "endMs": 25000,
            "en": "God is good and faithful to us today.",
        }],
        source_dir=source_dir,
        segment_origin="test",
    )
    row = json.loads((source_dir / "segments.en.jsonl").read_text(encoding="utf-8"))
    assert row["en"] == "God is good and faithful to us today."
    assert row["sourceReviewStatus"] == "youtube_caption_primary_model_unreviewed"
    assert report["audioDownloaded"] is False
    assert report["gptTranscribeCalled"] is False
    assert report["humanApprovalClaimed"] is False
    assert report["sourceQualityDisposition"] == "requires_source_reconciliation"
    assert report["teacherPipelineEligibility"] == "blocked"


def test_caption_quality_profile_allows_normal_density_and_blocks_sparse_share():
    normal = [
        {"startMs": 0, "endMs": 10_000, "en": " ".join(["word"] * 20)},
        {"startMs": 10_000, "endMs": 20_000, "en": " ".join(["word"] * 20)},
    ]
    assert subject.caption_quality_profile(normal)["disposition"] == "teacher_ready"

    sparse = [
        {"startMs": 0, "endMs": 10_000, "en": "few words"},
        *normal,
    ]
    profile = subject.caption_quality_profile(sparse)
    assert profile["sparseSegmentCount"] == 1
    assert profile["disposition"] == "requires_source_reconciliation"


def test_teacher_gate_fails_closed_for_sparse_source():
    subject.require_teacher_ready_source(
        {"sourceQualityDisposition": "teacher_ready"}, "ready-video"
    )
    with pytest.raises(RuntimeError, match="requires reconciliation"):
        subject.require_teacher_ready_source(
            {"sourceQualityDisposition": "requires_source_reconciliation"}, "sparse-video"
        )


def test_selective_audio_audit_promotes_supported_caption_without_replacing_source(tmp_path):
    audio = tmp_path / "audio.m4a"
    clip = tmp_path / "clip.mp3"
    transcript = tmp_path / "chunk.txt"
    audio.write_bytes(b"audio")
    clip.write_bytes(b"clip")
    transcript.write_text("God is good and faithful to us today.\n", encoding="utf-8")
    teacher_dir = tmp_path / "teacher"
    result = SimpleNamespace(
        chunk_index=0,
        transcript_txt_path=str(transcript),
        status="transcribed",
    )
    final = [{
            "id": "v_seg_0001",
            "sermonId": "v",
            "startMs": 0,
            "endMs": 25000,
            "en": "God is good and faithful to us today.",
            "captionEn": "God is good and faithful to us today.",
            "zh": "神今天对我们良善信实。",
            "severity": "needs_audio_review",
            "audioAuditReasons": ["sol_needs_audio_review"],
        }]
    report = subject.materialize_selective_audio_audit(
        final_segments=final,
        selected_segments=final,
        chunks=[{
            "chunk_path": str(clip),
            "duration_seconds": 25,
            "start_seconds": 0,
            "end_seconds": 25,
        }],
        transcript_results=[result],
        teacher_dir=teacher_dir,
        audio_path=audio,
        asr_model="gpt-transcribe",
        credential_source="existing_env_file",
        input_profile_sha256="profile-sha",
    )
    row = json.loads((teacher_dir / "segments.selective-audio-audited.jsonl").read_text(encoding="utf-8"))
    assert row["en"] == "God is good and faithful to us today."
    assert row["audioAudit"]["gptTranscribeEn"] == "God is good and faithful to us today."
    assert row["audioAudit"]["audioEvidence"]["humanListeningCompleted"] is False
    assert row["datasetCandidateEligibility"] == "candidate"
    assert row["reviewStatus"] == "audio_audit_supported_model_candidate"
    assert report["humanApprovalClaimed"] is False
    assert report["inputProfileSha256"] == "profile-sha"
    assert report["trainingEligibility"] == "blocked"


def test_selective_audio_audit_excludes_caption_asr_disagreement(tmp_path):
    audio = tmp_path / "audio.m4a"
    clip = tmp_path / "clip.mp3"
    transcript = tmp_path / "chunk.txt"
    audio.write_bytes(b"audio")
    clip.write_bytes(b"clip")
    transcript.write_text(
        "Today we are discussing a completely unrelated sentence.\n", encoding="utf-8"
    )
    segment = {
        "id": "v_seg_0001",
        "sermonId": "v",
        "startMs": 0,
        "endMs": 25_000,
        "en": "God is good and faithful to us today.",
        "captionEn": "God is good and faithful to us today.",
        "zh": "神今天对我们良善信实。",
        "severity": "needs_audio_review",
        "audioAuditReasons": ["sol_needs_audio_review"],
    }
    result = SimpleNamespace(
        chunk_index=0, transcript_txt_path=str(transcript), status="transcribed"
    )
    teacher_dir = tmp_path / "teacher"
    subject.materialize_selective_audio_audit(
        final_segments=[segment],
        selected_segments=[segment],
        chunks=[{
            "chunk_path": str(clip),
            "duration_seconds": 25,
            "start_seconds": 0,
            "end_seconds": 25,
        }],
        transcript_results=[result],
        teacher_dir=teacher_dir,
        audio_path=audio,
        asr_model="gpt-transcribe",
        credential_source="existing_env_file",
        input_profile_sha256="profile-sha",
    )
    row = json.loads((teacher_dir / "segments.selective-audio-audited.jsonl").read_text())
    assert row["datasetCandidateEligibility"] == "excluded"
    assert row["reviewStatus"] == "excluded_requires_source_reconciliation"
    assert "caption_asr_disagreement_unresolved" in row["trainingBlockers"]


def test_selective_audio_audit_keeps_unselected_pass_as_model_candidate(tmp_path):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"audio")
    selected = {
        "id": "v_seg_0001",
        "sermonId": "v",
        "startMs": 0,
        "endMs": 25_000,
        "en": "God is good and faithful to us today.",
        "zh": "神今天对我们良善信实。",
        "severity": "pass",
    }
    teacher_dir = tmp_path / "teacher"
    subject.materialize_selective_audio_audit(
        final_segments=[selected],
        selected_segments=[],
        chunks=[],
        transcript_results=[],
        teacher_dir=teacher_dir,
        audio_path=audio,
        asr_model="gpt-transcribe",
        credential_source="existing_env_file",
        input_profile_sha256="profile-sha",
    )
    row = json.loads(
        (teacher_dir / "segments.selective-audio-audited.jsonl").read_text(encoding="utf-8")
    )
    assert row["audioAuditStatus"] == "not_selected_by_policy"
    assert row["datasetCandidateEligibility"] == "candidate"
    assert row["trainingEligibility"] == "blocked"


def test_audio_selection_uses_sol_flags_and_stable_pass_sample():
    risky = {
        "id": "risk",
        "startMs": 0,
        "endMs": 20_000,
        "en": "This is an ordinary sentence with enough words for a normal speaking rate.",
        "severity": "needs_audio_review",
    }
    assert "sol_needs_audio_review" in subject.audio_audit_reasons(risky, sample_rate=0)
    passed = {**risky, "id": "pass", "severity": "pass"}
    first = subject.audio_audit_reasons(passed, sample_rate=0.5)
    second = subject.audio_audit_reasons(passed, sample_rate=0.5)
    assert first == second


def test_teacher_command_pins_terra_and_sol_high(tmp_path):
    command = subject.teacher_command(
        python="python3",
        video_id="v",
        source_root=tmp_path / "source",
        out_root=tmp_path / "out",
        batch_size=6,
        timeout_seconds=1200,
    )
    assert command[command.index("--translate-model") + 1] == "gpt-5.6-terra"
    assert command[command.index("--review-model") + 1] == "gpt-5.6-sol"
    assert command[command.index("--review-reasoning-effort") + 1] == "high"
    assert command[command.index("--segment-limit") + 1] == "0"


def test_teacher_command_accepts_video_id_starting_with_hyphen(tmp_path):
    command = subject.teacher_command(
        python="python3",
        video_id="-eabDU8ciVI",
        source_root=tmp_path / "source",
        out_root=tmp_path / "out",
        batch_size=6,
        timeout_seconds=1200,
    )
    assert "--video-id=-eabDU8ciVI" in command


def test_teacher_environment_does_not_receive_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("CODEX_API_KEY", "not-a-real-key")
    env = subject.clean_teacher_environment()
    assert "OPENAI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env


def test_all_stage_orders_caption_then_teacher_then_selective_audio(monkeypatch, tmp_path):
    order = []
    assignment = {"videoId": "v", "split": "train", "durationSeconds": 60}
    monkeypatch.setattr(subject, "load_assignments", lambda path: [assignment])
    monkeypatch.setattr(
        subject,
        "build_plan",
        lambda *args, **kwargs: {
            "schemaVersion": subject.SCHEMA_VERSION,
            "status": "dry_run_only",
            "selectedVideoCount": 1,
        },
    )
    monkeypatch.setattr(subject, "require_tools", lambda names: {
        "codex": "codex", "yt-dlp": "yt-dlp", "ffmpeg": "ffmpeg", "ffprobe": "ffprobe"
    })
    monkeypatch.setattr(subject, "load_api_key", lambda path: ("hidden", "existing_env_file"))
    monkeypatch.setattr(
        subject,
        "prepare_caption_source",
        lambda **kwargs: order.append("caption") or {"status": "caption_source_prepared"},
    )
    monkeypatch.setattr(
        subject,
        "run_teacher",
        lambda **kwargs: order.append("teacher") or {"status": "teacher_complete"},
    )
    monkeypatch.setattr(
        subject,
        "process_selective_audio_audit",
        lambda **kwargs: order.append("audio") or {"status": "audio_complete"},
    )
    source_report = tmp_path / "source" / "v" / "run-report.json"
    source_report.parent.mkdir(parents=True)
    source_report.write_text(
        '{"sourceQualityDisposition":"teacher_ready"}\n', encoding="utf-8"
    )
    args = SimpleNamespace(
        split_manifest=tmp_path / "splits.json",
        raw_root=tmp_path / "raw",
        existing_segment_root=tmp_path / "existing",
        calibration_root=tmp_path / "calibration",
        source_root=tmp_path / "source",
        teacher_out_root=tmp_path / "teacher",
        work_root=tmp_path / "work",
        report_dir=tmp_path / "reports",
        collector_root=tmp_path / "collector",
        api_key_env_file=tmp_path / ".env",
        split=["train", "dev"],
        video_id=[],
        max_videos=1,
        segment_limit=0,
        stage="all",
        asr_model="gpt-transcribe",
        asr_prompt="prompt",
        asr_workers=1,
        asr_retries=1,
        asr_price_per_minute=0.0045,
        audio_audit_sample_rate=0.05,
        audio_audit_padding_ms=750,
        teacher_batch_size=6,
        teacher_timeout_seconds=1200,
        execute=True,
        confirm_full_run=False,
        confirm_billable_asr=True,
        confirm_shared_codex_usage=True,
    )
    report = subject.run(args)
    assert report["status"] == "completed"
    assert order == ["caption", "teacher", "audio"]
