import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import scripts.collect_production_evidence_matrix as mod


class CollectProductionEvidenceMatrixTest(unittest.TestCase):
    def test_current_partial_evidence_summarizes_missing_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = write_json(root / "config.json", failed_config())
            preflight = write_json(root / "preflight.json", readonly_preflight())
            audio = write_json(root / "audio.json", audio_source_preflight(prepared=False))
            sse = write_json(root / "sse.json", public_sse_smoke())
            archive = write_json(root / "archive.json", offline_archive_preflight(decision="use_asr_fallback"))
            plan = write_json(root / "plan.json", update_plan())
            execution = write_json(root / "execution.json", update_execution())

            report = mod.collect_matrix(
                args_for(
                    config=config,
                    preflight=preflight,
                    audio=audio,
                    sse=sse,
                    archive=archive,
                    plan=plan,
                    execution=execution,
                )
            )

        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertEqual(report["summary"]["warnings"], 3)
        self.assertGreaterEqual(report["summary"]["missing"], 5)
        self.assertIn(
            "Get explicit approval, then run apply_cloud_run_realtime_update_plan.py with --approve --rollback-on-failure.",
            report["nextActions"],
        )
        self.assertEqual(report["updateExecution"]["runtimeTokenSources"], {"INTERNAL_TASK_TOKEN": "secret_manager"})
        self.assertEqual(report["updateExecution"]["missingRuntimeEnv"], [])
        self.assertTrue(report["updatePlan"]["secretReferencesIncluded"])
        self.assertFalse(report["updatePlan"]["secretResourceNamesIncluded"])
        self.assertFalse(report["updateExecution"]["secretReferencesIncluded"])
        self.assertFalse(report["updateExecution"]["secretResourceNamesIncluded"])
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])

    def test_missing_optional_evidence_file_does_not_abort_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = write_json(root / "config.json", failed_config())
            missing_asr = root / "missing-asr.json"

            report = mod.collect_matrix(args_for(config=config, asr_smoke=missing_asr))

        self.assertEqual(report["status"], "incomplete")
        row = next(row for row in report["matrix"] if row["id"] == "offline_asr_route")
        self.assertEqual(row["state"], "missing")
        self.assertIn("no-caption archive", row["nextAction"])
        self.assertIn("ASR fallback", row["nextAction"])

    def test_missing_cloud_run_preflight_declares_realtime_session_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_preflight = root / "missing-preflight.json"

            report = mod.collect_matrix(args_for(preflight=missing_preflight))

        row = next(row for row in report["matrix"] if row["id"] == "cloud_run_api_preflight")
        self.assertEqual(row["state"], "missing")
        self.assertIn("--internal-task-token", row["nextAction"])
        self.assertEqual(row["observed"]["expectedRealtimeSession"]["model"], "gpt-realtime-translate")
        self.assertEqual(row["observed"]["expectedRealtimeSession"]["targetLanguage"], "zh")
        self.assertEqual(row["observed"]["expectedRealtimeSession"]["audioSourceKind"], "ipad_mic")
        self.assertIn("realtime_local_session_metadata", row["observed"]["expectedChecks"])

    def test_stale_cloud_run_preflight_without_session_metadata_check_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = ready_preflight()
            data["checks"] = [{"name": "realtime_local_session_create", "state": "pass", "observed": None}]
            preflight = write_json(root / "preflight.json", data)

            report = mod.collect_matrix(args_for(preflight=preflight))

        row = next(row for row in report["matrix"] if row["id"] == "cloud_run_api_preflight")
        self.assertEqual(row["state"], "warn")
        self.assertIn("realtime_local_session_metadata", row["observed"]["missingChecks"])
        self.assertEqual(row["observed"]["expectedRealtimeSession"]["targetLanguage"], "zh")

    def test_complete_when_all_external_evidence_is_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = write_json(root / "config.json", ready_config())
            preflight = write_json(root / "preflight.json", ready_preflight())
            audio = write_json(root / "audio.json", audio_source_preflight(prepared=True))
            server = write_json(root / "server-realtime.json", server_realtime_contract())
            web = write_json(root / "web-realtime.json", web_realtime_contract())
            live_1130_plan = write_json(root / "live-1130.json", live_1130_run_plan())
            handoff = write_json(root / "handoff.json", realtime_handoff_validation())
            public_view = write_json(root / "public-view.json", public_caption_view_runtime())
            sse = write_json(root / "sse.json", public_sse_smoke())
            stable_contract = write_json(root / "stable-contract.json", stable_correction_contract())
            archive = write_json(root / "archive.json", offline_archive_preflight(decision="use_caption_track"))
            worker_plan = write_json(root / "worker-plan.json", worker_publish_plan())
            offline_chain = write_json(root / "offline-chain.json", ok_offline_chain_validation("use_caption_track"))
            no_caption_plan = write_json(root / "no-caption-plan.json", no_caption_asr_plan())
            caption = write_json(root / "caption.json", readiness_report("use_caption_track"))
            asr_smoke = write_json(root / "asr-smoke.json", offline_asr_smoke(status="ok"))
            asr_chain = write_json(root / "asr-chain.json", ok_offline_chain_validation("use_asr_fallback"))
            sunday_manifest = write_json(root / "sunday-manifest-validation.json", sunday_manifest_validation())

            report = mod.collect_matrix(
                args_for(
                    config=config,
                    preflight=preflight,
                    audio=audio,
                    server=server,
                    web=web,
                    live_1130_plan=live_1130_plan,
                    handoff=handoff,
                    public_view=public_view,
                    sse=sse,
                    stable_contract=stable_contract,
                    archive=archive,
                    worker_plan=worker_plan,
                    offline_chain_validation=offline_chain,
                    offline_asr_chain_validation=asr_chain,
                    no_caption_plan=no_caption_plan,
                    asr_smoke=asr_smoke,
                    sunday_manifest=sunday_manifest,
                    readiness=[caption],
                )
            )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["summary"]["passed"], 18)
        self.assertEqual(report["nextActions"], [])
        preflight_row = next(row for row in report["matrix"] if row["id"] == "cloud_run_api_preflight")
        self.assertEqual(preflight_row["observed"]["expectedRealtimeSession"]["audioSourceKind"], "ipad_mic")
        self.assertIn("realtime_local_session_metadata", preflight_row["observed"]["expectedChecks"])

    def test_caption_readiness_without_offline_chain_validation_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caption = write_json(root / "caption.json", readiness_report("use_caption_track"))

            report = mod.collect_matrix(args_for(readiness=[caption]))

        row = next(row for row in report["matrix"] if row["id"] == "offline_caption_route")
        self.assertEqual(row["state"], "warn")
        self.assertIn("validate_offline_chain.py", row["nextAction"])

    def test_ok_offline_chain_validation_can_prove_caption_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            offline_chain = write_json(root / "offline-chain.json", ok_offline_chain_validation("use_caption_track"))

            report = mod.collect_matrix(args_for(offline_chain_validation=offline_chain))

        row = next(row for row in report["matrix"] if row["id"] == "offline_caption_route")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["translation"]["model"], "gpt-5.5-mini")
        self.assertEqual(row["observed"]["notRealtimeChain"], "pass")

    def test_no_caption_asr_fallback_plan_report_marks_plan_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = write_json(root / "no-caption-plan.json", no_caption_asr_plan())

            report = mod.collect_matrix(args_for(no_caption_plan=plan))

        row = next(row for row in report["matrix"] if row["id"] == "offline_asr_fallback_plan")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["requiredModels"]["offlineAsr"], "gpt-4o-transcribe")
        self.assertEqual(row["observed"]["requiredModels"]["offlineTranslation"], "gpt-5.5-mini")
        self.assertTrue(row["observed"]["checks"]["offlineValidationCommand"])

    def test_no_caption_asr_fallback_plan_fails_without_not_realtime_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = no_caption_asr_plan()
            data["passCriteria"] = [
                item for item in data["passCriteria"] if "not_realtime_chain" not in item
            ]
            plan = write_json(root / "no-caption-plan.json", data)

            report = mod.collect_matrix(args_for(no_caption_plan=plan))

        row = next(row for row in report["matrix"] if row["id"] == "offline_asr_fallback_plan")
        self.assertEqual(row["state"], "fail")
        self.assertIn("offlineValidationCommand", row["observed"]["failedChecks"])

    def test_complete_offline_chain_validation_beats_stale_failed_translation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            offline_chain = write_json(root / "offline-chain.json", ok_offline_chain_validation("use_caption_track"))
            translation = write_json(root / "translation.json", failed_translation_report())

            report = mod.collect_matrix(args_for(offline_chain_validation=offline_chain, translation=translation))

        row = next(row for row in report["matrix"] if row["id"] == "offline_caption_route")
        self.assertEqual(row["state"], "pass")
        self.assertTrue(row["evidence"].endswith("offline-chain.json"))
        self.assertEqual(row["observed"]["notRealtimeChain"], "pass")

    def test_offline_chain_validation_requires_not_realtime_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = ok_offline_chain_validation("use_caption_track")
            for check in data["checks"]:
                if check["name"] == "not_realtime_chain":
                    check["state"] = "fail"
            data["status"] = "failed"
            data["failedChecks"] = ["not_realtime_chain"]
            offline_chain = write_json(root / "offline-chain.json", data)

            report = mod.collect_matrix(args_for(offline_chain_validation=offline_chain))

        row = next(row for row in report["matrix"] if row["id"] == "offline_caption_route")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["notRealtimeChain"], "fail")
        self.assertIn("offline chain validation", row["nextAction"])

    def test_worker_publish_plan_passes_when_captions_promote_before_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_plan = write_json(root / "worker-plan.json", worker_publish_plan())

            report = mod.collect_matrix(args_for(worker_plan=worker_plan))

        row = next(row for row in report["matrix"] if row["id"] == "offline_worker_publish_plan")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["stages"][-1], "promote")
        self.assertFalse(row["observed"]["notesIncluded"])

    def test_worker_publish_plan_fails_when_notes_block_caption_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = worker_publish_plan()
            data["stages"] = [
                "model-access",
                "prepare",
                "translate",
                "export-captions",
                "validate-offline",
                "upload-playback",
                "notes",
                "upload-manifest",
                "promote",
            ]
            data["notesIncluded"] = True
            data["promoteBeforeNotes"] = False
            worker_plan = write_json(root / "worker-plan.json", data)

            report = mod.collect_matrix(args_for(worker_plan=worker_plan))

        row = next(row for row in report["matrix"] if row["id"] == "offline_worker_publish_plan")
        self.assertEqual(row["state"], "fail")
        self.assertIn("publishes captions", row["nextAction"])

    def test_server_realtime_contract_report_marks_worker_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = write_json(root / "server-realtime.json", server_realtime_contract())

            report = mod.collect_matrix(args_for(server=server))

        row = next(row for row in report["matrix"] if row["id"] == "server_media_worker_contract")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["models"]["realtimeDraft"], "gpt-realtime-translate")
        self.assertTrue(row["observed"]["backendRealtimeSessionPolicy"]["allowedRealtimeTranslateZh"])
        self.assertTrue(row["observed"]["backendRealtimeSessionPolicy"]["rejectsWrongModel"])
        self.assertTrue(row["observed"]["backendRealtimeSessionPolicy"]["rejectsWrongTargetLanguage"])
        self.assertTrue(row["observed"]["mediaWorkerModelPolicy"]["allowsRealtimeTranslateZh"])
        self.assertTrue(row["observed"]["mediaWorkerModelPolicy"]["rejectsWrongRealtimeModel"])
        self.assertTrue(row["observed"]["mediaWorkerModelPolicy"]["rejectsWrongTargetLanguage"])
        self.assertTrue(row["observed"]["mediaWorkerModelPolicy"]["allowsGpt4oTranscribeFallback"])
        self.assertTrue(row["observed"]["mediaWorkerModelPolicy"]["rejectsWrongFallbackModel"])

    def test_failed_server_realtime_contract_report_marks_worker_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = write_json(root / "server-realtime.json", server_realtime_contract(status="failed"))

            report = mod.collect_matrix(args_for(server=server))

        row = next(row for row in report["matrix"] if row["id"] == "server_media_worker_contract")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["failedChecks"], ["nested_output_transcript_mapping"])

    def test_web_realtime_contract_report_marks_browser_webrtc_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web = write_json(root / "web-realtime.json", web_realtime_contract())

            report = mod.collect_matrix(args_for(web=web))

        row = next(row for row in report["matrix"] if row["id"] == "browser_webrtc_contract")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["models"]["realtimeDraft"], "gpt-realtime-translate")
        self.assertEqual(row["observed"]["normalizationProbe"]["status"], "ok")
        self.assertEqual(row["observed"]["normalizationProbe"]["caseCount"], 2)
        self.assertEqual(row["observed"]["sessionProbe"]["status"], "ok")
        self.assertTrue(row["observed"]["sessionProbe"]["createUsesRealtimeTranslate"])
        self.assertTrue(row["observed"]["sessionProbe"]["createTargetsChinese"])
        self.assertTrue(row["observed"]["sessionProbe"]["createUsesIpadMic"])
        self.assertTrue(row["observed"]["sessionProbe"]["backendPostUsesSessionEndpoint"])
        self.assertTrue(row["observed"]["sessionProbe"]["backendPostUsesEventTokenHeader"])
        self.assertTrue(row["observed"]["sessionProbe"]["backendPostStoresChineseDelta"])
        self.assertTrue(row["observed"]["sessionProbe"]["backendPostDoesNotIncludeClientSecret"])
        self.assertTrue(row["observed"]["sessionProbe"]["backendPostDoesNotIncludeEventToken"])
        self.assertEqual(row["observed"]["sessionProbe"]["persistedEvents"], 1)
        self.assertEqual(row["observed"]["sessionProbe"]["persistFailures"], 0)
        self.assertEqual(row["observed"]["noBrowserSpeechSuccessFallback"]["state"], "pass")
        self.assertEqual(row["observed"]["noBrowserSpeechSuccessFallback"]["forbiddenPresent"], [])

    def test_web_realtime_contract_requires_runtime_normalization_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = web_realtime_contract()
            data.pop("normalizationProbe")
            web = write_json(root / "web-realtime.json", data)

            report = mod.collect_matrix(args_for(web=web))

        row = next(row for row in report["matrix"] if row["id"] == "browser_webrtc_contract")
        self.assertEqual(row["state"], "fail")
        self.assertIn("openai_event_normalization_runtime", row["observed"]["failedChecks"])
        self.assertIn("runtime OpenAI event normalization probe", row["nextAction"])

    def test_web_realtime_contract_requires_session_persistence_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = web_realtime_contract()
            data["normalizationProbe"].pop("sessionProbe")
            web = write_json(root / "web-realtime.json", data)

            report = mod.collect_matrix(args_for(web=web))

        row = next(row for row in report["matrix"] if row["id"] == "browser_webrtc_contract")
        self.assertEqual(row["state"], "fail")
        self.assertIn("browser_session_backend_persistence_probe", row["observed"]["failedChecks"])
        self.assertIn("browser session persistence", row["nextAction"])

    def test_web_realtime_contract_requires_no_browser_speech_success_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = web_realtime_contract()
            for check in data["checks"]:
                if check["name"] == "no_browser_speech_success_fallback":
                    check["state"] = "fail"
                    check["forbiddenPresent"] = ["await startBrowserSpeechMicFallback();"]
            web = write_json(root / "web-realtime.json", data)

            report = mod.collect_matrix(args_for(web=web))

        row = next(row for row in report["matrix"] if row["id"] == "browser_webrtc_contract")
        self.assertEqual(row["state"], "fail")
        self.assertIn("no_browser_speech_success_fallback", row["observed"]["failedChecks"])
        self.assertEqual(
            row["observed"]["noBrowserSpeechSuccessFallback"]["forbiddenPresent"],
            ["await startBrowserSpeechMicFallback();"],
        )

    def test_live_1130_run_plan_report_marks_operator_plan_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_1130_plan = write_json(root / "live-1130.json", live_1130_run_plan())

            report = mod.collect_matrix(args_for(live_1130_plan=live_1130_plan))

        row = next(row for row in report["matrix"] if row["id"] == "live_1130_realtime_run_plan")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["targetWindow"]["liveCaptionStart"], "11:30 PT")
        self.assertEqual(row["observed"]["modelPolicy"]["realtimeDraftModel"], "gpt-realtime-translate")
        self.assertIn("browser_webrtc_ipad_or_iphone_mic", row["observed"]["operatorChoices"])
        self.assertIn("server_worker_authorized_audio", row["observed"]["operatorChoices"])

    def test_live_1130_run_plan_fails_when_offline_guard_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = live_1130_run_plan()
            data["passCriteria"] = [
                criterion
                for criterion in data["passCriteria"]
                if criterion != "Offline post-live route never uses gpt-realtime-translate."
            ]
            live_1130_plan = write_json(root / "live-1130.json", data)

            report = mod.collect_matrix(args_for(live_1130_plan=live_1130_plan))

        row = next(row for row in report["matrix"] if row["id"] == "live_1130_realtime_run_plan")
        self.assertEqual(row["state"], "fail")
        self.assertIn("offline_not_realtime_guard", row["observed"]["failedChecks"])
        self.assertIn("offline non-realtime guards", row["nextAction"])

    def test_realtime_handoff_validation_report_marks_handoff_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = write_json(root / "handoff.json", realtime_handoff_validation())

            report = mod.collect_matrix(args_for(handoff=handoff))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_handoff_validation")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["checkCount"], 19)
        self.assertIn("goLiveSequence", row["observed"]["reports"])

    def test_realtime_handoff_validation_fails_when_browser_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = realtime_handoff_validation()
            data["requiredEvidenceReports"] = [
                item for item in data["requiredEvidenceReports"] if item != "artifacts/evidence/web-realtime-contract.json"
            ]
            handoff = write_json(root / "handoff.json", data)

            report = mod.collect_matrix(args_for(handoff=handoff))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_handoff_validation")
        self.assertEqual(row["state"], "fail")
        self.assertIn(
            "artifacts/evidence/web-realtime-contract.json",
            row["observed"]["missingRequiredEvidenceReports"],
        )

    def test_failed_web_realtime_contract_report_marks_browser_webrtc_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web = write_json(root / "web-realtime.json", web_realtime_contract(status="failed"))

            report = mod.collect_matrix(args_for(web=web))

        row = next(row for row in report["matrix"] if row["id"] == "browser_webrtc_contract")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["failedChecks"], ["openai_realtime_webrtc"])

    def test_public_caption_view_runtime_report_marks_runtime_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_view = write_json(root / "public-view.json", public_caption_view_runtime())

            report = mod.collect_matrix(args_for(public_view=public_view))

        row = next(row for row in report["matrix"] if row["id"] == "public_caption_view_runtime")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["eventSourceUrl"], "/api/realtime/sessions/current/events")
        self.assertTrue(row["observed"]["draftCaptionVisible"])
        self.assertTrue(row["observed"]["stableCaptionVisible"])
        self.assertTrue(row["observed"]["englishDeltaSaved"])
        self.assertTrue(row["observed"]["segmentStable"])

    def test_failed_public_caption_view_runtime_report_marks_runtime_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_view = write_json(root / "public-view.json", public_caption_view_runtime(status="failed"))

            report = mod.collect_matrix(args_for(public_view=public_view))

        row = next(row for row in report["matrix"] if row["id"] == "public_caption_view_runtime")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["failedChecks"], ["stable_correction_replaces_draft"])

    def test_stable_correction_contract_report_marks_contract_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stable_contract = write_json(root / "stable-contract.json", stable_correction_contract())

            report = mod.collect_matrix(args_for(stable_contract=stable_contract))

        row = next(row for row in report["matrix"] if row["id"] == "stable_correction_contract")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["models"]["stableCorrection"], "gpt-5.5-mini")
        self.assertTrue(row["observed"]["stableEvent"]["hasSegmentId"])
        self.assertTrue(row["observed"]["stableModelPolicy"]["allowsGpt55Mini"])
        self.assertTrue(row["observed"]["stableModelPolicy"]["rejectsRealtimeTranslate"])
        self.assertTrue(row["observed"]["stableModelPolicy"]["rejectsGpt55Substitute"])

    def test_stable_correction_contract_report_fails_without_segment_id_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = stable_correction_contract()
            for check in data["checks"]:
                if check["name"] == "stable_corrections_are_caption_final_events":
                    check["observed"]["segmentId"] = None
                    check["observed"]["hasSegmentId"] = False
            stable_contract = write_json(root / "stable-contract.json", data)

            report = mod.collect_matrix(args_for(stable_contract=stable_contract))

        row = next(row for row in report["matrix"] if row["id"] == "stable_correction_contract")
        self.assertEqual(row["state"], "fail")
        self.assertFalse(row["observed"]["stableEvent"]["hasSegmentId"])
        self.assertIn("stable correction event contract", row["nextAction"])

    def test_failed_stable_correction_contract_report_marks_contract_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stable_contract = write_json(
                root / "stable-contract.json",
                stable_correction_contract(status="failed"),
            )

            report = mod.collect_matrix(args_for(stable_contract=stable_contract))

        row = next(row for row in report["matrix"] if row["id"] == "stable_correction_contract")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["failedChecks"], ["stable_corrections_are_caption_final_events"])

    def test_local_sse_smoke_is_warning_not_production_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sse = write_json(root / "sse.json", public_sse_smoke(base_url="http://127.0.0.1:8080"))

            report = mod.collect_matrix(args_for(sse=sse))

        sse_row = next(row for row in report["matrix"] if row["id"] == "realtime_public_sse_contract")
        self.assertEqual(sse_row["state"], "warn")
        self.assertIn("deployed Cloud Run URL", sse_row["nextAction"])
        self.assertEqual(
            sse_row["observed"]["sse"]["sessionStarted"]["audioSourceKind"],
            "ipad_mic",
        )
        self.assertEqual(sse_row["observed"]["eventPayloadSource"]["kind"], "web_realtime_contract_normalization_probe")
        self.assertEqual(sse_row["observed"]["postedEvents"][0]["type"], "input_transcript_delta")

    def test_public_sse_smoke_includes_session_validation_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sse = write_json(
                root / "sse.json",
                public_sse_smoke(
                    session_validation={
                        "status": "ok",
                        "eventsJsonl": "gs://bucket/realtime-events/2026-06-28/rt_test.jsonl",
                        "counts": {"events": 4, "stableCorrectionEvents": 1},
                        "targetLanguages": ["zh"],
                        "audioSourceKinds": ["ipad_mic"],
                    }
                ),
            )

            report = mod.collect_matrix(args_for(sse=sse))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_public_sse_contract")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["sessionValidation"]["status"], "ok")
        self.assertEqual(row["observed"]["sessionValidation"]["counts"]["stableCorrectionEvents"], 1)
        self.assertEqual(row["observed"]["sessionValidation"]["targetLanguages"], ["zh"])
        self.assertEqual(row["observed"]["sessionValidation"]["audioSourceKinds"], ["ipad_mic"])

    def test_public_sse_smoke_backfills_session_metadata_from_sse_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sse = write_json(
                root / "sse.json",
                public_sse_smoke(
                    base_url="http://127.0.0.1:8080",
                    session_validation={
                        "status": "ok",
                        "eventsJsonl": "rt_test.jsonl",
                        "counts": {"events": 4},
                    },
                ),
            )

            report = mod.collect_matrix(args_for(sse=sse))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_public_sse_contract")
        self.assertEqual(row["state"], "warn")
        self.assertEqual(row["observed"]["sessionValidation"]["targetLanguages"], ["zh"])
        self.assertEqual(row["observed"]["sessionValidation"]["audioSourceKinds"], ["ipad_mic"])

    def test_stale_public_sse_smoke_without_metadata_checks_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = public_sse_smoke()
            data["checks"] = [{"name": "sse_receives_session_started", "state": "pass", "observed": None}]
            sse = write_json(root / "sse.json", data)

            report = mod.collect_matrix(args_for(sse=sse))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_public_sse_contract")
        self.assertEqual(row["state"], "warn")
        self.assertIn("sse_session_metadata", row["observed"]["missingChecks"])
        self.assertIn("sse_stable_correction_matches_draft_segment", row["observed"]["missingChecks"])

    def test_public_sse_smoke_fails_when_session_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sse = write_json(
                root / "sse.json",
                public_sse_smoke(
                    session_validation={
                        "status": "failed",
                        "eventsJsonl": "rt_test.jsonl",
                        "failedChecks": ["stable_correction"],
                    }
                ),
            )

            report = mod.collect_matrix(args_for(sse=sse))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_public_sse_contract")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["sessionValidation"]["failedChecks"], ["stable_correction"])
        self.assertIn("session JSONL validation", row["nextAction"])

    def test_deployed_public_sse_session_validation_can_prove_stable_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sse = write_json(
                root / "sse.json",
                public_sse_smoke(session_validation=stable_public_sse_session_validation()),
            )

            report = mod.collect_matrix(args_for(sse=sse))

        row = next(row for row in report["matrix"] if row["id"] == "stable_correction")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["sessionValidation"]["counts"]["stableCorrectionEvents"], 1)
        self.assertTrue(row["observed"]["stableCorrection"]["matched"])

    def test_local_public_sse_stable_correction_is_warning_not_production_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sse = write_json(
                root / "sse.json",
                public_sse_smoke(
                    base_url="http://127.0.0.1:8080",
                    session_validation=stable_public_sse_session_validation(),
                ),
            )

            report = mod.collect_matrix(args_for(sse=sse))

        row = next(row for row in report["matrix"] if row["id"] == "stable_correction")
        self.assertEqual(row["state"], "warn")
        self.assertIn("deployed Cloud Run URL", row["nextAction"])
        self.assertEqual(row["observed"]["sessionValidation"]["counts"]["stableCorrectionEvents"], 1)

    def test_failed_offline_translation_report_marks_caption_route_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translation = write_json(root / "translation.json", failed_translation_report())

            report = mod.collect_matrix(args_for(translation=translation))

        row = next(row for row in report["matrix"] if row["id"] == "offline_caption_route")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["model"], "gpt-5.5-mini")
        self.assertEqual(row["observed"]["httpStatus"], 404)
        self.assertEqual(row["observed"]["failureKind"], "model_unavailable_or_not_found")
        self.assertIn("model/access", row["nextAction"])

    def test_failed_offline_chain_validation_is_included_with_caption_route_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translation = write_json(root / "translation.json", failed_translation_report())
            validation = write_json(root / "offline-chain-validation.json", failed_offline_chain_validation())

            report = mod.collect_matrix(args_for(translation=translation, offline_chain_validation=validation))

        row = next(row for row in report["matrix"] if row["id"] == "offline_caption_route")
        self.assertEqual(row["state"], "fail")
        self.assertTrue(row["evidence"].endswith("translation.json"))
        self.assertEqual(row["observed"]["model"], "gpt-5.5-mini")
        self.assertEqual(row["observed"]["failureKind"], "model_unavailable_or_not_found")
        self.assertEqual(
            row["observed"]["offlineChainValidation"]["failedChecks"],
            ["input_readable_zh_vtt", "input_readable_zh_srt"],
        )

    def test_failed_model_access_marks_stable_and_caption_routes_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_access = write_json(root / "model-access.json", failed_model_access_report())

            report = mod.collect_matrix(args_for(model_access=model_access))

        stable = next(row for row in report["matrix"] if row["id"] == "stable_correction")
        caption = next(row for row in report["matrix"] if row["id"] == "offline_caption_route")
        self.assertEqual(stable["state"], "fail")
        self.assertEqual(caption["state"], "fail")
        self.assertEqual(stable["observed"]["model"], "gpt-5.5-mini")
        self.assertEqual(stable["observed"]["failureKind"], "model_unavailable_or_not_found")
        self.assertEqual(caption["observed"]["failureKind"], "model_unavailable_or_not_found")
        self.assertEqual(caption["observed"]["httpStatus"], 404)

    def test_available_alternative_model_does_not_satisfy_required_mini_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_access = write_json(root / "model-access.json", failed_model_access_report())
            alternative_access = write_json(root / "model-access-gpt-5.5.json", ok_model_access_report("gpt-5.5"))

            report = mod.collect_matrix(args_for(model_access=model_access, alternative_model_access=[alternative_access]))

        stable = next(row for row in report["matrix"] if row["id"] == "stable_correction")
        caption = next(row for row in report["matrix"] if row["id"] == "offline_caption_route")
        self.assertEqual(stable["state"], "fail")
        self.assertEqual(caption["state"], "fail")
        self.assertEqual(stable["observed"]["model"], "gpt-5.5-mini")
        self.assertEqual(stable["observed"]["availableButNotConfiguredModels"], ["gpt-5.5"])
        self.assertIn("do not substitute", stable["observed"]["alternativeModelPolicy"])

    def test_stable_correction_validation_requires_matching_realtime_draft_segment_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validation = write_json(
                root / "realtime-validation.json",
                realtime_session_validation(
                    check_names=[
                        "jsonl_has_events",
                        "event_ids_strictly_increasing",
                        "session_id_consistent",
                        "target_language",
                        "audio_source_kind",
                        "stable_correction",
                    ],
                    stable_corrections=1,
                ),
            )

            report = mod.collect_matrix(args_for(realtime_validation=validation))

        row = next(row for row in report["matrix"] if row["id"] == "stable_correction")
        self.assertEqual(row["state"], "warn")
        self.assertIn("stable_correction_matches_realtime_draft_segment", row["observed"]["missingChecks"])
        self.assertIn("--require-stable-correction", row["nextAction"])
        self.assertIn("caption_final", row["nextAction"])

    def test_realtime_openai_no_transcript_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            realtime = write_json(root / "realtime.json", realtime_openai_smoke(status="no_transcript"))

            report = mod.collect_matrix(args_for(realtime_openai=realtime))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_live")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["model"], "gpt-realtime-translate")
        self.assertIn("both Chinese", row["nextAction"])

    def test_realtime_openai_missing_input_transcript_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            realtime = write_json(root / "realtime.json", realtime_openai_smoke(status="missing_input_transcript"))

            report = mod.collect_matrix(args_for(realtime_openai=realtime))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_live")
        self.assertEqual(row["state"], "fail")
        self.assertFalse(row["observed"]["inputTranscriptAvailable"])

    def test_realtime_openai_ok_marks_realtime_live_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            realtime = write_json(root / "realtime.json", realtime_openai_smoke(status="ok"))
            validation = write_json(root / "realtime-validation.json", realtime_session_validation())

            report = mod.collect_matrix(args_for(realtime_openai=realtime, realtime_validation=validation))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_live")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["validation"]["sessionIds"], ["rt_test"])
        self.assertEqual(row["observed"]["validation"]["targetLanguages"], ["zh"])
        self.assertEqual(row["observed"]["validation"]["audioSourceKinds"], ["authorized_audio_file"])
        self.assertEqual(row["observed"]["inputTranscriptMode"], "openai_realtime")

    def test_realtime_openai_synthetic_audio_is_warning_not_field_run_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            realtime = realtime_openai_smoke(status="ok")
            realtime["audio"]["file"] = "artifacts/evidence/realtime-source/synthetic-authorized-speech.wav"
            realtime = write_json(root / "realtime.json", realtime)
            validation = write_json(root / "realtime-validation.json", realtime_session_validation())

            report = mod.collect_matrix(args_for(realtime_openai=realtime, realtime_validation=validation))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_live")
        self.assertEqual(row["state"], "warn")
        self.assertEqual(row["observed"]["sourceEvidence"], "synthetic_smoke")
        self.assertIn("synthetic audio only", row["nextAction"])

    def test_realtime_openai_ok_identifies_audio_api_input_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            realtime = write_json(root / "realtime.json", realtime_openai_smoke(status="ok", fallback_input=True))
            validation = write_json(
                root / "realtime-validation.json",
                realtime_session_validation(realtime_input_events=0),
            )

            report = mod.collect_matrix(args_for(realtime_openai=realtime, realtime_validation=validation))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_live")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["inputTranscriptMode"], "audio_api_fallback")
        self.assertEqual(row["observed"]["validation"]["counts"]["realtimeInputTranscriptEvents"], 0)

    def test_realtime_openai_ok_without_jsonl_validation_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            realtime = write_json(root / "realtime.json", realtime_openai_smoke(status="ok"))

            report = mod.collect_matrix(args_for(realtime_openai=realtime))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_live")
        self.assertEqual(row["state"], "warn")
        self.assertIn("validate_realtime_session.py", row["nextAction"])

    def test_stale_realtime_validation_is_warning_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            realtime = write_json(root / "realtime.json", realtime_openai_smoke(status="ok"))
            validation = write_json(
                root / "stale-validation.json",
                realtime_session_validation(check_names=["jsonl_has_events", "caption_events"]),
            )

            report = mod.collect_matrix(args_for(realtime_openai=realtime, realtime_validation=validation))

        row = next(row for row in report["matrix"] if row["id"] == "realtime_live")
        self.assertEqual(row["state"], "warn")
        self.assertIn("missingChecks", row["observed"])

    def test_offline_asr_smoke_marks_asr_route_warning_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asr_smoke = write_json(root / "asr-smoke.json", offline_asr_smoke(status="ok"))

            report = mod.collect_matrix(args_for(asr_smoke=asr_smoke))

        row = next(row for row in report["matrix"] if row["id"] == "offline_asr_route")
        self.assertEqual(row["state"], "warn")
        self.assertEqual(row["observed"]["model"], "gpt-4o-transcribe")
        self.assertEqual(row["observed"]["cueCount"], 1)
        self.assertIn("--offline-asr-chain-validation-report", row["nextAction"])

    def test_asr_smoke_and_offline_chain_validation_can_prove_asr_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asr_smoke = write_json(root / "asr-smoke.json", offline_asr_smoke(status="ok"))
            asr_chain = write_json(root / "asr-chain.json", ok_offline_chain_validation("use_asr_fallback"))

            report = mod.collect_matrix(
                args_for(asr_smoke=asr_smoke, offline_asr_chain_validation=asr_chain)
            )

        row = next(row for row in report["matrix"] if row["id"] == "offline_asr_route")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["offlineRoute"]["decision"], "use_asr_fallback")
        self.assertEqual(row["observed"]["asr"]["model"], "gpt-4o-transcribe")
        self.assertTrue(row["observed"]["asr"]["used"])
        self.assertEqual(row["observed"]["translation"]["model"], "gpt-5.5-mini")
        self.assertEqual(row["observed"]["notRealtimeChain"], "pass")
        self.assertEqual(row["observed"]["asrSmoke"]["cueCount"], 1)

    def test_asr_chain_validation_must_be_for_asr_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asr_smoke = write_json(root / "asr-smoke.json", offline_asr_smoke(status="ok"))
            caption_chain = write_json(root / "caption-chain.json", ok_offline_chain_validation("use_caption_track"))

            report = mod.collect_matrix(
                args_for(asr_smoke=asr_smoke, offline_asr_chain_validation=caption_chain)
            )

        row = next(row for row in report["matrix"] if row["id"] == "offline_asr_route")
        self.assertEqual(row["state"], "fail")
        self.assertIn("openai_asr", row["nextAction"])

    def test_failed_offline_asr_smoke_marks_asr_route_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asr_smoke = write_json(root / "asr-smoke.json", offline_asr_smoke(status="failed"))

            report = mod.collect_matrix(args_for(asr_smoke=asr_smoke))

        row = next(row for row in report["matrix"] if row["id"] == "offline_asr_route")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["model"], "gpt-4o-transcribe")

    def test_sunday_manifest_validation_report_marks_gcs_manifest_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sunday_manifest = write_json(root / "sunday-manifest-validation.json", sunday_manifest_validation())

            report = mod.collect_matrix(args_for(sunday_manifest=sunday_manifest))

        row = next(row for row in report["matrix"] if row["id"] == "cloud_run_gcs_manifest")
        self.assertEqual(row["state"], "pass")
        self.assertEqual(row["observed"]["status"], "ok")
        self.assertTrue(row["observed"]["publicGcsArtifacts"])
        self.assertTrue(row["observed"]["readableArtifactsRequired"])
        self.assertEqual(row["observed"]["outputs"]["chineseVtt"], ["artifacts/sermon.zh.live-aligned.vtt"])

    def test_gcs_manifest_shape_without_readability_check_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shape_only = sunday_manifest_validation()
            shape_only["readableArtifactsRequired"] = False
            sunday_manifest = write_json(root / "sunday-manifest-validation.json", shape_only)

            report = mod.collect_matrix(args_for(sunday_manifest=sunday_manifest))

        row = next(row for row in report["matrix"] if row["id"] == "cloud_run_gcs_manifest")
        self.assertEqual(row["state"], "warn")
        self.assertIn("--require-readable-artifacts", row["nextAction"])

    def test_local_sunday_manifest_contract_is_warning_not_gcs_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = sunday_manifest_validation()
            local["manifest"] = "artifacts/evidence/manifest-promotion-guard/cloud-manifest.json"
            local["artifactLocation"] = "local"
            local["publicGcsArtifacts"] = False
            sunday_manifest = write_json(root / "sunday-manifest-validation.json", local)
            publish_plan = write_json(root / "publish-plan.json", gcs_manifest_publish_plan())

            report = mod.collect_matrix(args_for(sunday_manifest=sunday_manifest, gcs_publish_plan=publish_plan))

        row = next(row for row in report["matrix"] if row["id"] == "cloud_run_gcs_manifest")
        self.assertEqual(row["state"], "warn")
        self.assertIn("Upload/promote", row["nextAction"])
        self.assertEqual(row["observed"]["publishPlan"]["status"], "planned")
        self.assertEqual(row["observed"]["publishPlan"]["artifactCount"], 3)

    def test_gcs_manifest_publish_plan_warns_when_validation_report_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            publish_plan = write_json(root / "publish-plan.json", gcs_manifest_publish_plan())

            report = mod.collect_matrix(args_for(gcs_publish_plan=publish_plan))

        row = next(row for row in report["matrix"] if row["id"] == "cloud_run_gcs_manifest")
        self.assertEqual(row["state"], "warn")
        self.assertEqual(row["observed"]["stableManifestUri"], "gs://bucket/sundays/2026-06-28/cloud-manifest.json")

    def test_failed_sunday_manifest_validation_report_marks_gcs_manifest_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sunday_manifest = write_json(
                root / "sunday-manifest-validation.json",
                sunday_manifest_validation(status="failed", failed_checks=["caption_readable_vtt"]),
            )

            report = mod.collect_matrix(args_for(sunday_manifest=sunday_manifest))

        row = next(row for row in report["matrix"] if row["id"] == "cloud_run_gcs_manifest")
        self.assertEqual(row["state"], "fail")
        self.assertEqual(row["observed"]["failedChecks"], ["caption_readable_vtt"])


def args_for(config=None, preflight=None, audio=None, server=None, web=None, live_1130_plan=None, handoff=None, public_view=None, sse=None, realtime_openai=None, realtime_validation=None, stable_contract=None, archive=None, worker_plan=None, offline_chain_validation=None, offline_asr_chain_validation=None, no_caption_plan=None, asr_smoke=None, translation=None, sunday_manifest=None, gcs_publish_plan=None, model_access=None, alternative_model_access=None, plan=None, execution=None, readiness=None):
    return Namespace(
        production_readiness_report=[str(path) for path in readiness or []],
        cloud_run_config_report=str(config) if config else None,
        cloud_run_api_preflight_report=str(preflight) if preflight else None,
        realtime_audio_source_preflight_report=str(audio) if audio else None,
        server_realtime_contract_report=str(server) if server else None,
        web_realtime_contract_report=str(web) if web else None,
        live_1130_run_plan_report=str(live_1130_plan) if live_1130_plan else None,
        realtime_handoff_validation_report=str(handoff) if handoff else None,
        public_caption_view_runtime_report=str(public_view) if public_view else None,
        realtime_public_sse_smoke_report=str(sse) if sse else None,
        realtime_openai_smoke_report=str(realtime_openai) if realtime_openai else None,
        realtime_session_validation_report=str(realtime_validation) if realtime_validation else None,
        stable_correction_contract_report=str(stable_contract) if stable_contract else None,
        offline_archive_preflight_report=str(archive) if archive else None,
        offline_worker_plan_report=str(worker_plan) if worker_plan else None,
        offline_chain_validation_report=str(offline_chain_validation) if offline_chain_validation else None,
        offline_asr_chain_validation_report=str(offline_asr_chain_validation) if offline_asr_chain_validation else None,
        no_caption_asr_plan_report=str(no_caption_plan) if no_caption_plan else None,
        offline_asr_smoke_report=str(asr_smoke) if asr_smoke else None,
        offline_translation_report=str(translation) if translation else None,
        sunday_manifest_validation_report=str(sunday_manifest) if sunday_manifest else None,
        gcs_manifest_publish_plan=str(gcs_publish_plan) if gcs_publish_plan else None,
        openai_model_access_preflight_report=str(model_access) if model_access else None,
        openai_alternative_model_access_preflight_report=[str(path) for path in alternative_model_access or []],
        update_plan=str(plan) if plan else None,
        update_execution=str(execution) if execution else None,
        out=None,
    )


def write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def failed_config():
    return {
        "status": "failed",
        "failedChecks": ["single_instance_realtime_sse"],
        "cloudRun": {"maxInstances": 20},
    }


def ready_config():
    return {
        "status": "ok",
        "failedChecks": [],
        "cloudRun": {"maxInstances": 1},
    }


def readonly_preflight():
    return {
        "status": "ok",
        "warnings": ["cloud_run_realtime_config", "realtime_local_session_create"],
    }


def ready_preflight():
    return {
        "status": "ok",
        "warnings": [],
        "checks": [
            {"name": "realtime_local_session_create", "state": "pass", "observed": None},
            {"name": "realtime_local_session_metadata", "state": "pass", "observed": None},
        ],
        "realtimeSession": {
            "status": 201,
            "ready": True,
            "eventTokenReturned": True,
            "targetLanguage": "zh",
            "audioSourceKind": "ipad_mic",
        },
    }


def audio_source_preflight(*, prepared: bool):
    return {
        "status": "ok",
        "warnings": [] if prepared else ["prepare_audio"],
        "source": {
            "kind": "authorized_audio_file",
            "display": "/tmp/source.wav",
            "authorizationAssumption": "operator-provided-authorized-source",
        },
    }


def web_realtime_contract(*, status: str = "ok"):
    failed = [] if status == "ok" else ["openai_realtime_webrtc"]
    return {
        "status": status,
        "failedChecks": failed,
        "checks": [
            {
                "name": "no_browser_speech_success_fallback",
                "state": "pass" if status == "ok" else "fail",
                "missing": [],
                "forbiddenPresent": [],
            }
        ],
        "normalizationProbe": {
            "status": "ok" if status == "ok" else "failed",
            "results": [
                {"name": "output_delta", "state": "pass"},
                {"name": "nested_input_delta", "state": "pass"},
            ],
            "sessionProbe": {
                "status": "ok" if status == "ok" else "failed",
                "checks": {
                    "createUsesRealtimeTranslate": True,
                    "createTargetsChinese": True,
                    "createUsesIpadMic": True,
                    "backendPostUsesSessionEndpoint": True,
                    "backendPostUsesEventTokenHeader": True,
                    "backendPostStoresChineseDelta": True,
                    "backendPostDoesNotIncludeClientSecret": True,
                    "backendPostDoesNotIncludeEventToken": True,
                },
                "persistedEvents": 1,
                "persistFailures": 0,
            },
        },
        "models": {
            "realtimeDraft": "gpt-realtime-translate",
            "stableCorrection": "gpt-5.5-mini",
        },
        "path": "ipad/iphone mic -> browser WebRTC -> gpt-realtime-translate -> backend session events -> public caption SSE",
    }


def public_caption_view_runtime(*, status: str = "ok"):
    failed = [] if status == "ok" else ["stable_correction_replaces_draft"]
    return {
        "status": status,
        "failedChecks": failed,
        "models": {
            "realtimeDraft": "gpt-realtime-translate",
            "stableCorrection": "gpt-5.5-mini",
        },
        "path": "public caption view receives realtime session events and replaces draft with stable correction",
        "probe": {
            "eventSourceUrl": "/api/realtime/sessions/current/events",
            "eventSourceListeners": [
                "caption_delta",
                "caption_final",
                "input_transcript_delta",
                "input_transcript_final",
            ],
            "draftCaption": "神爱世人" if status == "ok" else "",
            "stableCaption": "神爱世人。" if status == "ok" else "",
            "segmentEn": "God loved the world" if status == "ok" else "",
            "segmentStable": status == "ok",
        },
    }


def server_realtime_contract(*, status: str = "ok"):
    failed = [] if status == "ok" else ["nested_output_transcript_mapping"]
    return {
        "status": status,
        "failedChecks": failed,
        "checks": [
            {
                "name": "backend_realtime_session_policy",
                "state": "pass",
                "observed": {
                    "allowedRealtimeTranslateZh": True,
                    "rejectsWrongModel": True,
                    "rejectsWrongTargetLanguage": True,
                },
            },
            {
                "name": "media_worker_model_policy",
                "state": "pass",
                "observed": {
                    "allowsRealtimeTranslateZh": True,
                    "rejectsWrongRealtimeModel": True,
                    "rejectsWrongTargetLanguage": True,
                    "allowsGpt4oTranscribeFallback": True,
                    "rejectsWrongFallbackModel": True,
                },
            },
        ],
        "models": {
            "realtimeDraft": "gpt-realtime-translate",
            "inputTranscriptFallback": "gpt-4o-transcribe",
        },
        "path": "youtube live/authorized audio -> server media worker -> gpt-realtime-translate -> backend session events -> public caption SSE",
    }


def live_1130_run_plan():
    return {
        "status": "ready_for_operator_review",
        "targetWindow": {
            "liveCaptionStart": "11:30 PT",
            "publicReadinessDeadline": "11:50 PT",
        },
        "modelPolicy": {
            "realtimeDraftModel": "gpt-realtime-translate",
            "stableCorrectionModel": "gpt-5.5-mini",
            "offlineAsrModel": "gpt-4o-transcribe",
            "offlineTranslationModel": "gpt-5.5-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
            "doNotSubstituteGpt55ForGpt55Mini": True,
        },
        "operatorChoices": [
            {
                "id": "browser_webrtc_ipad_or_iphone_mic",
                "source": "iPad/iPhone mic",
                "path": "browser WebRTC -> gpt-realtime-translate -> backend session events -> public caption SSE",
            },
            {
                "id": "server_worker_authorized_audio",
                "source": "authorized audio URL/file or authorized YouTube live source",
                "path": "server media worker -> gpt-realtime-translate -> backend session events -> public caption SSE",
            },
        ],
        "passCriteria": [
            "Realtime session uses gpt-realtime-translate and targetLanguage=zh.",
            "English input transcript deltas and Chinese caption deltas are saved as backend session events.",
            "Offline post-live route never uses gpt-realtime-translate.",
        ],
    }


def realtime_handoff_validation():
    return {
        "status": "ok",
        "failedChecks": [],
        "checks": [
            *[{"name": f"check_{index}", "state": "pass", "observed": None} for index in range(18)],
            {"name": "go_live_no_caption_asr_stage", "state": "pass", "observed": None},
        ],
        "reports": {
            "livePlan": "artifacts/evidence/live-1130-realtime-run-plan.json",
            "operatorBundle": "artifacts/evidence/operator-approval-bundle.json",
            "goLiveSequence": "artifacts/evidence/production-go-live-sequence.json",
        },
        "requiredEvidenceReports": [
            "artifacts/evidence/web-realtime-contract.json",
            "artifacts/evidence/public-caption-view-runtime.json",
            "artifacts/evidence/realtime-public-sse-smoke.json",
            "artifacts/evidence/realtime-public-sse-smoke.session-validation.json",
        ],
        "models": {
            "realtimeDraftModel": "gpt-realtime-translate",
            "stableCorrectionModel": "gpt-5.5-mini",
            "offlineAsrModel": "gpt-4o-transcribe",
            "offlineTranslationModel": "gpt-5.5-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def stable_correction_contract(*, status: str = "ok"):
    failed = [] if status == "ok" else ["stable_corrections_are_caption_final_events"]
    return {
        "status": status,
        "failedChecks": failed,
        "checks": [
            {
                "name": "stable_corrections_are_caption_final_events",
                "state": "pass" if status == "ok" else "fail",
                "observed": {
                    "count": 1,
                    "type": "caption_final",
                    "source": "gpt-5.5-mini-stable-correction",
                    "model": "gpt-5.5-mini",
                    "final": True,
                    "segmentId": "seg_1",
                    "hasSegmentId": True,
                    "hasChinese": True,
                    "hasEnglish": True,
                },
            },
            {
                "name": "stable_correction_model_policy",
                "state": "pass",
                "observed": {
                    "allowsGpt55Mini": True,
                    "rejectsRealtimeTranslate": True,
                    "rejectsGpt55Substitute": True,
                },
            },
        ],
        "models": {
            "stableCorrection": "gpt-5.5-mini",
        },
        "path": "saved realtime English/Chinese deltas -> gpt-5.5-mini -> caption_final stable corrections -> backend session events",
    }


def public_sse_smoke(base_url="https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app", session_validation=None):
    return {
        "status": "ok",
        "baseUrl": base_url,
        "sessionId": "rt_test",
        "sse": {
            "eventsRead": 4,
            "types": ["session_started", "input_transcript_delta", "caption_delta", "caption_final"],
            "sessionStarted": {
                "model": "gpt-realtime-translate",
                "targetLanguage": "zh",
                "audioSourceKind": "ipad_mic",
            },
            "stableCorrection": {
                "matched": True,
                "draftSegments": ["smoke_1"],
                "stableCorrectionSegments": ["smoke_1"],
                "matchedSegments": ["smoke_1"],
            },
        },
        "postedEvents": [
            {"type": "input_transcript_delta", "status": 202},
            {"type": "caption_delta", "status": 202},
        ],
        "eventPayloadSource": {
            "kind": "web_realtime_contract_normalization_probe",
            "report": "artifacts/evidence/web-realtime-contract.json",
        },
        "checks": [
            {"name": "browser_normalized_event_payloads", "state": "pass", "observed": None},
            {"name": "create_local_session_metadata", "state": "pass", "observed": None},
            {"name": "sse_session_metadata", "state": "pass", "observed": None},
            {
                "name": "sse_stable_correction_matches_draft_segment",
                "state": "pass",
                "observed": {
                    "matched": True,
                    "draftSegments": ["smoke_1"],
                    "stableCorrectionSegments": ["smoke_1"],
                    "matchedSegments": ["smoke_1"],
                },
            },
        ],
        "sessionValidation": session_validation or {"status": "skipped"},
    }


def stable_public_sse_session_validation():
    return {
        "status": "ok",
        "eventsJsonl": "rt_test.jsonl",
        "counts": {
            "events": 4,
            "inputTranscriptEvents": 1,
            "realtimeInputTranscriptEvents": 1,
            "realtimeCaptionEvents": 1,
            "stableCorrectionEvents": 1,
        },
        "targetLanguages": ["zh"],
        "audioSourceKinds": ["ipad_mic"],
        "failedChecks": [],
    }


def realtime_openai_smoke(*, status: str, fallback_input: bool = False):
    caption_count = 1 if status in {"ok", "missing_input_transcript"} else 0
    input_count = 1 if status == "ok" else 0
    return {
        "status": status,
        "model": "gpt-realtime-translate",
        "audio": {"file": "artifacts/source.wav", "maxAudioSeconds": 2},
        "openaiRealtime": {
            "audioChunksSent": 20,
            "openaiEventsReceived": 19,
            "captionEventsPosted": caption_count,
            "inputTranscriptEventsPosted": input_count,
            "inputTranscriptFallback": {
                "enabled": fallback_input,
                "eventsPosted": input_count if fallback_input else 0,
                "model": "gpt-4o-transcribe",
                "status": "ok" if fallback_input else "skipped",
            },
        },
        "sse": {
            "eventsRead": 4,
            "captionEvents": caption_count,
            "inputTranscriptEvents": input_count,
        },
        "inputTranscriptAvailable": bool(input_count),
    }


def realtime_session_validation(*, check_names=None, stable_corrections=0, realtime_input_events=1):
    names = check_names or [
        "jsonl_has_events",
        "event_ids_strictly_increasing",
        "session_id_consistent",
        "secret_strings",
        "realtime_sources",
        "target_language",
        "audio_source_kind",
        "input_transcript_events",
        "input_transcript_english",
        "caption_events",
        "caption_chinese",
        "realtime_model",
    ]
    if check_names is None and stable_corrections and "stable_correction" not in names:
        names.append("stable_correction")
    if check_names is None and stable_corrections and "stable_correction_matches_realtime_draft_segment" not in names:
        names.append("stable_correction_matches_realtime_draft_segment")
    return {
        "status": "ok",
        "eventsJsonl": "rt_test.jsonl",
        "checks": [{"name": name, "state": "pass", "observed": None} for name in names],
        "failedChecks": [],
        "counts": {
            "events": 4,
            "inputTranscriptEvents": 1,
            "realtimeInputTranscriptEvents": realtime_input_events,
            "realtimeCaptionEvents": 1,
            "stableCorrectionEvents": stable_corrections,
        },
        "models": ["gpt-realtime-translate"],
        "sessionIds": ["rt_test"],
        "realtimeSources": ["openai_realtime_translation_ws"],
        "targetLanguages": ["zh"],
        "audioSourceKinds": ["authorized_audio_file"],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def offline_archive_preflight(*, decision: str):
    return {
        "status": "ok",
        "warnings": ["asr_fallback_planned"] if decision == "use_asr_fallback" else [],
        "offlineRoute": {
            "strategy": "captions_first_then_asr",
            "decision": decision,
            "selectedSourceKind": "none" if decision == "use_asr_fallback" else "live_archive",
        },
    }


def worker_publish_plan():
    return {
        "status": "ok",
        "commandCount": 8,
        "stages": [
            "model-access",
            "prepare",
            "translate",
            "export-captions",
            "validate-offline",
            "upload-playback",
            "upload-manifest",
            "promote",
        ],
        "translationMode": "fresh_model_call",
        "notesIncluded": False,
        "promoteBeforeNotes": True,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def no_caption_asr_plan():
    return {
        "status": "needs_real_no_caption_archive",
        "requiredSource": {
            "kind": "youtube_live_archive",
            "captionRequirement": "No requested English caption track is available.",
            "authorizationRequirement": "Use only a source we are authorized to process.",
        },
        "requiredModels": {
            "offlineAsr": "gpt-4o-transcribe",
            "offlineTranslation": "gpt-5.5-mini",
            "forbiddenOfflineModel": "gpt-realtime-translate",
        },
        "commands": [
            [
                "python3",
                "scripts/run_offline_archive_preflight.py",
                "--asr-model",
                "gpt-4o-transcribe",
            ],
            [
                "python3",
                "scripts/prepare_live_link_playback.py",
                "--asr-model",
                "gpt-4o-transcribe",
                "--gcs-dry-run",
            ],
            [
                "python3",
                "scripts/translate_playback_with_openai.py",
                "--model",
                "gpt-5.5-mini",
            ],
            [
                "python3",
                "scripts/export_playback_captions.py",
                "--gcs-dry-run",
            ],
            [
                "python3",
                "scripts/validate_offline_chain.py",
                "--expected-asr-model",
                "gpt-4o-transcribe",
                "--expected-translation-model",
                "gpt-5.5-mini",
            ],
            ["python3", "scripts/validate_production_readiness.py"],
        ],
        "passCriteria": [
            "run_offline_archive_preflight.py reports decision=use_asr_fallback.",
            "Prepared offline report has caption_source.kind=openai_asr.",
            "ASR model is gpt-4o-transcribe.",
            "Chinese translation model is gpt-5.5-mini.",
            "validate_offline_chain.py status is ok and not_realtime_chain passes.",
            "validate_production_readiness.py output records offlineRoute.decision=use_asr_fallback.",
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def update_plan():
    return {
        "status": "approval_required",
        "requiresExplicitApproval": True,
        "plannedChanges": [{"name": "single_instance_realtime_sse", "needed": True}],
        "secretReferencesIncluded": True,
        "secretResourceNamesIncluded": False,
    }


def update_execution():
    return {
        "status": "dry_run",
        "approved": False,
        "runtimeTokenSources": {"INTERNAL_TASK_TOKEN": "secret_manager"},
        "missingRuntimeEnv": [],
        "apiKeyMaterialIncluded": False,
        "secretReferencesIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def failed_translation_report():
    return {
        "status": "failed",
        "failureStage": "openai_translation",
        "model": "gpt-5.5-mini",
        "httpStatus": 404,
        "failureKind": "model_unavailable_or_not_found",
        "error": "The model does not exist or you do not have access to it.",
        "translatedSegments": 0,
        "totalSegments": 12,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def failed_offline_chain_validation():
    return {
        "schemaVersion": 1,
        "status": "failed",
        "failedChecks": ["input_readable_zh_vtt", "input_readable_zh_srt"],
        "inputs": {
            "report": "artifacts/evidence/offline-caption-route/artifacts/report.json",
            "playbackJs": "artifacts/evidence/offline-caption-route/web/playback-simulation.generated.js",
            "zhVtt": "artifacts/evidence/offline-caption-route/artifacts/sermon.zh.live-aligned.vtt",
            "zhSrt": "artifacts/evidence/offline-caption-route/artifacts/sermon.zh.live-aligned.srt",
            "manifest": None,
        },
        "offlineRoute": None,
        "translation": {"model": None, "translatedSegments": 0, "totalSegments": 0},
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def ok_offline_chain_validation(decision: str):
    return {
        "schemaVersion": 1,
        "status": "ok",
        "failedChecks": [],
        "checks": [
            {"name": "not_realtime_chain", "state": "pass", "observed": None},
            {"name": "zh_vtt_timeline_alignment", "state": "pass", "observed": None},
            {"name": "zh_srt_timeline_alignment", "state": "pass", "observed": None},
        ],
        "offlineRoute": {
            "strategy": "captions_first_then_asr",
            "decision": decision,
            "selectedSourceKind": "live_archive" if decision == "use_caption_track" else "openai_asr",
            "asrFallbackRequired": decision == "use_asr_fallback",
            "audioExtractionAttempted": decision == "use_asr_fallback",
        },
        "translation": {
            "model": "gpt-5.5-mini",
            "translatedSegments": 12,
            "totalSegments": 12,
        },
        "asr": {
            "model": "gpt-4o-transcribe",
            "used": decision == "use_asr_fallback",
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def failed_model_access_report():
    return {
        "status": "failed",
        "models": ["gpt-5.5-mini"],
        "failedChecks": ["responses_model:gpt-5.5-mini"],
        "checks": [
            {
                "name": "api_key_secret_access",
                "state": "pass",
                "observed": "secret value read from Secret Manager",
            },
            {
                "name": "responses_model:gpt-5.5-mini",
                "state": "fail",
                "observed": {
                    "status": "failed",
                    "model": "gpt-5.5-mini",
                    "endpoint": "responses",
                    "httpStatus": 404,
                    "failureKind": "model_unavailable_or_not_found",
                    "error": "The model does not exist or you do not have access to it.",
                },
            },
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def ok_model_access_report(model: str):
    return {
        "status": "ok",
        "models": [model],
        "failedChecks": [],
        "checks": [
            {
                "name": "api_key_secret_access",
                "state": "pass",
                "observed": "secret value read from Secret Manager",
            },
            {
                "name": f"responses_model:{model}",
                "state": "pass",
                "observed": {
                    "status": "ok",
                    "model": model,
                    "endpoint": "responses",
                    "httpStatus": 200,
                    "responseJson": {"ok": True},
                },
            },
        ],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def offline_asr_smoke(*, status: str):
    return {
        "status": status,
        "asr": {"provider": "openai", "model": "gpt-4o-transcribe"},
        "cueCount": 1 if status == "ok" else 0,
        "source": {"kind": "authorized_extracted_audio_sample", "path": "artifacts/source.wav"},
        "error": None if status == "ok" else "ASR failed",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def sunday_manifest_validation(*, status: str = "ok", failed_checks=None):
    return {
        "status": status,
        "manifest": "gs://bucket/sundays/2026-06-28/cloud-manifest.json",
        "artifactLocation": "gcs",
        "publicGcsArtifacts": True,
        "readableArtifactsRequired": True,
        "sunday": "2026-06-28",
        "failedChecks": failed_checks or [],
        "outputs": {
            "playbackJs": "web/playback-simulation.generated.js",
            "chineseVtt": ["artifacts/sermon.zh.live-aligned.vtt"],
            "chineseSrt": ["artifacts/sermon.zh.live-aligned.srt"],
        },
        "playback": {
            "translationStatus": "ready",
            "translatedSegments": 12,
            "totalSegments": 12,
        },
        "captions": [
            {"type": ".vtt", "readable": True},
            {"type": ".srt", "readable": True},
        ],
    }


def gcs_manifest_publish_plan():
    return {
        "status": "planned",
        "artifactLocation": "gcs",
        "runManifestUri": "gs://bucket/sundays/2026-06-28/runs/local-manifest-contract/artifacts/cloud-manifest.json",
        "stableManifestUri": "gs://bucket/sundays/2026-06-28/cloud-manifest.json",
        "artifacts": [
            {"localPath": "web/playback-simulation.generated.js"},
            {"localPath": "artifacts/sermon.zh.live-aligned.vtt"},
            {"localPath": "artifacts/sermon.zh.live-aligned.srt"},
        ],
        "commands": [["gcloud"], ["gcloud"], ["gcloud"], ["gcloud"], ["gcloud"], ["python3"]],
        "gcsManifestValidation": {
            "status": "ok",
            "artifactLocation": "gcs",
            "publicGcsArtifacts": True,
            "readableArtifactsRequired": False,
        },
        "appliedSteps": [],
    }


def readiness_report(decision: str):
    return {
        "status": "ok",
        "offline": {
            "offlineRoute": {
                "strategy": "captions_first_then_asr",
                "decision": decision,
            }
        },
        "sundayManifest": {"status": "ok"},
        "realtime": {
            "counts": {
                "realtimeCaptionEvents": 2,
                "stableCorrectionEvents": 1,
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
