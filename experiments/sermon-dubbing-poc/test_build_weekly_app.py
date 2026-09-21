"""App export uses frozen candidates; no models, network, or deployment."""
import contextlib
import io
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_weekly_app as app
from check_weekly_timing import budgets
from poc import sha256, write_json
from render_weekly_audio import render_identity
import run_weekly_dubbing as runner
from server import load_weekly
from deploy_firebase import verify_release
from deploy_feedback import verified_feedback_catalog
from deploy_feedback_compat import verified_feedback_catalog as verified_compat_catalog
from test_resume_integrity import candidate_fixture, modify, snapshot
from weekly_dubbing import read


def app_fixture(root, source_id="weekly-fixture"):
    work = root / "weekly"
    work.mkdir()
    candidate_fixture(work)
    notes = {"status": "ready", "sermonDate": "2026-09-06", "centralMessageZh": "中心信息", "summaryZh": "证道摘要",
        "outlineZh": [{"title": "主题大纲", "points": ["第一点"], "sourceSliceIndexes": [0]}], "scriptureRefs": [], "reflectionQuestionsZh": []}
    write_json(work / "outline.json", notes)
    job = read(work / "job.json")
    job.update(sourceId=source_id, sourceUrl="https://example.invalid/sermon", title="本周证道", speaker="Eric Geiger", scripture="诗篇 137 篇",
        inheritedReview={"generationComplete": False})
    job["inputs"]["outline"] = {"path": str(work / "outline.json"), "sha256": sha256(work / "outline.json")}
    write_json(work / "job.json", job)
    identity = render_identity(work / "job.json", job["voice"]["checkpointSha256"])
    write_json(work / "render/identity.json", identity)
    modify(work, "render/report.json", lambda data: data.update(identity))
    for i in range(2):
        modify(work, f"render/unit-{i:04d}.json", lambda data: data.update(identity=identity))
    for path in ["assembly-report.json", "audio-review.json", "source-alignment/report.json", "audio/asr-screening.json", "synchronization/report.json"]:
        modify(work, path, lambda data: data.update(jobSha256=identity["jobSha256"]))
    modify(work, "audio/library.json", lambda data: data["tracks"][0].update(label="整篇待审", voiceLabel="Eric Geiger · 训练音色", scope="full_candidate", audioUrl="/media/zh-natural.mp3"))
    alignment_path = work / "source-alignment/report.json"
    model_path = work / "source-alignment/anchor-model-review.json"
    write_json(model_path, {"schemaVersion": "sermon-anchor-model-review-v1", "reviewType": "model", "model": "gpt-6-astra", "humanApproval": False,
        "status": "approved_for_candidate_alignment", "reviewedBy": "fixture-model-review", "reviewedAt": "2026-09-05T00:00:00Z",
        "jobSha256": identity["jobSha256"], "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"], "alignmentSha256": sha256(alignment_path),
        "unresolvedBoundaryIssues": [], "evidence": [job["inputs"]["sourceAudio"]],
        "blocks": [{"blockId": 0, "start": 0, "end": 4, "status": "model_supported", "reason": "Frozen acoustic fixture"}]})
    modify(work, "synchronization/report.json", lambda data: data.update(alignmentSha256=sha256(alignment_path), anchorReviewSha256=sha256(model_path), anchorReviewType="model"))
    render, timing = read(work / "render/report.json"), read(work / "synchronization/report.json")
    cues = [{**cue, "start": cue["start"] - row["chineseStart"] + row["videoStart"], "end": cue["end"] - row["chineseStart"] + row["videoStart"]}
        for row in timing["blocks"] for cue in render["cues"] if cue["blockId"] == row["blockId"]]
    (work / "synchronization/zh-synced.mp3").write_bytes(b"synchronized MP3 fixture")
    write_json(work / "synchronization/assembly.json", {"status": "synchronized_candidate", "jobSha256": identity["jobSha256"],
        "timingReportSha256": sha256(work / "synchronization/report.json"), "sourceNaturalMp3Sha256": sha256(work / "audio/zh-natural.mp3"),
        "sourceNaturalWavSha256": sha256(work / "render/chinese.raw.wav"), "sha256": sha256(work / "synchronization/zh-synced.mp3"),
        "fullDecode": "pass", "durationSeconds": 10.032, "cues": cues, "humanReview": "pending"})
    write_json(work / "audio-review-synced.json", {**read(work / "audio-review.json"), "mp3Sha256": sha256(work / "synchronization/zh-synced.mp3"),
        "reviewedBy": None, "reviewedAt": None, "humanApproval": False})
    return work


def fixture_fingerprint(job, week, public, *, synchronized):
    if not synchronized:
        from weekly_audio_fingerprint import bind_weekly_fingerprint
        return bind_weekly_fingerprint(job, week, public, synchronized=False)
    start = job["sourceStartSeconds"]
    end = start + job["sourceDurationSeconds"]
    identity = {"pageId": week["id"], "sourceSha256": "a" * 64, "trackSha256": week["tracks"][0]["sha256"],
        "sourceStartSeconds": start, "sourceEndSeconds": end, "algorithmVersion": "spectral-landmarks-v1"}
    index = {"schemaVersion": "sermon-landmark-index-v1", **identity, "sampleRate": 8000, "hopSize": 256, "fftSize": 1024,
        "window": {"startSeconds": start, "endSeconds": end}, "durationSeconds": end - start, "landmarkCount": 1, "postings": {"123": [1]}}
    tmp = public / "fixture-index.json"
    write_json(tmp, index)
    digest = sha256(tmp)
    destination = public / "fingerprints" / f"{digest[:16]}-landmarks.json"
    destination.parent.mkdir(exist_ok=True)
    tmp.rename(destination)
    week.update(sourceSha256="a" * 64, sourceStartSeconds=start, sourceEndSeconds=end, sourceDurationSeconds=end-start)
    week["audioFingerprint"] = {"schemaVersion": "sermon-audio-fingerprint-binding-v1", **identity,
        "captureSeconds": 10, "indexSha256": digest, "indexUrl": f"/fingerprints/{destination.name}"}
    week["automaticAudioAlignment"] = {"schemaVersion": "sermon-automatic-audio-alignment-v1", "status": "ready", "required": True}


class WeeklyAppBuildTests(unittest.TestCase):
    def test_feedback_export_binds_api_catalog_to_public_audio_without_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            self.build(root, work, review_preview=True, feedback_enabled=True)
            # The exported front end, including its recovery module, must also
            # be admissible to the strict Hosting uploader.
            verify_release(root / "build")
            verified_feedback_catalog(root / "build")
            verified_compat_catalog(root / "build")
            settings = read(root / "build/public/engagement.json")
            self.assertTrue(settings["enabled"])
            self.assertEqual(len(settings["appVersion"]), 16)
            api = read(root / "build/feedback-catalog.json")["sources"][0]
            public = read(root / "build/public/weekly.json")["weeks"][0]
            self.assertEqual(api["audioSha256"], public["tracks"][0]["sha256"])
            self.assertEqual(api["week"], public["date"])
            self.assertEqual(api["trackId"], public["tracks"][0]["id"])
            self.assertEqual(api["cueIds"], [str(i) for i in range(len(public["tracks"][0]["cues"]))])
            self.assertTrue(all("text" not in cue for cue in api["cues"]))

    def setUp(self):
        # Extraction uses real media in test_weekly_audio_fingerprint.
        fingerprint = patch.object(app, "bind_weekly_fingerprint", side_effect=fixture_fingerprint)
        fingerprint.start()
        self.addCleanup(fingerprint.stop)
        no_subprocess = patch.object(runner, "process_run", side_effect=AssertionError("No subprocess / models / network"))
        no_subprocess.start()
        self.addCleanup(no_subprocess.stop)

    def build(self, root, work, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return app.build(root / "missing-comparison", root / "build", weekly_jobs=[work], **kwargs)

    def test_weekly_job_is_independent_of_historical_samples_and_outlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            before = snapshot(work)
            with patch.object(app, "ROOT", root / "missing-historical-root"), patch.object(app, "load_library", wraps=app.load_library) as load:
                report = self.build(root, work, review_preview=True, expansion=root / "missing-expansion")
            self.assertEqual([call.args[0] for call in load.call_args_list], [work / "audio"])
            catalog = load_weekly(root / "build/public")
            self.assertEqual(report["weeks"], 1)
            self.assertEqual(catalog["defaultWeekId"], "2026-09-06-live_archive-weekly-fixture")
            self.assertEqual([w["id"] for w in catalog["weeks"]], ["2026-09-06-live_archive-weekly-fixture"])
            self.assertEqual(catalog["weeks"][0]["sourceLabel"], "主日聚会版")
            track = catalog["weeks"][0]["tracks"][0]
            self.assertEqual(track["sha256"], sha256(work / "audio/zh-natural.mp3"))
            self.assertEqual(track["subtitleTiming"], "measured_synthesis_groups")
            self.assertEqual(snapshot(work), before)

    def test_series_override_exports_titles_without_mutating_frozen_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            before = snapshot(work)
            self.build(root, work, review_preview=True, series="当生活令人费解")
            week = load_weekly(root / "build/public")["weeks"][0]
            self.assertEqual(week["series"], "当生活令人费解")
            self.assertEqual(week["title"], "本周证道 · 当生活令人费解｜主日聚会版")
            self.assertEqual(snapshot(work), before)
            self.assertEqual(app.series_title(week["title"], week["series"]), week["title"])

    def test_korean_content_sidecar_is_display_only_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            before = snapshot(work)
            localizations = root / "ko-localizations.json"
            write_json(localizations, {
                "schemaVersion": "sermon-target-language-content-v1",
                "sourceLocale": "en",
                "translations": [{
                    "weekId": "2026-09-06-live_archive-weekly-fixture",
                    "locale": "ko",
                    "status": "draft",
                    "sourceFields": {"title": "This Week's Sermon", "summary": "Canonical English summary"},
                    "fields": {"title": "이번 주 설교", "summary": "한국어 요약 초안"},
                }],
            })
            report = self.build(root, work, review_preview=True, content_localizations=localizations)
            week = load_weekly(root / "build/public")["weeks"][0]
            localized = week["contentLocalizations"]["ko"]
            self.assertEqual(localized["status"], "draft")
            self.assertEqual(localized["sourceLocale"], "en")
            self.assertEqual(localized["fields"]["title"], "이번 주 설교")
            self.assertEqual(localized["sourceContentSha256"], week["contentSource"]["sha256"])
            self.assertEqual(week["contentSource"]["locale"], "en")
            self.assertEqual(week["contentSource"]["fields"]["title"], "This Week's Sermon")
            self.assertEqual(week["contentSource"]["sha256"], app.content_fields_sha256(week["contentSource"]["fields"]))
            self.assertEqual(report["contentLocalizationsSha256"], sha256(localizations))
            self.assertEqual(week["tracks"][0]["sha256"], sha256(work / "audio/zh-natural.mp3"))
            self.assertEqual(snapshot(work), before)

    def test_content_sidecar_rejects_non_display_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            localizations = root / "invalid-localizations.json"
            write_json(localizations, {
                "schemaVersion": "sermon-target-language-content-v1",
                "sourceLocale": "en",
                "translations": [{
                    "weekId": "2026-09-06-live_archive-weekly-fixture",
                    "locale": "ko",
                    "status": "draft",
                    "sourceFields": {"audioStatus": "pending"},
                    "fields": {"audioStatus": "full_reviewed"},
                }],
            })
            with self.assertRaisesRegex(ValueError, "Unsupported localized content field"):
                self.build(root, work, review_preview=True, content_localizations=localizations)

    def test_content_sidecar_requires_english_source_and_matching_target_shape(self):
        cases = [
            ({"schemaVersion": "sermon-target-language-content-v1", "sourceLocale": "zh-CN", "translations": []}, "Invalid content localizations"),
            ({
                "schemaVersion": "sermon-target-language-content-v1", "sourceLocale": "en",
                "translations": [{
                    "weekId": "2026-09-06-live_archive-weekly-fixture", "locale": "ko", "status": "draft",
                    "sourceFields": {"title": "English title", "summary": "English summary"},
                    "fields": {"title": "한국어 제목"},
                }],
            }, "Target fields do not match canonical English fields"),
        ]
        for payload, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                work = app_fixture(root)
                localizations = root / "invalid-localizations.json"
                write_json(localizations, payload)
                with self.assertRaisesRegex(ValueError, message):
                    self.build(root, work, review_preview=True, content_localizations=localizations)

    def test_legacy_build_without_weekly_job_keeps_both_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            entries = [{"date": date, "sourceId": f"fixture-{i}", "title": "历史证道", "scripture": "诗篇 137 篇", "speaker": "Eric", "number": "137"}
                for i, date in enumerate(["2026-09-06", "2026-08-30"])]
            for entry in entries:
                path = root / f'artifacts/post-live-runs/{entry["date"]}/sermon_{entry["sourceId"]}/pipeline/sermon-interpretation/insights/openai-notes.json'
                write_json(path, {**read(work / "outline.json"), "sermonDate": entry["date"]})
            with patch.object(app, "ROOT", root), patch.object(app, "WEEKS", entries), contextlib.redirect_stdout(io.StringIO()):
                report = app.build(work / "audio", root / "build")
            catalog = load_weekly(root / "build/public")
            self.assertEqual(report["weeks"], 2)
            self.assertEqual(report["playableWeeks"], 1)
            self.assertEqual(catalog["defaultWeekId"], "2026-09-06")
            self.assertEqual(catalog["weeks"][1]["tracks"], [])

    def test_sync_preview_exports_verified_sync_audio_and_remains_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            before = snapshot(work)
            with patch("weekly_dubbing.validate_review", side_effect=AssertionError("No human approval in preview")):
                self.build(root, work, review_preview=True, sync_preview=True)
            week = load_weekly(root / "build/public")["weeks"][0]
            track = week["tracks"][0]
            assembled = read(work / "synchronization/assembly.json")
            self.assertEqual(track["sha256"], assembled["sha256"])
            self.assertEqual(track["cues"], assembled["cues"])
            self.assertEqual(track["cues"][1]["start"], 5)
            self.assertEqual(track["durationSeconds"], 10)
            self.assertEqual(track["subtitleTiming"], "source_video_aligned_candidate")
            self.assertEqual((root / "build/public/media" / track["file"]).read_bytes(), b"synchronized MP3 fixture")
            self.assertEqual(len(list((root / "build/public/media").iterdir())), 1)
            self.assertEqual(week["audioStatus"], "full_candidate")
            self.assertEqual(track["scope"], "full_candidate")
            self.assertFalse(week["humanApproval"])
            self.assertEqual(week["videoSynchronization"], "candidate_aligned")
            for phrase in ["同步试播", "模型审核不等于人工验收", "仍待现场试听"]:
                self.assertIn(phrase, week["audioNotice"])
            self.assertEqual(week["productionStages"][-1]["status"], "pending")
            self.assertEqual(week["candidateEvidence"]["syncAssemblySha256"], sha256(work / "synchronization/assembly.json"))
            self.assertEqual(snapshot(work), before)

    def test_include_history_keeps_three_old_auditions_and_replaces_matching_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            entries = [{"date": date, "sourceId": f"fixture-{i}", "title": "历史证道", "scripture": "诗篇 137 篇", "speaker": "Eric", "number": "137"}
                for i, date in enumerate(["2026-09-06", "2026-08-23"])]
            entries[0]["sourceId"] = "weekly-fixture"
            for entry in entries:
                path = root / f'artifacts/post-live-runs/{entry["date"]}/sermon_{entry["sourceId"]}/pipeline/sermon-interpretation/insights/openai-notes.json'
                write_json(path, {**read(work / "outline.json"), "sermonDate": entry["date"]})
            for name, identifiers in [("comparison", ["accepted", "default", "flow"]), ("expansion", ["expanded"])]:
                pack = root / name
                pack.mkdir()
                tracks = []
                for identifier in identifiers:
                    audio = pack / f"{identifier}.mp3"
                    audio.write_bytes(identifier.encode())
                    tracks.append({**read(work / "audio/library.json")["tracks"][0], "id": identifier, "file": audio.name,
                        "audioUrl": f"/media/{audio.name}", "sha256": sha256(audio)})
                write_json(pack / "library.json", {"schemaVersion": "sermon-audio-library-v1", "date": "2026-08-23", "tracks": tracks})
            with patch.object(app, "ROOT", root), patch.object(app, "WEEKS", entries), patch.object(app, "write_json", wraps=write_json) as write, contextlib.redirect_stdout(io.StringIO()):
                report = app.build(root / "comparison", root / "build", expansion=root / "expansion", weekly_jobs=[work],
                    review_preview=True, sync_preview=True, include_history=True)
            catalog = load_weekly(root / "build/public")
            self.assertEqual([week["id"] for week in catalog["weeks"]], ["2026-09-06-live_archive-weekly-fixture", "2026-08-23"])
            self.assertEqual(catalog["weeks"][0]["title"], "本周证道｜主日聚会版")
            self.assertEqual(catalog["weeks"][0]["tracks"][0]["sha256"], sha256(work / "synchronization/zh-synced.mp3"))
            old = catalog["weeks"][1]
            self.assertEqual(old["title"], "历史证道 · 当生活令人费解")
            self.assertEqual(old["outline"][0]["title"], "主题大纲")
            self.assertEqual([track["id"] for track in old["tracks"]], ["accepted", "expanded", "default"])
            self.assertTrue(report["includeHistory"])
            self.assertEqual(sum(call.args[0] == root / "build/build-report.json" for call in write.call_args_list), 1)

    def test_same_week_sources_keep_separate_pages_audio_and_feedback_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "first").mkdir()
            (root / "second").mkdir()
            first = app_fixture(root / "first", "first-video")
            second = app_fixture(root / "second", "second-video")
            with contextlib.redirect_stdout(io.StringIO()):
                app.build(root / "missing-history", root / "build", weekly_jobs=[first, second],
                    review_preview=True, feedback_enabled=True)
            weeks = load_weekly(root / "build/public")["weeks"]
            self.assertEqual({w["id"] for w in weeks}, {
                "2026-09-06-live_archive-first-video", "2026-09-06-live_archive-second-video"})
            self.assertEqual(len({w["tracks"][0]["id"] for w in weeks}), 2)
            # Identical fixture MP3 bytes still represent different sources.
            self.assertEqual(len({w["tracks"][0]["sha256"] for w in weeks}), 1)
            api = read(root / "build/feedback-catalog.json")
            self.assertEqual(api["weekIds"], ["2026-09-06"])
            self.assertEqual({s["week"] for s in api["sources"]}, {"2026-09-06"})
            self.assertEqual(len({s["trackId"] for s in api["sources"]}), 2)
            verify_release(root / "build")
            verified_feedback_catalog(root / "build")
            verified_compat_catalog(root / "build")

    def test_same_video_and_live_archive_pages_coexist_and_same_video_is_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = []
            for route in ["same_video", "live_archive"]:
                work = root / route
                work.mkdir()
                write_json(work / "job.json", {"week": "2026-09-06", "sourceRoute": route, "sourceId": "same-id"})
                jobs.append(work)
            # Source approval is exercised by the existing weekly_job tests;
            # this test isolates catalog retention/order after that validation.
            def exported(work, *args):
                return {**app.source_page(read(work / "job.json")), "date": "2026-09-06", "sourceId": "same-id",
                    "title": "本周证道", "speaker": "Eric", "outline": ["大纲"], "tracks": [],
                    "audioStatus": "full_candidate", "videoSynchronization": "not_validated",
                    "automaticAudioAlignment": {"schemaVersion": "sermon-automatic-audio-alignment-v1", "status": "unavailable", "required": False, "reason": "unsynchronized_review_preview"}}
            with patch.object(app, "weekly_job", side_effect=exported), contextlib.redirect_stdout(io.StringIO()):
                app.build(root / "missing-history", root / "build", weekly_jobs=jobs, review_preview=True)
            catalog = load_weekly(root / "build/public")
            self.assertEqual([w["id"] for w in catalog["weeks"]], [
                "2026-09-06-same_video-same-id", "2026-09-06-live_archive-same-id"])
            self.assertEqual(catalog["defaultWeekId"], "2026-09-06-same_video-same-id")
            self.assertEqual(catalog["weeks"][0]["sourceLabel"], "YouTube 版")
            self.assertEqual(catalog["weeks"][1]["sourceLabel"], "主日聚会版")

    def test_sync_preview_requires_both_flags_and_a_weekly_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for kwargs in [{"weekly_jobs": [root / "missing"]}, {"review_preview": True}]:
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "requires --review-preview"):
                    app.build(root / "missing", root / "build", sync_preview=True, **kwargs)
                self.assertFalse((root / "build").exists())
            with patch.object(sys, "argv", [str(app.__file__), "--sync-preview"]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                runpy.run_path(str(app.__file__), run_name="__main__")
            self.assertEqual(exc.exception.code, 2)

    def test_reviewed_playback_lead_uses_video_start_without_changing_source_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            job, render = read(work / "job.json"), read(work / "render/report.json")
            alignment = read(work / "source-alignment/report.json")
            review_path = work / "synchronization/placement-model-review.json"
            write_json(review_path, {"schemaVersion": "sermon-playback-placement-review-v1", "reviewType": "model", "model": "gpt-6-astra", "humanApproval": False,
                "status": "approved_for_candidate_playback", "reviewedBy": "fixture-model-review", "reviewedAt": "2026-09-05T00:00:00Z",
                "jobSha256": sha256(work / "job.json"), "renderSha256": sha256(work / "render/report.json"),
                "alignmentSha256": sha256(work / "source-alignment/report.json"), "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"],
                "unresolvedPlacementIssues": [], "evidence": [job["inputs"]["sourceAudio"]],
                "blocks": [{"blockId": 1, "sourceAnchorStart": 5, "playbackStart": 4.5, "status": "model_supported", "reason": "Frozen playback fixture"}]})
            rows, failures = budgets(job["blocks"], alignment["blocks"], render["cues"], 10, {1: 4.5})
            modify(work, "synchronization/report.json", lambda d: d.update(blocks=rows, failures=failures, placementReviewSha256=sha256(review_path)))
            modify(work, "synchronization/assembly.json", lambda d: d.update(timingReportSha256=sha256(work / "synchronization/report.json"),
                cues=[d["cues"][0], {**d["cues"][1], "start": 4.5, "end": 6.5}]))
            before = snapshot(work)
            report = self.build(root, work, review_preview=True, sync_preview=True)
            track = load_weekly(root / "build/public")["weeks"][0]["tracks"][0]
            self.assertEqual(track["cues"][1]["start"], 4.5)
            self.assertEqual(read(work / "source-alignment/report.json")["blocks"][1]["start"], 5)
            self.assertTrue(report["syncPreview"])
            self.assertEqual(snapshot(work), before)

    def test_replaced_sync_receipts_audio_and_subtitles_cannot_be_exported(self):
        changes = [
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(jobSha256="changed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(timingReportSha256="changed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(sourceNaturalMp3Sha256="changed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(sourceNaturalWavSha256="changed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(fullDecode="failed")),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d.update(durationSeconds=9)),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d["cues"][1].update(start=4.5)),
            lambda w: modify(w, "synchronization/assembly.json", lambda d: d["cues"][0].update(text="改了字幕")),
            lambda w: (w / "synchronization/zh-synced.mp3").write_bytes(b"changed MP3"),
            lambda w: (w / "synchronization/assembly.json").unlink(),
        ]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                work = app_fixture(root)
                change(work)
                before = snapshot(work)
                with self.assertRaises(ValueError):
                    self.build(root, work, review_preview=True, sync_preview=True)
                self.assertFalse((root / "build/public/weekly.json").exists())
                self.assertEqual(list((root / "build/public/media").iterdir()), [])
                self.assertEqual(snapshot(work), before)

    def test_shared_validator_rejects_changed_source_render_review_or_screening(self):
        changes = [lambda w: (w / "source.wav").write_bytes(b"changed source"),
            lambda w: (w / "render/chinese.raw.wav").write_bytes(b"changed WAV"),
            lambda w: modify(w, "source-alignment/anchor-model-review.json", lambda d: d.update(humanApproval=True)),
            lambda w: modify(w, "audio/asr-screening.json", lambda d: d.update(jobSha256="changed"))]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                work = app_fixture(root)
                change(work)
                with self.assertRaises(ValueError):
                    self.build(root, work, review_preview=True, sync_preview=True)
                self.assertFalse((root / "build/public/weekly.json").exists())

    def test_valid_candidate_with_timing_failures_is_not_a_sync_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            (work / "source-alignment/anchor-model-review.json").unlink()
            anchors = [{"blockId": 0, "start": 0, "end": 1, "issues": []}, {"blockId": 1, "start": 1, "end": 9, "issues": []}]
            modify(work, "source-alignment/report.json", lambda d: d.update(blocks=anchors))
            rows, failures = budgets(read(work / "job.json")["blocks"], anchors, read(work / "render/report.json")["cues"], 10)
            modify(work, "synchronization/report.json", lambda d: d.update(blocks=rows, failures=failures, status="needs_timing_review",
                alignmentSha256=sha256(work / "source-alignment/report.json"), anchorReviewSha256=None))
            modify(work, "synchronization/assembly.json", lambda d: d.update(timingReportSha256=sha256(work / "synchronization/report.json")))
            self.assertTrue(runner.validate_candidate(work))
            with self.assertRaisesRegex(ValueError, "Timing still has unresolved failures"):
                self.build(root, work, review_preview=True, sync_preview=True)

    def test_model_review_cannot_replace_the_formal_human_release_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            with self.assertRaisesRegex(ValueError, "Human audio review is not complete"):
                self.build(root, work)
            self.assertFalse((root / "build/public/weekly.json").exists())


if __name__ == "__main__":
    unittest.main()
