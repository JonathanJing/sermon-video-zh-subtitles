"""Offline App gate checks using existing source-builder and audio fixtures.

Every human receipt here is explicitly synthetic. No device, server or model is
used; fixture WAVs exercise the existing decoder and package validators.
"""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from scripts import sermon_app_delivery as app
from scripts import build_english_source_package as source_builder
from tests import test_build_english_source_package as source_fixtures
from tests import test_stage_formal_multilingual_dev as audio_fixtures


class AppDeliveryTests(unittest.TestCase):
    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        return self.reference(path)

    def reference(self, path, *, is_json=True):
        result = {"path": str(path.relative_to(self.root)), "sha256": app.stage.file_sha(path)}
        if is_json:
            result["jsonSha256"] = app.digest(json.loads(path.read_text()))
        return result

    def setUp(self):
        self.source_fixture = source_fixtures.EnglishSourcePackageTests("test_bound_human_review_promotes_layer_one_only")
        self.source_fixture.setUp()
        self.addCleanup(self.source_fixture.doCleanups)
        self.root = self.source_fixture.root
        # Two real anchor units let coverage regressions remain valid JSON.
        second = copy.deepcopy(self.source_fixture.segments[0])
        second.update(id=1, referenceChunkId="block-01", start=2.0, end=3.9)
        for word in second["wordTimes"]:
            word["start"] += 2.0; word["end"] += 2.0
        self.source_fixture.segments.append(second)
        self.write("segments.json", self.source_fixture.segments)
        self.source_fixture.manifest = source_fixtures.anchors.build_anchor_manifest(
            self.source_fixture.segments, source_path=self.source_fixture.segments_path,
            unit_policy=source_fixtures.anchors.UNIT_POLICY_V2)
        self.write("anchor-manifest.json", self.source_fixture.manifest)
        source_unit_ids = [unit["sourceUnitId"] for unit in self.source_fixture.manifest["sourceUnits"]]
        review = {"schemaVersion": source_builder.REVIEW_SCHEMA_VERSION,
                  "alignedSegmentsSha256": source_builder.file_sha256(self.source_fixture.segments_path),
                  "anchorManifestJsonSha256": app.digest(self.source_fixture.manifest),
                  "humanApproval": True, "reviewedBy": "Synthetic source reviewer",
                  "reviewedAt": "2026-10-03T10:00:00Z", "reviewedSourceUnitIds": source_unit_ids,
                  "checks": {key: "approved" for key in source_builder.APPROVED_CHECKS}}
        self.write("source-human-review.json", review)
        self.source = self.source_fixture.build(review_path=self.root / "source-human-review.json")
        self.source_ref = self.write("source.json", self.source)
        self.old_audio_fixture = audio_fixtures.FormalDevStageTests()
        self.old_audio_fixture.setUp()
        self.addCleanup(self.old_audio_fixture.tearDown)
        shutil.copyfile(self.old_audio_fixture.audio_file, self.root / "tone.wav")
        self.tone_ref = self.reference(self.root / "tone.wav", is_json=False)
        self.plan = {"schemaVersion": "sermon-app-delivery-plan-v1", "pageId": "fixture-app-page",
                     "sourceId": self.source["source"]["sourceId"],
                     "sourceUrlHash": self.source["source"]["sourceUrlHash"], "source": self.source_ref,
                     "contentRevision": "fixture-revision-1", "contentHash": "0" * 64,
                     "locales": ["ko"], "products": {}, "allowTextOnlyLocales": [],
                     "clientCapabilities": {}, "approvalReceipts": {}, "productionRuns": {},
                     "pdfAdHoc": {"status": "not_requested"},
                     "testEnvironments": {environment: {"environmentId": environment + "-fixture",
                        "appVersion": "test-app-1", "clientProtocolVersion": "test-protocol-1"}
                        for environment in app.TEST_ENVIRONMENTS},
                     "productionEnvironments": {environment: {"environmentId": environment + "-fixture",
                        "appVersion": "production-app-1", "clientProtocolVersion": "production-protocol-1"}
                        for environment in app.PRODUCTION_ENVIRONMENTS}}
        self.make_locale("ko")
        self.freeze()

    def make_locale(self, locale):
        fixture = self.old_audio_fixture
        candidate = json.loads(fixture.paths["candidate"][locale].read_text())
        candidate["englishSourcePackageJsonSha256"] = app.digest(self.source)
        candidate["anchorManifestSha256"] = self.source["anchors"]["artifact"]["jsonSha256"]
        source_ids = self.source["review"]["reviewedSourceUnitIds"]
        candidate["groups"][0]["sourceUnitIds"] = source_ids
        candidate["groups"][0]["coverage"] = [{"sourceUnitId": source_id,
            "targetText": candidate["groups"][0]["targetText"]} for source_id in source_ids]
        candidate_ref = self.write(locale + "-translation.json", candidate)
        receipt = json.loads(fixture.paths["receipt"][locale].read_text())
        receipt.update(englishSourcePackageJsonSha256=app.digest(self.source),
                       anchorManifestJsonSha256=candidate["anchorManifestSha256"],
                       candidateJsonSha256=app.digest(candidate))
        translation_review = self.write(locale + "-translation-review.json", receipt)
        package = json.loads(fixture.paths["audio"][locale].read_text())
        package.update(englishSourcePackageJsonSha256=app.digest(self.source),
                       targetLanguageCandidateJsonSha256=app.digest(candidate))
        package["track"] = dict(self.tone_ref)
        package["units"][0]["audio"] = dict(self.tone_ref)
        captions = json.loads(Path(json.loads(fixture.paths["audio"][locale].read_text())["captions"]["path"]).read_text())
        package["captions"] = self.write(locale + "-captions.json", captions)
        schedule = json.loads(Path(json.loads(fixture.paths["audio"][locale].read_text())["schedule"]["path"]).read_text())
        schedule["entries"][0]["sourceUnitIds"] = source_ids
        package["schedule"] = self.write(locale + "-schedule.json", schedule)
        package_ref = self.write(locale + "-audio.json", package)
        receipt = json.loads(fixture.paths["audio_receipt"][locale].read_text())
        receipt.update(englishSourcePackageJsonSha256=app.digest(self.source),
                       targetLanguageCandidateJsonSha256=app.digest(candidate),
                       targetLanguageAudioPackageJsonSha256=app.digest(package),
                       trackSha256=self.tone_ref["sha256"])
        audio_review = self.write(locale + "-audio-review.json", receipt)
        products = {"translation": {"status": "available", "artifact": candidate_ref, "review": translation_review},
                    "audio": {"status": "available", "artifact": package_ref, "review": audio_review}}
        for product in ("outline", "reflection"):
            value = {"schemaVersion": "sermon-app-study-product-v1", "pageId": self.plan["pageId"],
                     "targetLocale": locale, "product": product,
                     "contentRevision": self.plan["contentRevision"],
                     "englishSourcePackageJsonSha256": app.digest(self.source),
                     "targetLanguageCandidateJsonSha256": app.digest(candidate),
                     "items": [{"id": product + "-1", "text": "Synthetic reviewed study content",
                                "sourceUnitIds": source_ids}]}
            reference = self.write(locale + "-" + product + ".json", value)
            receipt = {key: value[key] for key in ("pageId", "targetLocale", "product", "contentRevision",
                        "englishSourcePackageJsonSha256", "targetLanguageCandidateJsonSha256")}
            receipt.update(schemaVersion="sermon-app-product-human-review-v1", decision="approved",
                           reviewer="Synthetic study reviewer", reviewedAt="2026-10-03T10:00:00Z",
                           artifactSha256=reference["sha256"], artifactJsonSha256=app.digest(value),
                           reviewedItemIds=[product + "-1"])
            products[product] = {"status": "available", "artifact": reference,
                                "review": self.write(locale + "-" + product + "-review.json", receipt)}
        self.plan["products"][locale] = products

    def freeze(self):
        self.plan["contentHash"] = app.content_hash(self.plan)
        self.write("plan.json", self.plan)

    def inspect(self):
        self.write("plan.json", self.plan)
        return app.inspect(self.root / "plan.json")

    def client_proof(self, *, supports_text_only=False):
        self.freeze()
        evidence = self.write("client-proof.json", {"note": "Synthetic compatibility observation, no real device"})
        for locale in self.plan["locales"]:
            references = {}
            for environment in app.TEST_ENVIRONMENTS:
                products = self.plan["products"][locale]
                value = {"schemaVersion": "sermon-app-client-capability-v1", "environment": environment,
                         "client": self.plan["testEnvironments"][environment], "pageId": self.plan["pageId"],
                         "targetLocale": locale, "contentRevision": self.plan["contentRevision"],
                         "contentHash": self.plan["contentHash"], "supportsAudioUnavailable": supports_text_only,
                         "supportedProductSchemas": {product: json.loads((self.root / row["artifact"]["path"]).read_text())["schemaVersion"]
                            if "artifact" in row else None for product, row in products.items()},
                         "productArtifactSha256s": {product: row.get("artifact", {}).get("sha256") for product, row in products.items()},
                         "evidence": evidence, "decision": "approved", "reviewer": "Synthetic client reviewer",
                         "reviewedAt": "2026-10-03T11:00:00Z"}
                references[environment] = self.write(locale + "-" + environment + "-capability.json", value)
            self.plan["clientCapabilities"][locale] = references

    def approve(self):
        for environment in app.TEST_ENVIRONMENTS:
            value = {"schemaVersion": "sermon-app-human-review-v1", "environment": environment,
                     "client": self.plan["testEnvironments"][environment], "pageId": self.plan["pageId"],
                     "sourceId": self.plan["sourceId"], "englishSourcePackageJsonSha256": app.digest(self.source),
                     "contentRevision": self.plan["contentRevision"], "contentHash": self.plan["contentHash"],
                     "candidateJsonSha256": app.candidate_identity(self.plan), "appVisible": True,
                     "reviewedProducts": app.review_scope(self.plan), "decision": "approved",
                     "reviewer": "Synthetic App reviewer", "reviewedAt": "2026-10-03T12:00:00Z"}
            self.plan["approvalReceipts"][environment] = self.write(environment + "-approval.json", value)

    def modify_reference(self, reference, change):
        value = json.loads((self.root / reference["path"]).read_text())
        change(value)
        reference.update(self.write(reference["path"], value))

    def rebind_audio(self, package):
        products = self.plan["products"]["ko"]
        products["audio"]["artifact"] = self.write("ko-audio.json", package)
        self.modify_reference(products["audio"]["review"], lambda value:
                              value.update(targetLanguageAudioPackageJsonSha256=app.digest(package)))
        self.freeze()

    def test_actual_source_arrays_audio_metadata_and_read_only_without_pdf(self):
        self.plan["products"]["ko"]["audio"]["artifact"] = self.write("ko-audio.json", dict(
            json.loads((self.root / "ko-audio.json").read_text())))
        package = json.loads((self.root / "ko-audio.json").read_text())
        package["track"]["sizeBytes"] = (self.root / "tone.wav").stat().st_size
        self.plan["products"]["ko"]["audio"]["artifact"] = self.write("ko-audio.json", package)
        audio_review = self.plan["products"]["ko"]["audio"]["review"]
        self.modify_reference(audio_review, lambda value: value.update(targetLanguageAudioPackageJsonSha256=app.digest(package)))
        self.client_proof(); self.approve(); self.write("plan.json", self.plan)
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = app.inspect(self.root / "plan.json")
        after = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(result["appProductsReady"])
        self.assertEqual(result["promotion"]["status"], "eligible_not_published")
        self.assertEqual(result["pdfAdHoc"]["status"], "not_requested")
        self.assertEqual(result["deviceAcceptance"], "not_run")
        self.assertEqual(result["venueAcceptance"], "not_run")
        self.assertEqual(result["legacyPdfScope"], "dual_pdf_unchanged")
        self.assertEqual(result["production"]["ios_prod"]["publication"], "not_run")

    def test_client_proof_and_both_approvals_are_required(self):
        self.approve()
        result = self.inspect()
        self.assertTrue(result["appProductsReady"])
        self.assertEqual(result["promotion"]["status"], "planned")
        self.assertIn("ko.client_capabilities_missing", result["promotion"]["blockers"])
        self.plan["approvalReceipts"] = {}
        self.client_proof(); self.approve()
        del self.plan["approvalReceipts"]["firebase_dev"]
        self.assertEqual(self.inspect()["promotion"]["status"], "planned")

    def test_missing_pending_failed_are_distinct_required_products(self):
        for status in ("missing", "pending", "failed"):
            with self.subTest(status=status):
                self.plan["products"]["ko"]["reflection"] = {"status": status, "reason": "Synthetic status"}
                self.freeze()
                result = self.inspect()
                self.assertFalse(result["appProductsReady"])
                self.assertIn("ko.reflection." + status, result["promotion"]["blockers"])

    def test_claimed_available_without_assets_or_review_is_rejected(self):
        self.plan["products"]["ko"]["reflection"] = {"status": "available"}
        self.freeze()
        with self.assertRaisesRegex(ValueError, "plan_invalid_schema"):
            self.inspect()

    def test_translation_missing_duplicate_and_reordered_source_coverage_rejected(self):
        products = self.plan["products"]["ko"]
        original = json.loads((self.root / products["translation"]["artifact"]["path"]).read_text())
        for mode in ("missing", "duplicate", "reordered"):
            with self.subTest(mode=mode):
                value = copy.deepcopy(original)
                group = value["groups"][0]
                if mode == "missing":
                    group["sourceUnitIds"] = group["sourceUnitIds"][:-1]
                    group["coverage"] = group["coverage"][:-1]
                elif mode == "duplicate":
                    duplicate = copy.deepcopy(group)
                    duplicate["translationGroupId"] = "extra-group"
                    value["groups"].append(duplicate)
                    value["humanReview"]["reviewedGroupIds"].append("extra-group")
                    value["modelReview"]["reviewedGroupIds"].append("extra-group")
                else:
                    group["sourceUnitIds"].reverse(); group["coverage"].reverse()
                app.existing_schema(value, "sermon-target-language-candidate-v2.schema.json")
                products["translation"]["artifact"] = self.write("ko-translation.json", value)
                self.freeze()
                with self.assertRaisesRegex(ValueError, "translation_not_reviewed_for_source"):
                    self.inspect()

    def test_measured_audio_rejects_duration_source_order_and_caption_time_changes(self):
        original = json.loads((self.root / "ko-audio.json").read_text())
        schedule_original = json.loads((self.root / "ko-schedule.json").read_text())
        captions_original = json.loads((self.root / "ko-captions.json").read_text())
        for mode in ("track_duration", "unit_duration", "source_ids", "caption_time", "bounds", "timing_kind"):
            with self.subTest(mode=mode):
                package, schedule, captions = copy.deepcopy(original), copy.deepcopy(schedule_original), copy.deepcopy(captions_original)
                if mode == "track_duration": schedule["trackDurationSeconds"] = 50
                if mode == "unit_duration": package["units"][0]["durationSeconds"] = 50
                if mode == "source_ids": schedule["entries"][0]["sourceUnitIds"] = ["wrong-unit"]
                if mode == "caption_time": captions["cues"][0]["start"] = 0.1
                if mode == "bounds":
                    schedule["entries"][0]["plannedEnd"] = 50
                    captions["cues"][0]["end"] = 50
                if mode == "timing_kind": schedule["timingKind"] = "guessed"
                package["schedule"] = self.write("ko-schedule.json", schedule)
                package["captions"] = self.write("ko-captions.json", captions)
                self.rebind_audio(package)
                with self.assertRaisesRegex(ValueError, "audio_.*(?:timing|schedule)_mismatch"):
                    self.inspect()

    def test_optional_caption_locale_must_not_contradict_audio_locale(self):
        original_package = json.loads((self.root / "ko-audio.json").read_text())
        original_captions = json.loads((self.root / "ko-captions.json").read_text())
        for field in ("targetLocale", "locale"):
            with self.subTest(field=field):
                package, captions = copy.deepcopy(original_package), copy.deepcopy(original_captions)
                captions[field] = "es"
                package["captions"] = self.write("ko-captions.json", captions)
                self.rebind_audio(package)
                with self.assertRaisesRegex(ValueError, "audio_captions_or_schedule_mismatch"):
                    self.inspect()

    def test_two_locales_are_explicit_and_unlisted_locale_is_rejected(self):
        self.make_locale("es")
        self.plan["locales"].append("es")
        self.client_proof(); self.approve()
        result = self.inspect()
        self.assertEqual(result["locales"], ["ko", "es"])
        self.assertEqual(result["promotion"]["status"], "eligible_not_published")
        self.plan["locales"] = ["ko"]
        with self.assertRaisesRegex(ValueError, "locale_plan_mismatch"):
            self.inspect()

    def test_separate_reviewed_spoken_candidate_can_bind_the_audio(self):
        products = self.plan["products"]["ko"]
        full = json.loads((self.root / "ko-translation.json").read_text())
        spoken = copy.deepcopy(full)
        text = spoken["groups"][0]["targetText"] + " 짧은 음성"
        spoken["groups"][0]["targetText"] = text
        spoken["groups"][0]["targetUtterances"] = [text]
        for coverage in spoken["groups"][0]["coverage"]:
            coverage["targetText"] = text
        products["audio"]["spokenCandidate"] = self.write("ko-spoken.json", spoken)
        receipt = json.loads((self.root / products["translation"]["review"]["path"]).read_text())
        receipt["candidateJsonSha256"] = app.digest(spoken)
        products["audio"]["spokenReview"] = self.write("ko-spoken-review.json", receipt)
        package = json.loads((self.root / "ko-audio.json").read_text())
        package["targetLanguageCandidateJsonSha256"] = app.digest(spoken)
        package["units"][0]["targetTextSha256"] = hashlib.sha256(text.encode()).hexdigest()
        captions = json.loads((self.root / "ko-captions.json").read_text())
        captions["cues"][0]["text"] = text
        package["captions"] = self.write("ko-captions.json", captions)
        self.modify_reference(products["audio"]["review"], lambda value:
                              value.update(targetLanguageCandidateJsonSha256=app.digest(spoken)))
        self.rebind_audio(package)
        self.client_proof(); self.approve()
        self.assertEqual(self.inspect()["promotion"]["status"], "eligible_not_published")

    def test_asset_and_human_review_tampering_is_rejected(self):
        reference = self.plan["products"]["ko"]["outline"]["artifact"]
        (self.root / reference["path"]).write_text("{}")
        with self.assertRaisesRegex(ValueError, "artifact_sha_mismatch"):
            self.inspect()

    def test_study_review_must_bind_product_locale_source_revision_and_items(self):
        reference = self.plan["products"]["ko"]["reflection"]["review"]
        for field, replacement in (("targetLocale", "es"), ("product", "outline"),
                ("contentRevision", "old"), ("englishSourcePackageJsonSha256", "0" * 64),
                ("artifactSha256", "0" * 64), ("decision", "rejected"), ("reviewedItemIds", ["wrong"])):
            with self.subTest(field=field):
                before = json.loads((self.root / reference["path"]).read_text())
                self.modify_reference(reference, lambda value: value.update({field: replacement}))
                self.freeze()
                with self.assertRaises(ValueError):
                    self.inspect()
                reference.update(self.write(reference["path"], before))

    def test_app_review_wrong_environment_version_hash_scope_and_reviewer_rejected(self):
        self.client_proof(); self.approve()
        reference = self.plan["approvalReceipts"]["ios_beta"]
        for field, replacement in (("environment", "firebase_dev"), ("candidateJsonSha256", "0" * 64),
                ("contentHash", "0" * 64), ("sourceId", "wrong"), ("reviewer", " "),
                ("reviewedAt", "not-time"), ("reviewedProducts", app.review_scope(self.plan)[:-1]),
                ("client", dict(self.plan["testEnvironments"]["ios_beta"], appVersion="old"))):
            with self.subTest(field=field):
                before = json.loads((self.root / reference["path"]).read_text())
                self.modify_reference(reference, lambda value: value.update({field: replacement}))
                with self.assertRaises(ValueError):
                    self.inspect()
                reference.update(self.write(reference["path"], before))

    def test_rejected_or_not_visible_app_review_never_eligible(self):
        self.client_proof(); self.approve()
        reference = self.plan["approvalReceipts"]["ios_beta"]
        self.modify_reference(reference, lambda value: value.update(decision="rejected"))
        self.assertEqual(self.inspect()["promotion"]["status"], "planned")
        self.modify_reference(reference, lambda value: value.update(decision="approved", appVisible=False))
        self.assertEqual(self.inspect()["promotion"]["status"], "planned")

    def test_changed_content_revision_invalidates_existing_approval(self):
        self.client_proof(); self.approve()
        self.plan["contentRevision"] = "new-revision"
        with self.assertRaisesRegex(ValueError, "study_product_binding_mismatch"):
            self.inspect()

    def test_client_proof_must_bind_new_study_schema_and_asset_hash(self):
        self.client_proof(); self.approve()
        reference = self.plan["clientCapabilities"]["ko"]["firebase_dev"]
        self.modify_reference(reference, lambda value: value["supportedProductSchemas"].update(reflection="old-protocol"))
        self.plan["approvalReceipts"] = {}
        with self.assertRaisesRegex(ValueError, "client_capability_mismatch"):
            self.inspect()

    def test_pdf_failure_missing_or_bad_bytes_does_not_block_app(self):
        self.client_proof(); self.approve()
        for record in ({"status": "failed", "reason": "Synthetic PDF job failed"},
                       {"status": "pending", "reason": "PDF not yet requested"},
                       {"status": "available", "artifact": {"path": "absent.pdf", "sha256": "0" * 64},
                        "review": {"path": "absent-review.json", "sha256": "0" * 64}}):
            self.plan["pdfAdHoc"] = record
            result = self.inspect()
            self.assertTrue(result["appProductsReady"])
            self.assertEqual(result["promotion"]["status"], "eligible_not_published")
            self.assertNotEqual(result["pdfAdHoc"]["status"], "available")

    def test_text_only_requires_explicit_unavailable_package_plan_and_both_clients(self):
        package = json.loads((self.root / "ko-audio.json").read_text())
        package.update(status="audio_unavailable", voice=None, units=[], track=None, captions=None, schedule=None)
        self.plan["products"]["ko"]["audio"] = {"status": "audio_unavailable", "reason": "Explicit text-only plan",
            "artifact": self.write("ko-unavailable.json", package)}
        self.freeze()
        with self.assertRaisesRegex(ValueError, "text_only_not_in_release_plan"):
            self.inspect()
        self.plan["allowTextOnlyLocales"] = ["ko"]
        with self.assertRaisesRegex(ValueError, "text_only_requires_both_clients"):
            self.inspect()
        self.client_proof(supports_text_only=False)
        with self.assertRaisesRegex(ValueError, "client_capability_mismatch"):
            self.inspect()
        self.client_proof(supports_text_only=True); self.approve()
        self.assertEqual(self.inspect()["promotion"]["status"], "eligible_not_published")

    def test_path_escape_symlink_and_extra_exec_fields_rejected(self):
        original = copy.deepcopy(self.plan["source"])
        for path in ("../source.json", "https://local.invalid/source.json", "/tmp/source.json"):
            self.plan["source"]["path"] = path
            with self.assertRaises(ValueError):
                self.inspect()
        self.plan["source"] = original
        (self.root / "source-link.json").symlink_to(self.root / "source.json")
        self.plan["source"]["path"] = "source-link.json"
        with self.assertRaisesRegex(ValueError, "symlink_artifact"):
            self.inspect()
        self.plan["source"] = original
        self.plan["exec"] = "never execute"
        with self.assertRaisesRegex(ValueError, "plan_invalid_schema"):
            self.inspect()

    def test_production_environment_failures_remain_separate_observations(self):
        self.client_proof(); self.approve()
        evidence = self.write("synthetic-failure.json", {"note": "Synthetic failure; no production execution"})
        observation = {"schemaVersion": "sermon-app-production-observation-v1", "environment": "firebase_prod",
                       "client": dict(self.plan["productionEnvironments"]["firebase_prod"]),
                       "candidateJsonSha256": app.candidate_identity(self.plan), "publication": "fail",
                       "deviceAcceptance": "not_run", "observer": "Synthetic observer",
                       "observedAt": "2026-10-03T13:00:00Z", "evidence": evidence}
        self.plan["productionRuns"]["firebase_prod"] = self.write("firebase-prod-failure.json", observation)
        result = self.inspect()
        self.assertEqual(result["production"]["ios_prod"]["publication"], "not_run")
        self.assertEqual(result["production"]["firebase_prod"]["publication"], "fail")
        self.assertEqual(result["promotion"]["status"], "eligible_not_published")
        observation["client"]["environmentId"] = "wrong-production"
        self.plan["productionRuns"]["firebase_prod"] = self.write("firebase-prod-failure.json", observation)
        result = self.inspect()
        self.assertEqual(result["production"]["firebase_prod"],
                         {"publication": "not_run", "deviceAcceptance": "not_run"})
        self.assertEqual(result["promotion"]["status"], "eligible_not_published")

    def test_invalid_optional_production_evidence_preserves_readiness_and_valid_sibling(self):
        self.client_proof(); self.approve()
        identity = app.candidate_identity(self.plan)
        evidence = self.write("production-evidence.json", {"note": "Synthetic observation"})
        valid = {"schemaVersion": "sermon-app-production-observation-v1", "environment": "ios_prod",
                 "client": dict(self.plan["productionEnvironments"]["ios_prod"]),
                 "candidateJsonSha256": identity, "publication": "fail", "deviceAcceptance": "not_run",
                 "observer": "Synthetic observer", "observedAt": "2026-10-03T13:00:00Z", "evidence": evidence}
        self.plan["productionRuns"]["ios_prod"] = self.write("valid-production.json", valid)
        other = dict(valid, environment="firebase_prod",
                     client=dict(self.plan["productionEnvironments"]["firebase_prod"]))
        malformed = self.root / "private-observation"
        malformed.write_text("private-canary invalid json")
        missing_evidence = dict(other, evidence={"path": "private-absent-evidence", "sha256": "0" * 64})
        cases = {
            "missing": {"path": "private-absent-observation", "sha256": "0" * 64},
            "stale_hash": dict(self.write("stale-production.json", other), sha256="0" * 64),
            "malformed_json": self.reference(malformed, is_json=False),
            "bad_schema": self.write("bad-production.json", {"private-canary": True}),
            "stale_candidate": self.write("old-production.json", dict(other, candidateJsonSha256="0" * 64)),
            "wrong_environment": self.write("wrong-production.json", valid),
            "missing_evidence": self.write("missing-evidence-production.json", missing_evidence),
        }
        for name, reference in cases.items():
            with self.subTest(name=name):
                self.plan["productionRuns"]["firebase_prod"] = reference
                result = self.inspect()
                self.assertEqual(result["candidateJsonSha256"], identity)
                self.assertEqual(result["promotion"]["status"], "eligible_not_published")
                self.assertEqual(result["production"]["ios_prod"], valid)
                self.assertEqual(result["production"]["firebase_prod"],
                                 {"publication": "not_run", "deviceAcceptance": "not_run"})
                self.assertNotIn("private", json.dumps(result["production"]))

    def test_cli_inspect_outputs_readiness_and_redacts_invalid_input(self):
        self.write("plan.json", self.plan)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(app.main(["inspect", "--plan", str(self.root / "plan.json")]), 0)
        self.assertEqual(json.loads(output.getvalue())["workflowScope"], "app_delivery_readiness")
        self.plan["private_payload"] = "private-canary"
        self.write("plan.json", self.plan)
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
            app.main(["inspect", "--plan", str(self.root / "plan.json")])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn("private-canary", error.getvalue())
        self.assertNotIn(str(self.root), error.getvalue())

    def test_cli_argument_errors_do_not_echo_secret_like_values(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
            app.main(["inspect", "--plan", "missing", "--api-key", "sk-private-sentinel"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn("sk-private-sentinel", error.getvalue())
        self.assertNotIn("--api-key", error.getvalue())
        self.assertIn("invalid_arguments", error.getvalue())

    def test_json_duplicate_fields_and_nonfinite_numbers_rejected_everywhere(self):
        for raw in ('{"private-key":1,"private-key":2}', '{"value":NaN}',
                    '{"value":Infinity}', '{"value":-Infinity}',
                    '{"value":1e999}', '{"value":-1e999}'):
            with self.subTest(raw=raw):
                path = self.root / "invalid.json"
                path.write_text(raw)
                with self.assertRaisesRegex(ValueError, "duplicate_json_field|nonfinite_json_number"):
                    app.read(path)
                reference = self.reference(path, is_json=False)
                with self.assertRaisesRegex(ValueError, "duplicate_json_field|nonfinite_json_number"):
                    app.artifact(self.root.resolve(), self.root.resolve(), reference)

    def test_bad_pdf_with_matching_hash_and_claimed_review_stays_failed(self):
        self.client_proof(); self.approve()
        path = self.root / "broken.pdf"
        path.write_bytes(b"%PDF-1.7\nThis is not a PDF document.")
        reference = self.reference(path, is_json=False)
        receipt = {"schemaVersion": "sermon-app-pdf-human-review-v1", "pageId": self.plan["pageId"],
                   "contentRevision": self.plan["contentRevision"], "contentHash": self.plan["contentHash"],
                   "artifactSha256": reference["sha256"], "decision": "approved",
                   "reviewer": "Synthetic PDF reviewer", "reviewedAt": "2026-10-03T12:00:00Z"}
        self.plan["pdfAdHoc"] = {"status": "available", "artifact": reference,
                                 "review": self.write("pdf-review.json", receipt)}
        result = self.inspect()
        self.assertEqual(result["promotion"]["status"], "eligible_not_published")
        self.assertEqual(result["pdfAdHoc"]["status"], "failed")

    def test_pdf_inspection_timeout_is_independent_and_redacted(self):
        self.client_proof(); self.approve()
        path = self.root / "private-timeout.pdf"
        path.write_bytes(b"%PDF-1.7\nSynthetic timeout fixture.")
        reference = self.reference(path, is_json=False)
        receipt = {"schemaVersion": "sermon-app-pdf-human-review-v1", "pageId": self.plan["pageId"],
                   "contentRevision": self.plan["contentRevision"], "contentHash": self.plan["contentHash"],
                   "artifactSha256": reference["sha256"], "decision": "approved",
                   "reviewer": "Synthetic PDF reviewer", "reviewedAt": "2026-10-03T12:00:00Z"}
        self.plan["pdfAdHoc"] = {"status": "available", "artifact": reference,
                                 "review": self.write("pdf-review.json", receipt)}
        original_run = app.subprocess.run
        def timeout_pdf(command, *args, **kwargs):
            if command[0] == "pdfinfo":
                raise subprocess.TimeoutExpired(command, 10)
            return original_run(command, *args, **kwargs)
        with patch.object(app.subprocess, "run", side_effect=timeout_pdf):
            result = self.inspect()
        self.assertTrue(result["appProductsReady"])
        self.assertEqual(result["promotion"]["status"], "eligible_not_published")
        self.assertEqual(result["pdfAdHoc"], {"status": "failed", "reason": "pdf_evidence_invalid_or_missing"})
        self.assertNotIn("private-timeout", json.dumps(result["pdfAdHoc"]))


if __name__ == "__main__":
    unittest.main()
