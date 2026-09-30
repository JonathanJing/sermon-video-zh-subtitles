"""Offline synthetic contract tests; numeric fixtures are not production evidence."""
import copy
from decimal import localcontext
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/sermon_delivery_intent"
SPEC = importlib.util.spec_from_file_location("sermon_delivery_intent", ROOT / "scripts/sermon_delivery_intent.py")
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
PLAN_SPEC = importlib.util.spec_from_file_location("legacy_weekly_plan", ROOT / "scripts/prepare_multilingual_weekly_plan.py")
planner = importlib.util.module_from_spec(PLAN_SPEC)
PLAN_SPEC.loader.exec_module(planner)


class DeliveryIntentTest(unittest.TestCase):
    def setUp(self):
        self.request = subject.read_object(FIXTURES / "synthetic-request.json")

    def freeze(self):
        return subject.freeze_intent(self.request)

    def bundle(self, manifest, *, seconds=175):
        measurements = []
        for target in manifest["request"]["requestedLocales"]:
            if target["audioRequirement"] == "text_only":
                continue
            for kind, identity in (("full_text", target["approvedFullText"]),
                                   ("short_script", target["approvedSpokenText"])):
                if identity is None or (kind == "short_script" and identity["kind"] != kind):
                    continue
                measurements.append({"targetLocale": target["targetLocale"], "kind": kind,
                                     "candidateJsonSha256": identity["candidateJsonSha256"],
                                     "humanReviewReceiptJsonSha256": identity["humanReviewReceiptJsonSha256"],
                                     "sourceBindingSha256": subject.canonical_hash(manifest["request"]["source"]),
                                     "measuredDurationSeconds": seconds, "audioSha256": "a" * 64,
                                     "measurementReceiptJsonSha256": "b" * 64,
                                     "method": "decoded_audio", "ratePolicy": "natural_no_time_stretch"})
        return {"schemaVersion": subject.MEASUREMENTS_VERSION,
                "intentSha256": manifest["intentSha256"], "measurements": measurements}

    def make_short(self):
        self.request["requestedLocales"][0]["approvedSpokenText"] = {
            "kind": "short_script", "candidateJsonSha256": "c" * 64,
            "humanReviewReceiptJsonSha256": "d" * 64}

    def make_text_only(self):
        target = self.request["requestedLocales"][0]
        target["audioRequirement"] = "text_only"
        target["approvedSpokenText"] = None
        target["layer3AudioUnavailable"] = {
            "packageJsonSha256": "e" * 64,
            "englishSourcePackageJsonSha256": self.request["source"]["englishSourcePackageJsonSha256"],
            "targetLanguageCandidateJsonSha256": target["approvedFullText"]["candidateJsonSha256"],
            "targetLocale": target["targetLocale"], "status": "audio_unavailable"}
        return target

    def plan(self):
        registry = subject.read_object(ROOT / "config/speaker-voice-registry.json")
        source = {"schemaVersion": planner.SOURCE_SCHEMA_VERSION,
                  "packageId": "english-source-" + "a" * 24,
                  "downstreamInvalidationKey": self.request["source"]["downstreamInvalidationKey"],
                  "status": "candidate_ready_for_translation", "candidateTranslationEligible": True,
                  "translationEligible": False}
        plan = planner.prepare_plan(source, registry, speaker_id="eric_geiger",
                                    target_locales=["zh-Hans", "ko", "es"], mode="shadow")
        self.request["source"]["englishSourcePackageJsonSha256"] = planner.json_sha256(source)
        return plan

    def test_schema_and_committed_fixture_are_valid(self):
        schema = subject.read_object(subject.SCHEMA_PATH)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.freeze())

    def test_frozen_golden_identity_is_stable_and_locale_order_independent(self):
        first = self.freeze()
        golden = subject.read_object(FIXTURES / "synthetic-golden.json")
        self.assertEqual(first["intentSha256"], golden["intentSha256"])
        self.request["requestedLocales"].reverse()
        self.assertEqual(self.freeze(), first)
        subject.validate_intent(first)
        self.assertEqual(len(first["intentSha256"]), 64)

    def test_every_delivery_binding_changes_identity(self):
        original = copy.deepcopy(self.request)
        before = self.freeze()["intentSha256"]
        changes = [
            ("source", "mediaSha256", "f" * 64),
            ("source", "sourceUrlHash", "f" * 64),
            ("source", "downstreamInvalidationKey", "f" * 64),
            ("source", "englishSourcePackageJsonSha256", "f" * 64),
            ("delivery", "webAppVersion", "fixture-web-2"),
            ("delivery", "iosInstalledAppVersion", "fixture-ios-2"),
        ]
        for section, key, value in changes:
            with self.subTest(key=key):
                self.request = copy.deepcopy(original)
                self.request[section][key] = value
                self.assertNotEqual(self.freeze()["intentSha256"], before)
        self.request = copy.deepcopy(original)
        self.request["source"]["window"]["startSeconds"] = 61
        self.assertNotEqual(self.freeze()["intentSha256"], before)
        self.request = copy.deepcopy(original)
        self.request["requestedLocales"].pop()
        self.assertNotEqual(self.freeze()["intentSha256"], before)
        self.request = copy.deepcopy(original)
        self.make_text_only()
        self.assertNotEqual(self.freeze()["intentSha256"], before)

    def test_freezing_and_reporting_do_not_mutate_inputs(self):
        original = copy.deepcopy(self.request)
        manifest = self.freeze()
        bundle = self.bundle(manifest)
        before = copy.deepcopy((manifest, bundle))
        subject.preflight(manifest, bundle)
        self.assertEqual(self.request, original)
        self.assertEqual((manifest, bundle), before)

    def test_missing_measurements_remain_unknown(self):
        report = subject.preflight(self.freeze())
        self.assertEqual(report["offlineStatus"], "unknown")
        self.assertTrue(all(row["fullTextDuration"]["measuredDurationSeconds"] is None for row in report["locales"]))
        self.assertFalse(report["humanApproval"])
        self.assertFalse(report["productionEligible"])
        self.assertFalse(report["publicationAuthorized"])

    def test_missing_approved_identity_is_unknown_and_cannot_be_supplied_by_measurement(self):
        original = self.freeze()
        bundle = self.bundle(original)
        self.request["requestedLocales"][0]["approvedFullText"] = None
        self.request["requestedLocales"][0]["approvedSpokenText"] = None
        manifest = self.freeze()
        report = subject.preflight(manifest)
        self.assertEqual(report["offlineStatus"], "unknown")
        bundle["intentSha256"] = manifest["intentSha256"]
        with self.assertRaises(subject.IntentError):
            subject.preflight(manifest, bundle)

    def test_missing_window_approval_or_media_duration_is_unknown(self):
        for field in ("windowApproval", "mediaDuration"):
            with self.subTest(field=field):
                request = copy.deepcopy(self.request)
                if field == "windowApproval":
                    request["source"]["window"]["approvalReceiptJsonSha256"] = None
                else:
                    request["source"]["mediaDurationSeconds"] = None
                manifest = subject.freeze_intent(request)
                report = subject.preflight(manifest, self.bundle(manifest))
                self.assertEqual(report["offlineStatus"], "unknown")
                self.assertEqual(report["sourceStatus"], "unknown")

    def test_supplied_natural_duration_fit_is_only_offline_pass(self):
        manifest = self.freeze()
        report = subject.preflight(manifest, self.bundle(manifest, seconds=180))
        self.assertEqual(report["offlineStatus"], "pass")
        self.assertEqual(report["availableWindowSeconds"], 180)
        self.assertTrue(all(row["status"] == "not_run" and row["receiptJsonSha256"] is None
                            for row in report["acceptanceMatrix"]))
        self.assertFalse(report["productionEligible"])
        self.assertFalse(report["humanApproval"])

    def test_overrun_fails_and_does_not_compress_or_downgrade(self):
        manifest = self.freeze()
        report = subject.preflight(manifest, self.bundle(manifest, seconds=180.01))
        self.assertEqual(report["offlineStatus"], "fail")
        for row in report["locales"]:
            self.assertEqual(row["spokenDuration"]["overrunSeconds"], 0.01)
            self.assertEqual(row["audioRequirement"], "required")
            self.assertIn("separately_reviewed_short_script", row["nextAction"])

    def test_decimal_window_boundary_does_not_use_float_rounding(self):
        self.request["source"]["window"].update(startSeconds=0.1, endSeconds=0.3)
        manifest = self.freeze()
        report = subject.preflight(manifest, self.bundle(manifest, seconds=0.2))
        self.assertEqual(report["offlineStatus"], "pass")
        self.assertEqual(report["availableWindowSeconds"], 0.2)

    def test_duration_report_is_independent_of_callers_decimal_context(self):
        manifest = self.freeze()
        bundle = self.bundle(manifest, seconds=180.123456789)
        expected = subject.preflight(manifest, bundle)
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(subject.preflight(manifest, bundle), expected)

    def test_separately_approved_short_script_can_fit_after_full_text_overrun(self):
        self.make_short()
        manifest = self.freeze()
        bundle = self.bundle(manifest)
        for item in bundle["measurements"]:
            if item["targetLocale"] == "zh-Hans" and item["kind"] == "full_text":
                item["measuredDurationSeconds"] = 210
        report = subject.preflight(manifest, bundle)
        row = next(row for row in report["locales"] if row["targetLocale"] == "zh-Hans")
        self.assertEqual(row["fullTextDuration"]["status"], "overrun")
        self.assertEqual(row["spokenDuration"]["status"], "fits")
        self.assertEqual(report["offlineStatus"], "pass")

    def test_short_script_needs_both_full_and_short_measured_evidence(self):
        self.make_short()
        manifest = self.freeze()
        for kind in ("full_text", "short_script"):
            with self.subTest(kind=kind):
                bundle = self.bundle(manifest)
                bundle["measurements"] = [item for item in bundle["measurements"]
                                           if not (item["targetLocale"] == "zh-Hans" and item["kind"] == kind)]
                self.assertEqual(subject.preflight(manifest, bundle)["offlineStatus"], "unknown")

    def test_short_script_cannot_reuse_full_candidate_or_review(self):
        for key in ("candidateJsonSha256", "humanReviewReceiptJsonSha256"):
            with self.subTest(key=key):
                self.make_short()
                target = self.request["requestedLocales"][0]
                target["approvedSpokenText"][key] = target["approvedFullText"][key]
                with self.assertRaises(subject.IntentError):
                    self.freeze()

    def test_text_only_requires_explicit_same_locale_layer3_binding(self):
        target = self.make_text_only()
        manifest = self.freeze()
        report = subject.preflight(manifest, self.bundle(manifest))
        row = next(row for row in report["locales"] if row["targetLocale"] == "zh-Hans")
        self.assertEqual(row["duration"]["status"], "not_applicable")
        self.assertEqual(row["status"], "pass")
        checks = {row["checkId"] for row in report["acceptanceMatrix"]}
        self.assertIn("zh-Hans:same_locale_layer3_audio_unavailable", checks)
        self.assertIn("zh-Hans:ios_text_only_compatibility", checks)
        self.assertNotIn("zh-Hans:ios_audio_playback", checks)
        target["layer3AudioUnavailable"] = None
        manifest = self.freeze()
        self.assertEqual(subject.preflight(manifest, self.bundle(manifest))["offlineStatus"], "unknown")

    def test_wrong_layer3_source_locale_text_or_status_is_rejected(self):
        target = self.make_text_only()
        good = copy.deepcopy(target["layer3AudioUnavailable"])
        for key, value in (("targetLocale", "ko"), ("englishSourcePackageJsonSha256", "f" * 64),
                           ("targetLanguageCandidateJsonSha256", "f" * 64), ("status", "human_reviewed")):
            with self.subTest(key=key):
                target["layer3AudioUnavailable"] = {**good, key: value}
                with self.assertRaises(subject.IntentError):
                    self.freeze()

    def test_required_audio_cannot_use_audio_unavailable(self):
        target = self.make_text_only()
        target["audioRequirement"] = "required"
        with self.assertRaises(subject.IntentError):
            self.freeze()

    def test_text_only_cannot_claim_spoken_text_or_consume_measurement(self):
        original = self.freeze()
        bundle = self.bundle(original)
        target = self.make_text_only()
        manifest = self.freeze()
        bundle["intentSha256"] = manifest["intentSha256"]
        with self.assertRaises(subject.IntentError):
            subject.preflight(manifest, bundle)
        target["approvedSpokenText"] = {"kind": "full_text", **target["approvedFullText"]}
        with self.assertRaises(subject.IntentError):
            self.freeze()

    def test_stale_or_cross_locale_measurements_are_rejected(self):
        manifest = self.freeze()
        for key, value in (("candidateJsonSha256", "f" * 64), ("humanReviewReceiptJsonSha256", "f" * 64),
                           ("sourceBindingSha256", "f" * 64), ("targetLocale", "vi"),
                           ("method", "estimated_words_per_minute"), ("ratePolicy", "time_stretched"),
                           ("audioSha256", "A" * 64), ("measurementReceiptJsonSha256", "bad")):
            with self.subTest(key=key):
                bundle = self.bundle(manifest)
                bundle["measurements"][0][key] = value
                with self.assertRaises(subject.IntentError):
                    subject.preflight(manifest, bundle)
        bundle = self.bundle(manifest)
        bundle["intentSha256"] = "0" * 64
        with self.assertRaises(subject.IntentError):
            subject.preflight(manifest, bundle)

    def test_duplicate_measurement_is_rejected(self):
        manifest = self.freeze()
        bundle = self.bundle(manifest)
        bundle["measurements"].append(bundle["measurements"][0])
        with self.assertRaises(subject.IntentError):
            subject.preflight(manifest, bundle)

    def test_duration_must_be_finite_positive_number_not_bool_or_estimate(self):
        manifest = self.freeze()
        for bad in (True, False, "175", 0, -1, math.nan, math.inf, -math.inf, 10**100):
            with self.subTest(bad=bad):
                bundle = self.bundle(manifest)
                bundle["measurements"][0]["measuredDurationSeconds"] = bad
                with self.assertRaises(subject.IntentError):
                    subject.preflight(manifest, bundle)

    def test_full_text_measurement_cannot_hide_wrong_spoken_approval(self):
        self.request["requestedLocales"][0]["approvedSpokenText"]["humanReviewReceiptJsonSha256"] = "f" * 64
        with self.assertRaises(subject.IntentError):
            self.freeze()

    def test_invalid_source_windows_are_rejected(self):
        for start, end in ((240, 240), (241, 240), (-1, 240), (0, 301), (True, 240), (0, math.inf)):
            with self.subTest(start=start, end=end):
                self.request["source"]["window"].update(startSeconds=start, endSeconds=end)
                with self.assertRaises(subject.IntentError):
                    self.freeze()

    def test_duplicate_locale_or_unknown_contract_field_is_rejected(self):
        self.request["requestedLocales"].append(copy.deepcopy(self.request["requestedLocales"][0]))
        with self.assertRaises(subject.IntentError):
            self.freeze()
        self.request["requestedLocales"].pop()
        self.request["source"]["path"] = "/private/secret-media.wav"
        with self.assertRaises(subject.IntentError) as result:
            self.freeze()
        self.assertNotIn("secret-media", str(result.exception))

    def test_schema_and_runtime_reject_trailing_control_chars_in_hashes_and_ids(self):
        schema = subject.read_object(subject.SCHEMA_PATH)
        for path in (("source", "mediaSha256"), ("source", "sourceId"),
                     ("source", "sourceUrlHash"), ("delivery", "webAppVersion")):
            for suffix in ("\n", "\r", "\x00"):
                with self.subTest(path=path, suffix=suffix):
                    request = copy.deepcopy(self.request)
                    request[path[0]][path[1]] += suffix
                    request_schema = {"$ref": "#/$defs/request", "$defs": schema["$defs"]}
                    self.assertTrue(list(Draft202012Validator(request_schema).iter_errors(request)))
                    with self.assertRaises(subject.IntentError):
                        subject.freeze_intent(request)

    def test_oversize_locale_cannot_generate_an_invalid_frozen_manifest(self):
        self.request["requestedLocales"][0]["targetLocale"] = "en" + "-abcdefgh" * 30
        with self.assertRaises(subject.IntentError):
            self.freeze()

    def test_app_root_qr_and_ios_target_are_strict_and_bound(self):
        original = copy.deepcopy(self.request)
        cases = [("qrTargetUrl", "https://example.invalid/?week=wrong"),
                 ("webAppEntryUrl", "https://example.invalid/pages/offline-fixture-week/index.html"),
                 ("iosPageId", "wrong"), ("appRootUrl", "http://example.invalid/"),
                 ("appRootUrl", "https://user:secret@example.invalid/"),
                 ("appRootUrl", "https://example.invalid/\n"),
                 ("appRootUrl", "https://example.invalid/../"),
                 ("appRootUrl", "https://example.invalid/#fragment")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.request = copy.deepcopy(original)
                self.request["delivery"][key] = value
                with self.assertRaises(subject.IntentError):
                    self.freeze()

    def test_acceptance_matrix_covers_all_surfaces_and_cannot_be_edited(self):
        self.request["venueAcceptanceRequired"] = True
        manifest = self.freeze()
        checks = {row["checkId"] for row in manifest["acceptanceMatrix"]}
        for check in ("shared:full_video_asset", "shared:http_assets_and_range",
                      "shared:web_app_refresh_and_entry", "shared:ios_installed_app_refresh_and_entry",
                      "shared:final_qr_decode_and_target", "shared:venue_acceptance",
                      "ko:page_and_english_reference", "es:full_listening_review",
                      "zh-Hans:one_x_video_synchronization"):
            self.assertIn(check, checks)
        manifest["acceptanceMatrix"].pop()
        with self.assertRaises(subject.IntentError):
            subject.validate_intent(manifest)

    def test_tampering_version_and_recomputed_hash_cannot_remove_acceptance(self):
        manifest = self.freeze()
        manifest["acceptanceMatrix"] = []
        payload = {key: value for key, value in manifest.items() if key not in ("intentId", "intentSha256")}
        manifest["intentSha256"] = subject.canonical_hash(payload)
        manifest["intentId"] = "delivery-intent-" + manifest["intentSha256"]
        with self.assertRaises(subject.IntentError):
            subject.validate_intent(manifest)
        manifest = self.freeze()
        manifest["schemaVersion"] = "private-sermon-delivery-intent-v2"
        with self.assertRaises(subject.IntentError):
            subject.validate_intent(manifest)
        manifest = self.freeze()
        manifest["request"]["delivery"]["iosInstalledAppVersion"] = "fixture-ios-2"
        with self.assertRaises(subject.IntentError):
            subject.validate_intent(manifest)

    def test_existing_weekly_planner_is_bound_without_mutation_or_replanning(self):
        plan = self.plan()
        original = copy.deepcopy(plan)
        manifest = subject.freeze_intent(self.request, plan)
        self.assertEqual(manifest["request"]["weeklyPlanBinding"]["jsonSha256"], planner.json_sha256(plan))
        self.assertEqual(plan, original)
        self.assertEqual(plan["scheduling"]["localeBarrier"], "none")
        report = subject.preflight(manifest, self.bundle(manifest), plan)
        self.assertEqual(report["weeklyPlanStatus"], "binding_matches")
        self.assertEqual(report["offlineStatus"], "pass")
        missing = subject.preflight(manifest, self.bundle(manifest))
        self.assertEqual(missing["weeklyPlanStatus"], "unknown")
        self.assertEqual(missing["offlineStatus"], "unknown")

    def test_existing_plan_mismatches_fail_closed(self):
        original = self.plan()
        manifest = subject.freeze_intent(self.request, original)
        for mutation in ("source", "locale", "content", "duplicate"):
            with self.subTest(mutation=mutation):
                plan = copy.deepcopy(original)
                if mutation == "source":
                    plan["englishSourcePackage"]["jsonSha256"] = "f" * 64
                elif mutation == "locale":
                    plan["lanes"].pop()
                elif mutation == "duplicate":
                    plan["lanes"].append(plan["lanes"][0])
                else:
                    plan["lanes"][0]["voice"]["revision"] = "changed"
                with self.assertRaises(subject.IntentError):
                    subject.preflight(manifest, None, plan)

    def test_private_intent_never_implicitly_upgrades_legacy_plan(self):
        plan = self.plan()
        with self.assertRaises(subject.IntentError):
            subject.validate_intent(plan)
        manifest = self.freeze()
        with self.assertRaises(subject.IntentError):
            subject.preflight(manifest, None, plan)
        self.assertEqual(planner.PLAN_SCHEMA_VERSION, "sermon-multilingual-weekly-plan-v1")

    def test_strict_json_rejects_duplicates_constants_surrogates_and_nonobjects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for raw in ('{"x":1,"x":2}', '{"x":{"a":0,"a":1}}', '{"x":NaN}',
                        '{"x":Infinity}', '{"x":1e400}', '[]', '{"x":"\\ud800"}'):
                with self.subTest(raw=raw):
                    path.write_text(raw)
                    with self.assertRaises(subject.IntentError):
                        subject.read_object(path)
        for value in ({1: "key"}, ("tuple",), {"x": math.nan}, {"x": object()}):
            with self.assertRaises(subject.IntentError):
                subject.canonical_hash(value)

    def test_offline_api_never_fetches_or_invokes_processes(self):
        with patch("socket.create_connection", side_effect=AssertionError("network")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("fetch")), \
             patch("subprocess.run", side_effect=AssertionError("process")), \
             patch("subprocess.Popen", side_effect=AssertionError("process")):
            manifest = self.freeze()
            self.assertEqual(subject.preflight(manifest, self.bundle(manifest))["offlineStatus"], "pass")

    def test_reports_have_no_paths_urls_credentials_or_machine_approval(self):
        manifest = self.freeze()
        report = subject.preflight(manifest, self.bundle(manifest))
        encoded = json.dumps(report)
        self.assertNotIn("https://", encoded)
        self.assertNotIn(str(ROOT), encoded)
        self.assertNotIn("approved", {row["status"] for row in report["acceptanceMatrix"]})
        self.assertEqual(report["evidenceAuthority"], "supplied_identity_references_and_measurements_only")

    def test_write_new_never_overwrites_and_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "intent.json"
            subject.write_new(path, self.freeze())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            before = path.read_bytes()
            with self.assertRaises(subject.IntentError):
                subject.write_new(path, {"overwritten": True})
            self.assertEqual(path.read_bytes(), before)
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(subject.IntentError):
                subject.write_new(link, {"overwritten": True})
            self.assertEqual(path.read_bytes(), before)

    def test_cli_exit_codes_and_redacted_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest_path = directory / "intent.json"
            command = [sys.executable, str(ROOT / "scripts/sermon_delivery_intent.py")]
            frozen = subprocess.run(command + ["freeze", "--request", str(FIXTURES / "synthetic-request.json"),
                                                "--out", str(manifest_path)], capture_output=True, text=True)
            self.assertEqual(frozen.returncode, 0, frozen.stderr)
            manifest = subject.read_object(manifest_path)
            for status, seconds, expected in (("unknown", None, 2), ("pass", 175, 0), ("fail", 200, 3)):
                args = command + ["preflight", "--intent", str(manifest_path), "--out", str(directory / (status + ".json"))]
                if seconds is not None:
                    measured = directory / (status + "-measurements.json")
                    measured.write_text(json.dumps(self.bundle(manifest, seconds=seconds)))
                    args += ["--measurements", str(measured)]
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(subject.read_object(directory / (status + ".json"))["offlineStatus"], status)
            failed = subprocess.run(command + ["freeze", "--request", str(directory / "secret-input.json"),
                                                "--out", str(directory / "missing.json")], capture_output=True, text=True)
            self.assertEqual(failed.returncode, 1)
            self.assertNotIn(str(directory), failed.stderr)
            self.assertNotIn("secret-input", failed.stderr)


if __name__ == "__main__":
    unittest.main()
