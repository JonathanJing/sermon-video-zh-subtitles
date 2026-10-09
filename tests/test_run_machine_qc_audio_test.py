"""The local machine-QC audio driver and its ASR/TTS transports, with fakes only."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from scripts import machine_qc_audio_transports as transports
from scripts import machine_quality_release_basis as basis
from scripts import machine_repair_ledger as ledger
from scripts import run_machine_qc_audio_test as driver
from scripts import run_machine_qc_clip_test as text_driver
from scripts import screen_target_language_audio_units as audio_screen
from scripts import target_audio_auto_qc as audio_qc
from scripts.target_audio_predicted_schedule import SYNTHESIS_IDENTITY_FIELDS, speech_units
from tests import auto_qc_fixtures as qc_fixtures
from tests import test_run_machine_qc_clip_test as text_tests

LOCALE = "ko"
CHECKPOINT = "e" * 64
FLAGGED = "g002"
OPENAI_ENV = {"SERMON_OPENAI_ENVIRONMENT": "dev", "OPENAI_PROJECT_ID": "proj_test",
              "SERMON_OPENAI_CREDENTIAL_ALIAS": "tongxing-dev-runtime", "OPENAI_API_KEY": "sk-test-not-real"}


def write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def speech_job(run: Path, candidate: dict, paths: dict, *, schema=driver.MACHINE_SPEECH_JOB_SCHEMA) -> dict:
    adapter = {field: f"{field}-1" for field in SYNTHESIS_IDENTITY_FIELDS}
    adapter.update(provider="local", model="tts", conditioningSha256=CHECKPOINT, speakerKey="speaker_1",
                   conditioningRef="ckpt-ref")

    def ref(path: Path) -> dict:
        return {"path": str(path), "jsonSha256": basis.json_sha256(json.loads(path.read_text(encoding="utf-8")))}

    return {"schemaVersion": schema, "status": "prepared_for_target_language_speech", "synthesisEligible": True,
            "targetLocale": LOCALE,
            "inputs": {"englishSourcePackage": ref(paths["source"]), "anchorManifest": ref(paths["anchor"]),
                       "targetLanguageCandidate": ref(paths["candidate"]), "targetLanguagePolicy": ref(paths["policy"]),
                       "textReleaseBasis": ref(paths["textWaiver"])},
            "adapter": adapter,
            "units": [{"unitIndex": index, "translationGroupId": group["translationGroupId"],
                       "sourceUnitIds": group["sourceUnitIds"], "text": group["targetText"],
                       "outputRelativePath": f"languages/{LOCALE}/audio/unit-{index:04d}.wav"}
                      for index, group in enumerate(candidate["groups"])]}


def audio_run(test, run: Path, text_waiver_path: Path, *, job_schema=driver.MACHINE_SPEECH_JOB_SCHEMA,
              screening_schema="sermon-target-language-audio-screening-v2") -> dict:
    """A rendered, ASR-screened ko audio package beside the synthetic text run; one unit is flagged."""
    paths = {"source": run / "source-package.json", "anchor": run / "anchor-manifest.json",
             "candidate": run / "diagnostic-previews/ko/native-1/candidate.json", "policy": run / "policy/ko.json",
             "textWaiver": text_waiver_path}
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    job = speech_job(run, candidate, paths, schema=job_schema)
    job_root = run / "speech-job"
    job_path = write(job_root / "speech-job.json", job)
    units, entries, wavs, start = [], [], [], 0.0
    for job_unit in job["units"]:
        wav = qc_fixtures.speech_wav(0.2 + 0.17 * speech_units(job_unit["text"], LOCALE) + 0.01 * job_unit["unitIndex"])
        path = job_root / job_unit["outputRelativePath"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wav)
        wavs.append(wav)
        units.append({"textGroupId": job_unit["translationGroupId"],
                      "targetTextSha256": sha(job_unit["text"].encode("utf-8")),
                      "audio": {"path": str(path.resolve()), "sha256": sha(wav)}, "durationSeconds": 1.0})
        entries.append({"textGroupId": job_unit["translationGroupId"], "plannedStart": round(start, 3)})
        start += len(audio_qc._pcm16_frames(wav)[0]) / 2 / 8000 + 0.5
    schedule = {"entries": entries}
    schedule_path = write(job_root / f"languages/{LOCALE}/synchronization/schedule.json", schedule)
    track_pcm, rate, channels = audio_qc.scheduled_track(entries, wavs, int((start + 1) * 8000))
    import io
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(track_pcm)
    track_path = job_root / f"languages/{LOCALE}/audio/track.wav"
    track_path.write_bytes(buffer.getvalue())
    captions_path = write(job_root / f"languages/{LOCALE}/synchronization/captions.json", {"cues": []})
    heard = [job_unit["text"] if job_unit["translationGroupId"] != FLAGGED else job_unit["text"][:6]
             for job_unit in job["units"]]
    scores = [audio_screen.score(unit["text"], recognized, LOCALE, 0.88) for unit, recognized in zip(job["units"], heard)]
    status = "pass" if all(passed for _, _, passed in scores) else "requires_review"
    settings = {"protocol": "formal-back-asr-batch-v1", "model": audio_screen.MODEL,
                "modelRevision": "model.safetensors:sha256:" + "a" * 64, "language": LOCALE, "batchSize": 1,
                "maxNewTokens": 2048, "dtype": "bfloat16", "executionDevice": "cuda:0",
                "runtime": {"backend": "qwen-asr-local", "torchVersion": "test"},
                "implementationSha256": transports.file_sha256(transports.SCREENER),
                "minSimilarity": 0.88, "scoring": audio_screen.SCORING}
    screening = {"schemaVersion": screening_schema, "targetLocale": LOCALE,
                 "targetLanguageSpeechJobJsonSha256": basis.json_sha256(job),
                 "trackSha256": sha(track_path.read_bytes()), "status": status, "model": audio_screen.MODEL,
                 "modelRevision": settings["modelRevision"], "minSimilarity": 0.88, "coverage": 1.0,
                 "reviewedGroupIds": [unit["textGroupId"] for unit in units],
                 "unitAudioSha256s": [unit["audio"]["sha256"] for unit in units],
                 "results": [{"textGroupId": unit["textGroupId"], "targetTextSha256": unit["targetTextSha256"],
                              "audioSha256": unit["audio"]["sha256"], "recognized": recognized,
                              "similarity": similarity, "differences": differences,
                              "status": "pass" if passed else "requires_review"}
                             for unit, recognized, (similarity, differences, passed) in zip(units, heard, scores)],
                 "humanListeningStatus": "pending"}
    if screening_schema.endswith("v2"):
        screening.update(asrSettings=settings, asrSettingsSha256=basis.json_sha256(settings))
    write(job_root / f"review/{LOCALE}-asr-screening.json", screening)
    package = {"schemaVersion": driver.AUDIO_PACKAGE_SCHEMA, "packageId": "target-audio-ko-test",
               "englishSourcePackageJsonSha256": candidate["englishSourcePackageJsonSha256"],
               "targetLanguageCandidateJsonSha256": basis.json_sha256(candidate),
               "targetLanguageSpeechJobJsonSha256": basis.json_sha256(job), "targetLocale": LOCALE,
               "status": "machine_screened" if status == "pass" else "candidate",
               "ratePolicy": "natural_no_time_stretch",
               "voice": {"targetLocale": LOCALE, "provider": "local", "model": "tts", "modelRevision": "modelRevision-1",
                         "voice": "voice-1", "speakerId": "speakerId-1", "checkpointSha256": CHECKPOINT,
                         "authorizationStatus": "authorized", "targetLocaleCapability": "reviewed"},
               "units": units, "track": {"path": str(track_path.resolve()), "sha256": sha(track_path.read_bytes())},
               "captions": {"path": str(captions_path.resolve()), "sha256": sha(captions_path.read_bytes())},
               "schedule": {"path": str(schedule_path.resolve()), "sha256": sha(schedule_path.read_bytes()),
                            "jsonSha256": basis.json_sha256(schedule)},
               "machineScreening": {"status": status, "model": audio_screen.MODEL, "coverage": 1.0},
               "humanReview": {"status": "pending", "humanApproval": False, "reviewedBy": None,
                               "reviewedAt": None, "fullPlayback": "pending"},
               "issues": []}
    write(run / "audio-package/ko/package.json", package)
    return {"job": job_path, "package": run / "audio-package/ko/package.json"}


class MachineQcAudioDriverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # The text path first: a real-looking text driver run issues the text waiver.
        self.text = text_tests.MachineQcClipDriverTests()
        self.text.root = self.root
        self.run_dir = text_tests.synthetic_run(self, self.root)
        stack, argv = self.text.real_runs(self.run_dir)
        with stack:
            self.assertEqual(text_driver.main(argv), 0)
        self.text_waiver = Path(self.text.real_row()["textWaiver"])
        self.state = self.root / "real-state"

    def build(self, **kwargs):
        return audio_run(self, self.run_dir, self.text_waiver, **kwargs)

    def fake(self, *extra):
        return driver.main(["--run-dir", str(self.run_dir), "--out", str(self.root / "audio"),
                            "--locales", LOCALE, "--backend", "fake", *extra])

    def fake_row(self):
        return json.loads((self.root / "audio/fake-plumbing/summary.json").read_text(encoding="utf-8"))["locales"][LOCALE]

    def test_preflight_finds_everything_by_hash(self):
        self.build()
        self.assertEqual(self.fake("--preflight-only"), 0, self.fake_row()["problems"])
        row = self.fake_row()
        self.assertEqual(row["flaggedGroups"], [FLAGGED])
        self.assertEqual(Path(row["paths"]["textWaiver"]), self.text_waiver)
        self.assertEqual(row["calibrationCoverage"]["audio"]["untestableKinds"], [])

    def test_fake_backend_proves_the_path_but_never_saves_a_waiver(self):
        self.build()
        built = []
        original = basis.build_audio_waiver

        def spy(*args, **kwargs):
            built.append(original(*args, **kwargs))
            return built[-1]

        with patch.object(basis, "build_audio_waiver", side_effect=spy):
            self.assertEqual(self.fake(), 0, self.fake_row().get("reason"))
        row = self.fake_row()
        self.assertEqual(row["status"], "fake_plumbing_pass")
        self.assertEqual(row["secondaryAsrGroups"], [FLAGGED])
        self.assertEqual(list((self.root / "audio/fake-plumbing" / LOCALE).glob("audio-waiver*")), [])
        receipt = built[0]
        self.assertFalse(receipt["humanApproval"])
        self.assertEqual(receipt["secondaryAsrModel"], {"model": "fake-strong-asr", "modelRevision": None})
        self.assertEqual([r["asr"] for r in receipt["unitResults"] if r["textGroupId"] == FLAGGED], ["secondary_pass"])
        timings = (self.root / "audio/fake-plumbing/timings.tsv").read_text(encoding="utf-8")
        for stage in ("discover", "ko.track-check", "ko.secondary-asr", "ko.audio-qc", "ko.calibration",
                      "ko.audio-waiver"):
            self.assertIn(f"\n{stage}\tpass\t", timings)
        calibration = json.loads(next((self.root / "audio/fake-plumbing" / LOCALE).glob(
            "audio-calibration-*[0-9a-f].json")).read_text(encoding="utf-8"))
        self.assertGreater(calibration["kinds"]["audio.dropped_key_word"]["trials"], 0)
        self.assertGreater(calibration["kinds"]["audio.wrong_sentence"]["trials"], 0)
        self.assertEqual(calibration["renderIdentity"]["checkpointSha256"], CHECKPOINT)

    def real_looking(self):
        """Fake transports the driver treats as real: it saves receipts and the waiver."""
        stack = ExitStack()
        stack.enter_context(patch.dict(os.environ, OPENAI_ENV))
        real_make = driver.make_transports
        stack.enter_context(patch.object(driver, "make_transports",
                                         lambda backend, *a, **k: real_make("fake", *a, **k)))
        stack.enter_context(patch.object(transports.QwenPrimaryAsr, "runtime_problems", lambda self: []))
        groups = text_driver.qc_groups(json.loads((self.run_dir / "diagnostic-previews/ko/native-1/candidate.json")
                                                  .read_text(encoding="utf-8")),
                                       json.loads((self.run_dir / "anchor-manifest.json").read_text(encoding="utf-8")))

        class RealLooking(text_driver.FakeJudge):
            pass

        stack.enter_context(patch.object(text_driver, "CodexJudge", lambda cache: RealLooking({LOCALE: groups})))
        map_path = write(self.root / "ckpt-map.json", {})
        argv = ["--run-dir", str(self.run_dir), "--out", str(self.root / "audio-real"), "--locales", LOCALE,
                "--state-dir", str(self.state), "--asr-model-path", str(self.root / "asr"),
                "--tts-checkpoint-map", str(map_path)]
        return stack, argv

    def real_row(self):
        return json.loads((self.root / "audio-real/summary.json").read_text(encoding="utf-8"))["locales"][LOCALE]

    def lineage(self):
        anchor = json.loads((self.run_dir / "anchor-manifest.json").read_text(encoding="utf-8"))
        source = json.loads((self.run_dir / "source-package.json").read_text(encoding="utf-8"))
        return ledger.lineage("audio", LOCALE, basis.json_sha256(source), basis.json_sha256(anchor))

    def test_a_real_looking_run_issues_and_then_reuses_its_waiver(self):
        paths = self.build()
        stack, argv = self.real_looking()
        with stack:
            self.assertEqual(driver.main(argv), 0, self.real_row().get("reason"))
            path = Path(self.real_row()["audioWaiver"])
            first = path.read_bytes()
            self.assertEqual(driver.main(argv), 0)
            self.assertTrue(self.real_row()["reused"])
            self.assertEqual(path.read_bytes(), first)
        package = json.loads(paths["package"].read_text(encoding="utf-8"))
        receipt = json.loads(first)
        self.assertEqual(receipt["targetLanguageAudioPackageJsonSha256"], basis.json_sha256(package))
        self.assertFalse(receipt["humanApproval"])
        # One audio ledger entry beside the text one, in the shared state dir.
        self.assertEqual(len(ledger.load(self.state / "repair-ledger", self.lineage())), 1)
        self.assertEqual(package["humanReview"]["humanApproval"], False)

    def test_a_confirmed_mismatch_needs_a_re_render_before_rescreening(self):
        self.build()
        stack, argv = self.real_looking()
        mishears = lambda asr, wav: "다른 문장"  # The strong ASR also disagrees on the flagged unit.
        with stack:
            with patch.object(transports.FakeSecondaryAsr, "transcribe", mishears):
                self.assertEqual(driver.main(argv), 1)
            row = self.real_row()
            self.assertEqual((row["status"], row["failedGroups"]), ("requires_repair", [FLAGGED]))
            self.assertEqual(row["nextActions"], {FLAGGED: "resynthesize_new_seed"})
            self.assertEqual(list((self.root / "audio-real" / LOCALE).glob("audio-calibration*")), [])
            # Another secondary runtime changes the QC binding, but the failed audio is unchanged.
            with patch.object(transports.FakeSecondaryAsr, "identity", lambda asr: {"model": "other"}):
                self.assertEqual(driver.main(argv), 1)
            self.assertEqual(self.real_row()["status"], "blocked_prior_failure")
        self.assertEqual(len(ledger.load(self.state / "repair-ledger", self.lineage())), 1)

    def test_an_unknown_paid_call_outcome_stops_new_dispatch(self):
        self.build()
        stack, argv = self.real_looking()
        lost = self.state / "asr-calls/secondary/call-1"
        lost.mkdir(parents=True)
        (lost / "started.json").write_text("{}", encoding="utf-8")
        with stack, patch.object(driver, "run_locale", side_effect=AssertionError("dispatched")):
            self.assertEqual(driver.main(argv), 1)
        self.assertEqual(self.real_row()["status"], "blocked_unknown_outcome")
        self.assertEqual(self.real_row()["uncertainCalls"], ["call-1"])

    def test_real_runs_need_the_openai_launcher_and_local_models(self):
        self.build()
        stack, argv = self.real_looking()
        stack.close()  # Only the arguments: no launcher route and no patched transports.
        with patch.dict(os.environ, {}, clear=False):
            for name in OPENAI_ENV:
                os.environ.pop(name, None)
            with self.assertRaises(SystemExit):
                driver.main(argv)
        with self.assertRaises(SystemExit):
            driver.main(argv[:argv.index("--asr-model-path")])

    def test_preflight_refuses_a_human_receipt_job_and_a_v1_screening(self):
        self.build(job_schema="sermon-target-language-speech-job-v2",
                   screening_schema="sermon-target-language-audio-screening-v1")
        self.assertEqual(self.fake("--preflight-only"), 2)
        problems = self.fake_row()["problems"]
        self.assertTrue(any("needs the v3 job" in problem for problem in problems), problems)
        self.assertTrue(any("screening v2" in problem for problem in problems), problems)

    def test_preflight_refuses_a_package_from_another_voice(self):
        paths = self.build()
        package = json.loads(paths["package"].read_text(encoding="utf-8"))
        package["voice"]["checkpointSha256"] = "f" * 64
        write(paths["package"], package)
        self.assertEqual(self.fake("--preflight-only"), 2)
        self.assertTrue(any("TTS other than the package's voice" in p for p in self.fake_row()["problems"]))

    def test_preflight_refuses_changed_unit_audio(self):
        paths = self.build()
        package = json.loads(paths["package"].read_text(encoding="utf-8"))
        Path(package["units"][0]["audio"]["path"]).write_bytes(qc_fixtures.speech_wav(1.0))
        self.assertEqual(self.fake("--preflight-only"), 2)
        self.assertTrue(any("unit audio changed" in p for p in self.fake_row()["problems"]))


class TransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_secondary_asr_needs_the_launcher_route(self):
        with patch.dict(os.environ, {}, clear=False):
            for name in OPENAI_ENV:
                os.environ.pop(name, None)
            with self.assertRaisesRegex(ValueError, "run_with_openai_environment"):
                transports.OpenAiTranscribeSecondary(LOCALE, cache=self.root, max_calls=5)

    def test_secondary_asr_sends_audio_only_and_caches_by_audio(self):
        sent = []

        def executor(request):
            sent.append(request)
            return {"text": " 두려워하지 마십시오. ", "usage": {"type": "duration", "seconds": 1}}

        text = "두려워하지 마십시오."
        wav = qc_fixtures.speech_wav(1.0)
        with patch.dict(os.environ, OPENAI_ENV):
            asr = transports.OpenAiTranscribeSecondary(LOCALE, cache=self.root / "calls", max_calls=1,
                                                       request_executor=executor)
            opinion = asr.opinion(wav, text, LOCALE)
            again = asr.opinion(wav, "다른 기대 문장", LOCALE)
        self.assertEqual(len(sent), 1)
        request = sent[0]
        self.assertEqual(request.full_url, transports.TRANSCRIBE_URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test-not-real")
        self.assertEqual(request.get_header("Openai-project"), "proj_test")
        self.assertNotIn(text.encode("utf-8"), request.data)
        self.assertIn(b'name="languages[]"\r\n\r\nko\r\n', request.data)
        self.assertIn(b"Content-Type: audio/wav", request.data)
        self.assertEqual(opinion["recognized"], "두려워하지 마십시오.")
        self.assertEqual(opinion["similarity"], 1.0)
        self.assertEqual(again["recognized"], opinion["recognized"])
        self.assertEqual(opinion["settings"]["runtime"]["backend"], "openai-api")
        self.assertEqual(opinion["settings"]["runtime"]["openaiEnvironment"], "dev")
        stored = "".join(path.read_text(encoding="utf-8") for path in (self.root / "calls").rglob("*.json"))
        self.assertNotIn("sk-test-not-real", stored)
        self.assertNotIn(json.dumps(opinion["settings"]), "sk-test")
        # The opinion is accepted by the audio QC as a secondary of another model.
        audio_qc.bound_opinion(opinion, sha(wav), text, LOCALE)

    def test_a_failed_paid_call_is_never_resent(self):
        calls = []

        def executor(request):
            calls.append(request)
            raise TimeoutError("no response")

        wav = qc_fixtures.speech_wav(1.0)
        with patch.dict(os.environ, OPENAI_ENV):
            asr = transports.OpenAiTranscribeSecondary(LOCALE, cache=self.root / "calls", max_calls=5,
                                                       request_executor=executor)
            with self.assertRaises(TimeoutError):
                asr.transcribe(wav)
            with self.assertRaises(transports.UnknownOutcome):
                asr.transcribe(wav)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(asr.uncertain()), 1)
            capped = transports.OpenAiTranscribeSecondary(LOCALE, cache=self.root / "other", max_calls=0,
                                                          request_executor=executor)
            with self.assertRaisesRegex(ValueError, "call cap"):
                capped.transcribe(wav)
        self.assertEqual(len(calls), 1)

    def screening(self, revision: str):
        wav = qc_fixtures.speech_wav(1.0)
        settings = {"protocol": "formal-back-asr-batch-v1", "model": audio_screen.MODEL, "modelRevision": revision,
                    "language": LOCALE, "batchSize": 1, "maxNewTokens": 2048, "dtype": "bfloat16",
                    "executionDevice": "cuda:0", "runtime": {"backend": "qwen-asr-local", "torchVersion": "t"},
                    "implementationSha256": transports.file_sha256(transports.SCREENER), "minSimilarity": 0.88,
                    "scoring": audio_screen.SCORING}
        return wav, {"schemaVersion": "sermon-target-language-audio-screening-v2", "targetLocale": LOCALE,
                     "model": audio_screen.MODEL, "modelRevision": revision, "minSimilarity": 0.88,
                     "results": [{"audioSha256": sha(wav), "recognized": "두려워하지 마십시오"}],
                     "asrSettings": settings, "asrSettingsSha256": basis.json_sha256(settings)}

    def test_primary_asr_reuses_the_screening_and_proves_its_runtime_for_new_audio(self):
        model = self.root / "asr"
        model.mkdir()
        (model / "model.safetensors").write_bytes(b"weights")
        revision = "model.safetensors:sha256:" + sha(b"weights")
        wav, screening = self.screening(revision)
        loaded = []

        def loader(path, settings):
            loaded.append(path)
            return lambda audio_path, language: " 새 문장 "

        asr = transports.QwenPrimaryAsr(screening, cache=self.root / "calls", model_path=model,
                                        identity_probe=lambda path: {"backend": "qwen-asr-local", "torchVersion": "t"},
                                        loader=loader)
        opinion = asr.opinion(wav, "두려워하지 마십시오.", LOCALE)
        self.assertEqual(opinion["recognized"], "두려워하지 마십시오")
        self.assertEqual(opinion["settingsSha256"], screening["asrSettingsSha256"])
        self.assertEqual(loaded, [])
        other = qc_fixtures.speech_wav(1.5)
        self.assertEqual(asr.transcribe(other), "새 문장")
        self.assertEqual(asr.transcribe(other), "새 문장")
        self.assertEqual(len(loaded), 1)
        stale = transports.QwenPrimaryAsr(screening, cache=self.root / "c2", model_path=model,
                                          identity_probe=lambda path: {"backend": "qwen-asr-local", "torchVersion": "x"},
                                          loader=loader)
        self.assertTrue(any("runtime" in problem for problem in stale.runtime_problems()))
        with self.assertRaisesRegex(ValueError, "cannot reproduce"):
            stale.transcribe(other)
        _, wrong = self.screening("model.safetensors:sha256:" + "0" * 64)
        self.assertTrue(any("weights" in problem for problem in transports.QwenPrimaryAsr(
            wrong, cache=self.root / "c3", model_path=model,
            identity_probe=lambda path: {"backend": "qwen-asr-local", "torchVersion": "t"}).runtime_problems()))

    def test_tts_render_uses_the_jobs_checkpoint_and_identity(self):
        checkpoint = self.root / "ckpt"
        checkpoint.mkdir()
        (checkpoint / "model.safetensors").write_bytes(b"tts weights")
        (checkpoint / "config.json").write_text(json.dumps({"talker_config": {"spk_id": {"speaker_1": 1}}}))
        job = qc_fixtures.speech_job(LOCALE)
        job["adapter"].update(conditioningSha256=sha(b"tts weights"), speakerKey="speaker_1",
                              languageParameter="Korean", conditioningRef="ref-1")
        made, said = [], []

        class Synth:
            def __init__(self, path, **settings):
                made.append((path, settings))

            def __call__(self, text, language, speaker, *, seed):
                said.append((text, language, speaker, seed))
                return [0.1, -0.1] * 2000, 8000

        mapping = {"schemaVersion": "sermon-speaker-checkpoint-map-v1",
                   "checkpoints": [{"speakerId": job["adapter"]["speakerId"], "checkpointRef": "ref-1",
                                    "path": str(checkpoint)}]}
        render = transports.QwenTtsRender(job, checkpoint=transports.checkpoint_path(job, mapping),
                                          cache=self.root / "tts", synth_factory=Synth)
        first = render("두 사람", LOCALE)
        self.assertEqual(render("두 사람", LOCALE), first)
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0], ("두 사람", "Korean", "speaker_1", 42))
        self.assertEqual(made[0][1]["dtype"], "bfloat16")
        audio_qc.decode_pcm16(first)
        self.assertEqual(basis.waiver.render_identity_problems(render.identity), [])
        self.assertEqual(render.identity["checkpointSha256"], sha(b"tts weights"))
        mapping["checkpoints"][0]["checkpointRef"] = "other"
        with self.assertRaises(ValueError):
            transports.checkpoint_path(job, mapping)


if __name__ == "__main__":
    unittest.main()
