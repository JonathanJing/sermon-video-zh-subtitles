import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.experiments import decisions_l2_calibration as subject


ENGLISH = {
    "u1": "Jesus conquers over everything.",
    "u2": "Next week we will look at Revelation 4 and 5.",
    "u3": "You have an enemy who is a roaring lion.",
    "u4": "He wants to destroy you.",
}
TARGETS = {
    "ko": ["예수님은 모든 것을 이기십니다. 그는 승리하십니다.", "다음 주에는 요한계시록 4장과 5장을 보겠습니다.", "여러분에게는 으르렁거리는 사자 같은 원수가 있습니다.", "그는 여러분을 멸망시키려 합니다."],
    "es": ["Jesús vence sobre todo. Él es el vencedor.", "La próxima semana veremos Apocalipsis 4 y 5.", "Tienes un enemigo que es un león rugiente.", "Él quiere destruirte."],
    "zh-Hans": ["耶稣胜过一切。祂是得胜者。", "下周我们会看启示录4章和5章。", "你有一个仇敌，是吼叫的狮子。", "他想要毁灭你。"],
}


def manifest():
    return {"schemaVersion": "sermon-sentence-anchor-manifest-v2",
            "sourceUnits": [{"sourceUnitId": unit, "english": text} for unit, text in ENGLISH.items()]}


def candidate(locale):
    return {"schemaVersion": "sermon-target-language-candidate-v2", "targetLocale": locale, "groups": [
        {"translationGroupId": f"g{index}-{locale}", "sourceUnitIds": [unit], "targetText": text, "targetUtterances": [text]}
        for index, (unit, text) in enumerate(zip(ENGLISH, TARGETS[locale]))]}


def fake_transport(body):
    # Flags anything that differs from the approved text, so detection is perfect and clean is never flagged.
    parts = body["input"].split("\n\n")
    english = next(part for part in parts if part.startswith("English source:\n")).removeprefix("English source:\n")
    translation = next(part for part in parts if part.startswith("Translation:\n")).removeprefix("Translation:\n")
    index = list(ENGLISH.values()).index(english)
    clean = translation in {texts[index] for texts in TARGETS.values()}
    probability = 0.05 if clean else 0.9
    answers = [{"type": "predicate", "name": q["name"], "probability": probability} for q in body["questions"] if q["type"] == "predicate"]
    answers.append({"type": "score", "name": "fluency", "score": 2.6, "probabilities": [], "confidence": 0.7})
    answers.append({"type": "choice", "name": "issue_type", "choice": "none" if clean else "omission", "probabilities": [], "confidence": 0.8})
    return {"answers": answers, "usage": {"input_tokens": 500}, "_requestId": "req_test"}


class DecisionsCalibrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "manifest.json").write_text(json.dumps(manifest()), encoding="utf-8")
        for locale in TARGETS:
            (self.root / f"{locale}.json").write_text(json.dumps(candidate(locale), ensure_ascii=False), encoding="utf-8")

    def args(self, *extra):
        return ["--anchor-manifest", str(self.root / "manifest.json"),
                *sum((["--candidate", str(self.root / f"{locale}.json")] for locale in TARGETS), []),
                "--out", str(self.root / "out"), *extra]

    def test_dataset_pairs_each_clean_group_with_one_seeded_error(self):
        english = subject.english_by_unit(manifest())
        groups = {locale: subject.candidate_groups(candidate(locale), english) for locale in TARGETS}
        items = subject.build_dataset(groups, {"g0-ko": TARGETS["zh-Hans"][0]}, seed=1, max_items=100)
        clean = [item for item in items if item["kind"] == "clean"]
        seeded = [item for item in items if item["kind"] != "clean"]
        self.assertEqual(len(clean), 12)
        self.assertEqual(len(seeded), 12)
        for item in seeded:
            original = next(row for row in clean if row["groupId"] == item["groupId"])
            self.assertNotEqual(item["target"], original["target"])
        self.assertEqual(len({item["itemId"] for item in items}), len(items))
        self.assertEqual(items, subject.build_dataset(groups, {"g0-ko": TARGETS["zh-Hans"][0]}, seed=1, max_items=100))

    def test_request_includes_reference_only_when_present(self):
        item = {"english": "E", "locale": "ko", "target": "T", "reference": "参照"}
        body = subject.decision_request(item, None)
        self.assertEqual(body["model"], "gpt-6-luna")
        names = [question["name"] for question in body["questions"]]
        self.assertIn("meaning_vs_reference", names)
        self.assertIn("参照", body["input"])
        self.assertNotIn("meaning_vs_reference", [q["name"] for q in subject.decision_request({**item, "reference": None}, None)["questions"]])

    def test_dry_run_makes_no_network_call(self):
        with mock.patch.object(subject, "post_decision", side_effect=AssertionError("network")), \
                mock.patch("sys.stdout"):
            self.assertEqual(subject.main(self.args("--dry-run")), 0)
        plan = json.loads((self.root / "out" / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["items"], 24)
        self.assertGreater(plan["estimatedInputTokens"], 0)

    def test_run_reports_rates_and_resumes_from_cache(self):
        english = subject.english_by_unit(manifest())
        groups = {locale: subject.candidate_groups(candidate(locale), english) for locale in TARGETS}
        items = subject.build_dataset(groups, {}, seed=3, max_items=100)
        results = subject.run(items, self.root / "out", None, 2, transport=fake_transport)
        summary = subject.report(results, {"model": subject.MODEL})
        at_half = next(row for row in summary["thresholds"] if row["threshold"] == 0.5)
        self.assertEqual(at_half["detectionRate"], 1.0)
        self.assertEqual(at_half["cleanFlagRate"], 0.0)
        self.assertTrue(summary["inputTokensMeasured"])
        self.assertEqual(summary["inputTokens"], 500 * len(items))
        self.assertIn("## Clean items flagged, by locale", subject.markdown({**summary, "generatedAt": "t", "questionSetVersion": "v"}))
        self.assertEqual(subject.flagged_clean(items, results, 0.3), [])
        noisy = [{**row, "maxRisk": 0.6} if row["kind"] == "clean" else row for row in results]
        exported = subject.flagged_clean(items, noisy, 0.3)
        self.assertEqual(len(exported), sum(row["kind"] == "clean" for row in results))
        self.assertTrue(all(row["english"] and row["target"] for row in exported))
        again = subject.run(items, self.root / "out", None, 2, transport=mock.Mock(side_effect=AssertionError("cached")))
        self.assertEqual(again, results)

    def test_mixed_predicate_refusal_and_missing_probability_are_retained(self):
        risk_names = list(subject.RISK_PREDICATES)
        payload = {"answers": [
            {"type": "predicate", "name": risk_names[0], "probability": 0.8},
            {"type": "refusal", "name": risk_names[1]},
            {"type": "predicate", "name": risk_names[2]},
            {"type": "refusal", "name": "fluency"},
        ]}
        summary = subject.summarize_answers(payload)
        self.assertEqual(summary["risks"], {risk_names[0]: 0.8})
        self.assertEqual(summary["maxRisk"], 0.8)
        self.assertEqual(set(summary["refusals"]), {risk_names[1], "fluency"})
        self.assertIn(risk_names[2], summary["missingProbabilities"])
        self.assertIsNone(summary["fluency"])

    def test_unavailable_predicates_are_excluded_from_threshold_denominators(self):
        results = [
            {"kind": "clean", "maxRisk": 0.1, "unavailablePredicates": []},
            {"kind": "omission", "maxRisk": 0.9, "unavailablePredicates": []},
            {"kind": "clean", "maxRisk": 0.9, "unavailablePredicates": ["omission"]},
            {"kind": "omission", "maxRisk": None, "unavailablePredicates": ["omission"]},
        ]
        rates = subject.rates(results, 0.5)
        self.assertEqual(rates["evaluatedItems"], 2)
        self.assertEqual(rates["unscoredItems"], 2)
        self.assertEqual(rates["detectionRate"], 1.0)
        self.assertEqual(rates["cleanFlagRate"], 0.0)
        self.assertEqual(rates["byKind"], {"omission": {"detected": 1, "total": 1}})
        all_unscored = subject.rates(results[2:], 0.5)
        self.assertEqual(all_unscored["evaluatedItems"], 0)
        self.assertIsNone(all_unscored["detectionRate"])
        self.assertIsNone(all_unscored["cleanFlagRate"])
        self.assertEqual(all_unscored["byKind"], {})

    def test_partial_and_all_risk_refusals_are_unscored_and_resume_from_cache(self):
        items = [
            {"itemId": "partial", "groupId": "g0-ko", "locale": "ko", "kind": "clean",
             "english": ENGLISH["u1"], "target": TARGETS["ko"][0], "reference": TARGETS["zh-Hans"][0]},
            {"itemId": "all", "groupId": "g0-ko", "locale": "ko", "kind": "omission",
             "english": ENGLISH["u1"], "target": "incomplete", "reference": TARGETS["zh-Hans"][0]},
        ]

        def refusal_transport(body):
            payload = fake_transport(body)
            predicates = [answer for answer in payload["answers"] if answer["type"] == "predicate"]
            all_refused = "Translation:\nincomplete" in body["input"]
            for answer in predicates if all_refused else predicates[:1]:
                name = answer["name"]
                answer.clear()
                answer.update({"type": "refusal", "name": name})
            return payload

        transport = mock.Mock(side_effect=refusal_transport)
        results = subject.run(items, self.root / "out", None, 1, transport=transport)
        self.assertEqual(transport.call_count, 2)
        self.assertIsNotNone(results[0]["maxRisk"])
        self.assertIsNone(results[1]["maxRisk"])
        self.assertEqual(len(results[0]["unavailablePredicates"]), 1)
        requested = [q["name"] for q in subject.decision_request(items[1], None)["questions"] if q["type"] == "predicate"]
        self.assertEqual(set(results[1]["unavailablePredicates"]), set(requested))
        summary = subject.report(results, {"model": subject.MODEL})
        self.assertEqual(summary["refusedItems"], 2)
        self.assertEqual(summary["unscoredItems"], 2)
        self.assertEqual(summary["fullyScoredItems"], 0)
        for rates in summary["thresholds"]:
            self.assertEqual(rates["evaluatedItems"], 0)
            self.assertIsNone(rates["detectionRate"])
            self.assertIsNone(rates["cleanFlagRate"])
        cached_transport = mock.Mock(side_effect=AssertionError("refusal cache must not retry API"))
        again = subject.run(items, self.root / "out", None, 1, transport=cached_transport)
        self.assertEqual(again, results)
        cached_transport.assert_not_called()

    def test_missing_key_fails_before_any_request(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                subject.post_decision({"model": subject.MODEL})


if __name__ == "__main__":
    unittest.main()
