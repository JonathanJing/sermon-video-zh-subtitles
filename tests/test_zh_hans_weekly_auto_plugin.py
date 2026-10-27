"""The week-independent zh-Hans plugin, hashed with the shared machine-QC rules (10-25 week)."""
import copy
import json
from pathlib import Path
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from scripts.language_review_plugins import auto_qc_text_common, zh_hans_weekly_auto as plugin
from tongxing_production.review import release_basis as basis
from tongxing_production.text import candidate as producer
from tongxing_production.text import policy as subject
from tongxing_production.text import rule_preflight
from tongxing_production.source import sentence_interpretation as interpretation
# Module import only, so its tests are not collected a second time here.
from tests import test_target_language_policy_machine_qc as machine_qc


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = Path(plugin.__file__)
TARGET = ("记住你起初的爱心。", "回到那份爱里去。")


def zh_draft(source, anchor):
    """The checked-in zh-Hans template, references-only, pinned to the weekly auto plugin."""
    value = json.loads((ROOT / "config/target-language-policies/zh-Hans.json").read_text(encoding="utf-8"))
    value.pop("componentSha256")
    value["schemaVersion"] = subject.POLICY_V2
    value["sourceScope"] = {"englishSourcePackageJsonSha256": interpretation.json_sha256(source),
                            "anchorManifestSha256": interpretation.json_sha256(anchor),
                            "usedSeriesNames": [], "usedProperNames": [], "termApprovalEvidence": []}
    value["scripture"].update({"editionId": None, "citationUseStatus": "project_source_reviewed",
                               "quoteCheckPolicy": "references_only"})
    value["languageReview"].update({"pluginId": plugin.PLUGIN_ID,
                                    "pluginImplementationSha256": producer.plugin_implementation_sha256(PLUGIN),
                                    "implementationStatus": "verified",
                                    "requiredChecks": list(auto_qc_text_common.REQUIRED)})
    return value


class ZhHansWeeklyAutoHashTests(unittest.TestCase):
    def test_hash_covers_the_shared_rules_like_ko_and_es(self):
        builtins = PLUGIN.parent
        self.assertEqual(producer.plugin_implementation_sources(PLUGIN),
                         [PLUGIN.resolve(), builtins.resolve() / "common.py",
                          builtins.resolve() / "auto_qc_text_common.py"])

    def test_plugin_bytes_are_the_10_18_run_plugin(self):
        self.assertEqual(plugin.PLUGIN_ID, "zh-Hans-weekly-auto-v1")
        self.assertEqual(plugin.PLUGIN_VERSION, "2026-10-18-broadcast-v1")
        self.assertEqual(plugin.REQUIRED, auto_qc_text_common.REQUIRED)

    def test_plugin_is_not_a_machine_qc_default(self):
        # zh-Hans keeps naming its plugin; machine_qc binding stays ko/es only.
        with self.assertRaisesRegex(ValueError, "cover ko and es only"):
            subject.machine_qc_language_review("zh-Hans")


class ZhHansWeeklyAutoEndToEndTests(unittest.TestCase):
    """Freeze, rule preflight, plugin run and candidate admission for one zh-Hans source."""

    setUp = machine_qc.MachineQcCandidateEndToEndTests.setUp

    def test_candidate_is_admitted_with_the_auto_plugin(self):
        policy = subject.freeze_policy(zh_draft(self.source, self.anchor))
        self.assertTrue(subject.validate_policy(policy)["productionPolicyReady"])
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
        } for index, (unit, text) in enumerate(zip(self.anchor["sourceUnits"], TARGET), 1)]
        plan = [{"translationGroupId": g["translationGroupId"], "sourceUnitIds": g["sourceUnitIds"]}
                for g in evidence["groups"]]
        self.assertEqual(rule_preflight.preflight(request, policy, PLUGIN, plan)["pluginId"], plugin.PLUGIN_ID)
        receipt = producer.run_language_plugin(self.source, self.anchor, policy, request, evidence,
                                               PLUGIN, plugin_sha)
        candidate = producer.admit_evidence(self.source, self.anchor, policy, request, evidence,
                                            receipt, PLUGIN, plugin_sha)
        self.assertTrue(all(group["languageReview"]["pluginId"] == plugin.PLUGIN_ID
                            and all(check["status"] == "pass" for check in group["languageReview"]["checks"])
                            for group in candidate["groups"]))

    def test_traditional_characters_fail_the_script_check(self):
        policy = subject.freeze_policy(zh_draft(self.source, self.anchor))
        unit = self.anchor["sourceUnits"][0]
        checks = {c["checkId"]: c["status"] for c in plugin.review_group(
            policy, [unit], {"targetText": "記住你起初的愛心。", "targetUtterances": ["記住你起初的愛心。"],
                             "sourceUnitIds": [unit["sourceUnitId"]]})}
        self.assertEqual(checks["target_script"], "fail")


if __name__ == "__main__":
    unittest.main()
