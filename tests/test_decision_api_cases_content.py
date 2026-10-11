"""Offline protocol tests; synthetic responses are not quality/performance evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.experiments import decision_api_cases_content as c


def response(model, result):
    return {"id": "fixture-response", "model": model,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class ContentCasesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def english_fixture(self):
        source = self.root / "artifacts/fixture/source-frozen"
        aligned = source / "aligned.json"
        rows = [{"id": 0, "referenceChunkId": "block-00", "text": "God is good.", "start": 0,
                 "end": 2.9, "sentenceBoundarySource": "frozen_reference_punctuation",
                 "wordTimes": [{"text": w, "start": n, "end": n + .9}
                               for n, w in enumerate(("God", "is", "good."))]}]
        write(aligned, rows)
        manifest = c.identity.build_anchor_manifest(rows, source_path=aligned,
            unit_policy=c.identity.UNIT_POLICY_V2, max_unit_seconds=4.)
        write(source / "anchor.json", manifest)
        batch = c.english._sentence_inputs(manifest)
        payload = c.english._payload(batch, manifest_hash=c._sha(manifest),
            anchor_policy=manifest["policy"], model="gpt-6.1-sol", effort="high")
        request = {"schemaVersion": "sermon-sentence-model-run-v1", "stage": "english-source-judge-000", "payload": payload}
        result = {"schemaVersion": c.english.BATCH_SCHEMA, "sentences": [{
            "sourceSentenceId": batch[0]["sourceSentenceId"],
            "sourceUnitIds": [u["sourceUnitId"] for u in batch[0]["units"]],
            "verdict": "pass", "risk": "low", "checks": {k: "pass" for k in c.english.CHECKS},
            "evidence": "Developer fixture only.", "unresolvedIssues": []}]}
        raw = response("gpt-6.1-sol", result)
        path = source / "judge-requests/cache/english-source-judge-000-fixture.json"
        write(path, {"request": request, "requestSha256": c._sha(request),
                     "response": raw, "responseSha256": c._sha(raw)})
        return path, raw

    def translation_fixture(self):
        units = ["source.001"]
        draft = {"translationGroupId": "g1", "sourceUnitIds": units,
                 "targetUtterances": ["神是良善的。"],
                 "coverage": [{"sourceUnitId": units[0], "targetText": "神是良善的。"}]}
        evidence = {"translationGroupId": "g1", "sourceUnitIds": units,
                    "englishUnits": [{"sourceUnitId": units[0], "english": "God is good."}],
                    "context": {}, "targetLocale": "zh-Hans", "astraDraft": draft}
        policy = {"reviewer": {"model": "gpt-6.1-sol", "reasoningEffort": "medium",
                               "promptVersion": "developer-fixture-v1"},
                  "sourceScope": {"englishSourcePackageJsonSha256": "a" * 64,
                                  "anchorManifestSha256": "b" * 64}}
        prompt = {"instruction": "Correct any error in final targetUtterances and coverage. developer-fixture-v1",
                  "input": evidence}
        payload = c.translation.model_payload("reviewer", prompt, policy)
        result = {**copy.deepcopy(draft), "semanticReview": {"status": "pass",
            "checks": {name: "pass" for name in c.translation.SEMANTIC_CHECKS},
            "evidence": "Developer fixture only.", "uncertainty": [], "issues": []}}
        raw = response("gpt-6.1-sol", result)
        folder = self.root / "artifacts/fixture/zh-Hans/layer2"
        preview = folder / "group-0001-sol.policy-preview.json"
        write(preview, {"schemaVersion": "sermon-target-language-consumed-policy-v1",
                        "role": "reviewer", "payload": payload, "payloadSha256": c.policy_tools.canonical_sha256(payload),
                        "policy": policy, "policySha256": c.policy_tools.canonical_sha256(policy)})
        write(folder / "group-0001-sol.json", {"payloadSha256": c._sha(payload), "model": "gpt-6.1-sol",
                                               "requestId": raw["id"], "result": result})
        write(folder / "group-0001-sol.raw.json", {"payloadSha256": c._sha(payload), "response": raw})
        return preview, raw

    def test_missing_artifacts_report_without_invented_baseline(self):
        self.assertEqual(c.build_content_cases(self.root), [])
        self.assertEqual({r["stageId"] for r in c.get_content_case_report()["missing"]}, {"E01", "E02"})

    def test_exports_original_payload_and_shared_evidence_no_answers(self):
        ep, er = self.english_fixture()
        tp, tr = self.translation_fixture()
        cases = c.build_content_cases(self.root)
        self.assertEqual([v["stageId"] for v in cases], ["E01", "E02"])
        for case, raw in zip(cases, (er, tr)):
            self.assertEqual(case["sharedEvidence"], json.loads(case["b"]["input"]))
            self.assertEqual(case["sharedEvidence"], c._user(case["a"]["payload"]))
            self.assertEqual(case["evidenceSha256"], c._sha(case["sharedEvidence"]))
            self.assertIsNone(case["expected"])
            self.assertNotIn("semanticReview", case["sharedEvidence"].get("astraDraft", {}))
            for q in case["b"]["questions"]:
                self.assertEqual(set(q), {"name", "type", "instructions", "choices"})
                self.assertTrue(all(set(v) == {"value", "description"} for v in q["choices"]))
            self.assertIn("labels", c.normalize_content_a(case, raw))
        original = c._load(tp)
        self.assertEqual(cases[1]["a"]["payload"], original["payload"])
        self.assertEqual(cases[1]["provenance"]["policySha256"], original["policySha256"])

    def test_request_hash_tamper_rejected(self):
        path, _ = self.english_fixture()
        saved = c._load(path)
        saved["request"]["payload"]["reasoning_effort"] = "medium"
        write(path, saved)
        self.assertEqual(c.build_content_cases(self.root), [])

    def test_preview_hash_tamper_rejected(self):
        path, _ = self.translation_fixture()
        value = c._load(path)
        value["payload"]["messages"][0]["content"] += " Changed"
        write(path, value)
        self.assertEqual(c.build_content_cases(self.root), [])

    def test_corrected_final_pass_is_projected_as_repair_not_draft_pass(self):
        _, raw = self.translation_fixture()
        case = c.build_content_cases(self.root)[0]
        result = json.loads(raw["choices"][0]["message"]["content"])
        result["targetUtterances"] = ["神确实是良善的。"]
        result["coverage"][0]["targetText"] = "神确实是良善的。"
        normalized = c.normalize_content_a(case, response(raw["model"], result))
        self.assertEqual(normalized["labels"]["draft_disposition"], "repair_required")
        self.assertTrue(normalized["projectionNeedsGoldReview"])
        self.assertFalse(normalized["historicalAnswerIsGold"])

    def test_raw_terminal_shape_and_evidence_bindings_required(self):
        _, raw = self.english_fixture()
        case = c.build_content_cases(self.root)[0]
        broken = copy.deepcopy(raw)
        broken["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(ValueError):
            c.normalize_content_a(case, broken)
        broken = copy.deepcopy(case)
        broken["b"]["input"] = "{}"
        with self.assertRaisesRegex(ValueError, "shared_evidence_changed"):
            c.normalize_content_a(broken, raw)
        with self.assertRaises(ValueError):
            c.normalize_content_a(case, {"result": {}})

    def test_wrong_source_identity_rejected(self):
        _, raw = self.translation_fixture()
        case = c.build_content_cases(self.root)[0]
        result = json.loads(raw["choices"][0]["message"]["content"])
        result["sourceUnitIds"] = ["foreign"]
        with self.assertRaisesRegex(ValueError, "reviewer_changed_source_identity"):
            c.normalize_content_a(case, response(raw["model"], result))


if __name__ == "__main__":
    unittest.main()
