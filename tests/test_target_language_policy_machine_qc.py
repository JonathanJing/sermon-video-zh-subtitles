"""New ko/es policies bind the week-independent machine-QC plugins end to end."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import build_english_source_package as english_source
from scripts import machine_quality_release_basis as basis
from scripts import prepare_target_language_speech_job as handoff
from scripts import produce_target_language_candidate as producer
from scripts import run_machine_qc_clip_test as clip_test
from scripts import sermon_sentence_interpretation as interpretation
from scripts import target_language_policy as subject
from scripts import target_language_rule_preflight as rule_preflight
from scripts import target_text_auto_qc as text_qc
from scripts.language_review_plugins import auto_qc_text_common, es_weekly_auto, ko_weekly_auto
# Module imports only, so their tests are not collected a second time here.
from tests import auto_qc_fixtures as fixtures
from tests import test_build_english_source_package as source_fixtures
from tests import test_machine_quality_release_basis as release_fixture


ROOT = Path(__file__).resolve().parents[1]
ENGLISH = ("Remember your first love.", "Return to it.")
TARGET = {"ko": ("처음 사랑을 기억하십시오.", "그 사랑으로 돌아가십시오."),
          "es": ("Recuerden su primer amor.", "Vuelvan a él.")}
PLUGINS = {"ko": ko_weekly_auto, "es": es_weekly_auto}
IDENTITY = fixtures.SEMANTIC_IDENTITY


def draft(locale, source, anchor):
    """A new ko/es draft from the checked-in template, its plugin binding left open."""
    value = json.loads((ROOT / f"config/target-language-policies/{locale}.json").read_text(encoding="utf-8"))
    value.pop("componentSha256")
    value["schemaVersion"] = subject.POLICY_V2
    value["sourceScope"] = {"englishSourcePackageJsonSha256": interpretation.json_sha256(source),
                            "anchorManifestSha256": interpretation.json_sha256(anchor),
                            "usedSeriesNames": [], "usedProperNames": [], "termApprovalEvidence": []}
    value["scripture"].update({"editionId": None, "citationUseStatus": "project_source_reviewed",
                               "quoteCheckPolicy": "references_only"})
    for key in subject.LANGUAGE_REVIEW_BINDING:
        value["languageReview"].pop(key, None)
    return value


class Judge:
    """Fake back-translation transport: clean text recovers its English."""

    def __init__(self, locale):
        self.clean = dict(zip(TARGET[locale], ENGLISH))

    def __call__(self, role, system, user, schema):
        if role == "back_translator":
            return {"english": self.clean.get(user, "A different passage.")}
        pair = json.loads(user)
        return {"status": "pass" if pair["ORIGINAL"] == pair["BACK-TRANSLATION"] else "fail", "issues": []}


class LanguageReviewBindingTests(unittest.TestCase):
    def setUp(self):
        self.anchor = {"sourceUnits": [{"sourceUnitId": "u1", "english": ENGLISH[0]}]}
        self.source = {"anchors": {"artifact": {"jsonSha256": interpretation.json_sha256(self.anchor)}}}

    def test_new_ko_es_drafts_bind_the_machine_qc_plugin(self):
        for locale, plugin in PLUGINS.items():
            with self.subTest(locale=locale):
                frozen = subject.freeze_policy(draft(locale, self.source, self.anchor))
                review = frozen["languageReview"]
                self.assertEqual(review["pluginId"], plugin.PLUGIN_ID)
                self.assertEqual(review["requiredChecks"], auto_qc_text_common.REQUIRED)
                self.assertEqual(review["implementationStatus"], "verified")
                self.assertEqual(review["pluginImplementationSha256"],
                                 producer.plugin_implementation_sha256(Path(plugin.__file__)))
                identity = subject.validate_policy(frozen)
                self.assertTrue(identity["productionPolicyReady"], identity["unresolved"])

    def test_explicit_machine_qc_replaces_a_template_binding(self):
        template = draft("ko", self.source, self.anchor)
        template["languageReview"].update(pluginId="ko-sermon-v1", pluginImplementationSha256="a" * 64,
                                          implementationStatus="verified", requiredChecks=["natural_korean"])
        kept = subject.freeze_policy(template)
        self.assertEqual(kept["languageReview"]["pluginId"], "ko-sermon-v1")
        bound = subject.freeze_policy(template, language_review="machine_qc")
        self.assertEqual(bound["languageReview"]["pluginId"], ko_weekly_auto.PLUGIN_ID)
        self.assertEqual(template["languageReview"]["pluginId"], "ko-sermon-v1")  # The draft is not mutated.

    def test_zh_hans_keeps_its_plugin_and_partial_bindings_fail(self):
        zh = draft("zh-Hans", self.source, self.anchor)
        with self.assertRaisesRegex(ValueError, "zh-Hans keeps its own plugin"):
            subject.freeze_policy(zh)
        with self.assertRaisesRegex(ValueError, "zh-Hans keeps its own plugin"):
            subject.freeze_policy(zh, language_review="machine_qc")
        partial = draft("ko", self.source, self.anchor)
        partial["languageReview"]["requiredChecks"] = list(auto_qc_text_common.REQUIRED)
        with self.assertRaisesRegex(ValueError, "binding is incomplete"):
            subject.freeze_policy(partial)
        legacy = draft("es", self.source, self.anchor)
        legacy["schemaVersion"] = "sermon-target-language-policy-v1"
        legacy.pop("sourceScope")
        with self.assertRaisesRegex(ValueError, "v2, v3 or v4"):
            subject.freeze_policy(legacy)

    def test_existing_frozen_policies_are_never_rebound(self):
        for locale in ("zh-Hans", "ko", "es"):
            path = ROOT / f"config/target-language-policies/{locale}.json"
            before = path.read_bytes()
            policy = json.loads(before)
            identity = subject.validate_policy(policy)
            with self.assertRaisesRegex(ValueError, "without component hashes"):
                subject.freeze_policy(policy, language_review="machine_qc")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(subject.validate_policy(json.loads(before)), identity)
            self.assertNotIn("weekly-auto", policy["languageReview"]["pluginId"])


class MachineQcCandidateEndToEndTests(unittest.TestCase):
    """A candidate produced under the auto plugin passes text QC and the waiver."""

    def setUp(self):
        source = source_fixtures.EnglishSourcePackageTests()
        source.setUp()
        self.addCleanup(source.doCleanups)
        self.root = Path(source.root)
        segments = []
        for index, text in enumerate(ENGLISH):
            words = text.split()
            start = index * 3.0
            segments.append({"id": index, "referenceChunkId": "block-1", "text": text,
                             "start": start, "end": start + len(words) * .3,
                             "sentenceBoundarySource": "frozen_reference_punctuation",
                             "wordTimes": [{"text": word, "start": start + n * .3, "end": start + (n + 1) * .3}
                                           for n, word in enumerate(words)]})
        source_fixtures.write_json(source.segments_path, segments)
        self.anchor = interpretation.build_anchor_manifest(segments, source_path=source.segments_path,
                                                           unit_policy=interpretation.UNIT_POLICY_V2)
        source_fixtures.write_json(source.manifest_path, self.anchor)
        review_path = source.root / "synthetic-review.json"
        source_fixtures.write_json(review_path, {
            "schemaVersion": english_source.REVIEW_SCHEMA_VERSION,
            "alignedSegmentsSha256": english_source.file_sha256(source.segments_path),
            "anchorManifestJsonSha256": interpretation.json_sha256(self.anchor),
            "humanApproval": True, "reviewedBy": "Synthetic fixture reviewer",
            "reviewedAt": "2026-10-07T00:00:00Z",
            "reviewedSourceUnitIds": [u["sourceUnitId"] for u in self.anchor["sourceUnits"]],
            "checks": {name: "approved" for name in english_source.APPROVED_CHECKS}})
        self.source = source.build(review_path=review_path)

    def produce(self, locale):
        policy = subject.freeze_policy(draft(locale, self.source, self.anchor))
        plugin = Path(PLUGINS[locale].__file__)
        plugin_sha = policy["languageReview"]["pluginImplementationSha256"]
        request = producer.prepare_request(self.source, self.anchor, policy)
        evidence = copy.deepcopy(request)
        evidence["generation"] = {role: {"model": policy[role]["model"],
                                         "promptVersion": policy[role]["promptVersion"],
                                         "requestIds": [f"{role}-1", f"{role}-2"]}
                                  for role in ("translator", "reviewer")}
        evidence["groups"] = [{
            "translationGroupId": f"g{index}", "sourceUnitIds": [unit["sourceUnitId"]],
            "targetUtterances": [text], "coverage": [{"sourceUnitId": unit["sourceUnitId"], "targetText": text}],
            "semanticReview": {"status": "pass", "checks": dict.fromkeys(basis.SEMANTIC_CHECKS, "pass"),
                               "evidence": "Independent model review record for this group.",
                               "uncertainty": [], "issues": []},
            "translatorRequestId": f"translator-{index}", "reviewerRequestId": f"reviewer-{index}",
        } for index, (unit, text) in enumerate(zip(self.anchor["sourceUnits"], TARGET[locale]), 1)]
        plan = [{"translationGroupId": g["translationGroupId"], "sourceUnitIds": g["sourceUnitIds"]}
                for g in evidence["groups"]]
        # The rule preflight accepts the auto plugin's identity and frozen checks.
        rules = rule_preflight.preflight(request, policy, plugin, plan)
        self.assertEqual(rules["pluginId"], PLUGINS[locale].PLUGIN_ID)
        receipt = producer.run_language_plugin(self.source, self.anchor, policy, request, evidence,
                                               plugin, plugin_sha)
        candidate = producer.admit_evidence(self.source, self.anchor, policy, request, evidence,
                                            receipt, plugin, plugin_sha)
        return policy, candidate

    def test_candidate_passes_layer3_text_qc_and_waiver(self):
        for locale in PLUGINS:
            with self.subTest(locale=locale):
                policy, candidate = self.produce(locale)
                self.assertEqual(candidate["translationPolicySha256"], subject.canonical_sha256(policy))
                self.assertTrue(all(group["languageReview"]["pluginId"] == PLUGINS[locale].PLUGIN_ID
                                    and [c["checkId"] for c in group["languageReview"]["checks"]]
                                    == auto_qc_text_common.REQUIRED for group in candidate["groups"]))
                self.assertTrue(basis.machine_pending_candidate(candidate))
                handoff.validate_target_candidate(self.source, self.anchor, candidate,
                                                  require_human_approval=False)
                handoff.validate_policy_binding(candidate, policy)

                # The clip-test preflight finds the policy by the candidate's hash and raises nothing.
                run = self.root / f"run-{locale}"
                for name, value in (("source", self.source), ("anchor", self.anchor),
                                    ("policy", policy), ("candidate", candidate)):
                    clip_test.save(run / f"{name}.json", value)
                resolved = clip_test.resolve_locale(run, clip_test.index_run(run), locale, None)
                self.assertEqual(resolved["problems"], [])
                self.assertEqual(Path(resolved["paths"]["policy"]).name, "policy.json")

                qc = text_qc.screen(clip_test.qc_groups(candidate, self.anchor), locale, policy=policy,
                                    call=Judge(locale), identity=IDENTITY)
                self.assertEqual(qc["status"], "pass", qc["results"])
                self.assertEqual(qc["policyJsonSha256"], candidate["translationPolicySha256"])
                cal = release_fixture.calibration(locale, semanticIdentitySha256=qc["semanticIdentitySha256"])
                text_waiver = release_fixture.issue_text(self.source, self.anchor, candidate, qc, cal)
                self.assertFalse(text_waiver["humanApproval"])
                self.assertEqual(text_waiver["candidateJsonSha256"], basis.json_sha256(candidate))
                basis.validate_text_waiver(text_waiver, candidate=candidate)


if __name__ == "__main__":
    unittest.main()
