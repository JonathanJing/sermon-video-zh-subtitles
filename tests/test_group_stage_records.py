"""DEV-GRP-001: per-group stage records, input keys and the read-only plan.

The golden cases of docs/design/per-group-independent-pipeline.zh.md section 11: the
same inputs give the same key; any Layer 1 change makes everything stale; a plugin
change makes only P stale; one group's new text makes only that group stale from R
on; records never cross locales; and ``plan`` makes no call and writes nothing.
"""
import copy
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  (binds the package host)
from tongxing_production.orchestration import group_legacy as legacy
from tongxing_production.orchestration import group_plan
from tongxing_production.orchestration import group_records as records
from tongxing_production.text import models

ROOT = Path(__file__).resolve().parents[1]
RUN = "1" * 64
PLUGIN = "2" * 64
LANGUAGE_POLICY = "3" * 64
QC = "4" * 64
RENDERER = "5" * 64
ASR = "6" * 64
SEMANTIC = "7" * 64
ASR_SETTINGS_VALUE = {"protocol": "formal-back-asr-batch-v1", "model": "Qwen/Qwen3-ASR-0.6B", "batchSize": 4}
ASR_SETTINGS = records.json_sha256(ASR_SETTINGS_VALUE)
THRESHOLDS = {"asrMinSimilarity": 0.88, "maxSilenceRatio": 0.6}
UNITS = [("u1", "Hey, church, it is a joy to be with you."), ("u2", "Turn with me to Romans 8."),
         ("u3", "Verse 28 says this."), ("u4", "God works for the good."), ("u5", "Let us pray.")]
GROUPS = [("g1", ["u1"]), ("g2", ["u2", "u3"]), ("g3", ["u4"]), ("g4", ["u5"])]
TEXT = {"ko": {"g1": "성도 여러분, 안녕하세요.", "g2": "로마서 8장을 펴십시오. 28절입니다.",
               "g3": "하나님은 선을 이루십니다.", "g4": "기도합시다."},
        "es": {"g1": "Hola, iglesia.", "g2": "Abran Romanos 8. El versículo 28 dice.",
               "g3": "Dios obra para bien.", "g4": "Oremos."}}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


class Run:
    """A small whole-sermon run: two locales, four groups, products for every stage."""

    def __init__(self, root: Path):
        self.root = root
        self.anchor = {"sourceUnits": [{"sourceUnitId": u, "english": e} for u, e in UNITS],
                       "translationRequests": [{"translationGroupId": g, "sourceUnitIds": s} for g, s in GROUPS]}
        self.source = {"anchors": {"artifact": {"jsonSha256": records.json_sha256(self.anchor)}}, "id": "source"}
        self.policy = {"terminology": {"terms": ["Romans"]}, "scripture": {"quoteCheckPolicy": "references_only"},
                       "formatting": {"digits": "keep"},
                       "translator": {"model": "gpt-6.1-sol", "reasoningEffort": "high"},
                       "reviewer": {"model": "gpt-6.1-sol", "reasoningEffort": "medium"}}
        self.texts = copy.deepcopy(TEXT)
        # Products are bound to the source they were made from; a test may then change the source.
        self.produced_anchor = copy.deepcopy(self.anchor)
        self.produced_policy = copy.deepcopy(self.policy)
        self.produced_layer1 = self.layer1

    @property
    def layer1(self):
        return records.layer1_identity(records.json_sha256(self.source), records.json_sha256(self.anchor))

    def build(self):
        write(self.root / "source.json", self.source)
        write(self.root / "anchor.json", self.anchor)
        write(self.root / "policy.json", self.policy)
        locales = {}
        for locale in self.texts:
            locales[locale] = self._locale(locale)
        manifest = {"schemaVersion": group_plan.MANIFEST_SCHEMA, "source": "source.json", "anchor": "anchor.json",
                    "locales": locales}
        return write(self.root / "inputs.json", manifest)

    def _locale(self, locale):
        layer1 = self.produced_layer1
        base = self.root / locale
        groups = [{"translationGroupId": g, "sourceUnitIds": s, "targetUtterances": [self.texts[locale][g]]}
                  for g, s in GROUPS]
        write(base / "candidate.json", {"englishSourcePackageJsonSha256": layer1["englishSourcePackageJsonSha256"],
                                        "anchorManifestSha256": layer1["anchorManifestSha256"], "groups": groups})
        rounds = base / "round-001"
        anchor = self.produced_anchor
        contexts = legacy.group_contexts(anchor, group_plan.group_plan_rows(anchor))
        write(rounds / "request.json", {"targetLocale": locale, **layer1})
        for index, (group_id, unit_ids) in enumerate(GROUPS, 1):
            stem = f"group-{index:04d}"
            text = TEXT[locale][group_id]  # what Layer 2 produced; the candidate may later differ
            result = {"translationGroupId": group_id, "sourceUnitIds": unit_ids, "targetUtterances": [text]}
            prompt = {"translationGroupId": group_id, "sourceUnitIds": unit_ids,
                      "englishUnits": legacy.english_rows(anchor, unit_ids), "context": contexts[group_id],
                      "targetLocale": locale, "terminology": self.policy["terminology"],
                      "scripture": self.policy["scripture"], "formatting": self.policy["formatting"]}
            for role, suffix, settings, extra in (
                    ("translator", "astra", self.policy["translator"], {}),
                    ("reviewer", "sol", self.policy["reviewer"], {"astraDraft": result})):
                payload = {"model": settings["model"], "reasoning_effort": settings["reasoningEffort"],
                           "messages": [{"role": "system", "content": f"{role} instruction"},
                                        {"role": "user", "content": json.dumps({**prompt, **extra}, ensure_ascii=False)}]}
                reply = (dict(result, semanticReview={"status": "pass", "uncertainty": [], "issues": [],
                                                      "checks": {"completeMeaning": "pass", "noAddedMeaning": "pass"}})
                         if role == "reviewer" else result)
                write(rounds / f"{stem}-{suffix}.policy-preview.json",
                      {"role": role, "payload": payload, "payloadSha256": records.json_sha256(payload),
                       "policy": self.produced_policy, "policySha256": records.json_sha256(self.produced_policy)})
                write(rounds / f"{stem}-{suffix}.json", {"payloadSha256": sha(f"{locale}{group_id}{role}route"),
                                                          "requestId": f"req-{locale}-{group_id}-{role}",
                                                          "model": settings["model"], "result": reply})
            def file_sha(name):
                return hashlib.sha256((rounds / f"{stem}-{name}").read_bytes()).hexdigest()
            write(rounds / f"{stem}-payload-cache-success.json", {
                "runnerImplementationSha256": RUN, "translationGroupId": group_id, "sourceUnitIds": unit_ids,
                "roles": {role: {"cacheSha256": file_sha(f"{suffix}.json"),
                                 "previewSha256": file_sha(f"{suffix}.policy-preview.json")}
                          for role, suffix in (("translator", "astra"), ("reviewer", "sol"))}})
        # Every product below is what the run produced (TEXT); only the candidate may move on.
        write(base / "language-review.json", {
            "schemaVersion": "sermon-target-language-plugin-receipt-v1", **layer1, "targetLocale": locale,
            "languageReviewPolicySha256": LANGUAGE_POLICY, "pluginId": f"{locale}-test", "pluginImplementationSha256": PLUGIN,
            "groupReviews": [{"translationGroupId": g, "sourceUnitIds": s, "targetTextSha256": sha(TEXT[locale][g]),
                              "status": "pass", "checks": [{"checkId": "numbers", "status": "pass", "evidence": "ok"}]}
                             for g, s in GROUPS]})
        write(base / "text-qc.json", {
            "schemaVersion": "sermon-target-text-auto-qc-v1", "locale": locale, "implementationSha256": QC,
            "semanticIdentity": {"model": "gpt-6.1-sol", "settings": {"qcContext": {
                "englishSourcePackageJsonSha256": layer1["englishSourcePackageJsonSha256"],
                "anchorManifestJsonSha256": layer1["anchorManifestSha256"]}}},
            "semanticIdentitySha256": SEMANTIC, "repairLedger": {"priorFailedAttempts": {}},
            "results": [{"groupId": g, "sourceUnitIds": s, "status": "pass", "mode": "full", "problems": [],
                         "nextAction": "keep", "failedAttempts": 0, "targetTextSha256": sha(TEXT[locale][g]),
                         "englishSha256": legacy.qc_english_sha256(legacy.english_rows(anchor, s)),
                         "backTranslation": {"requestSha256s": [sha(f"bt{locale}{g}")]}} for g, s in GROUPS]})
        job = base / "speech-job"
        for index, (group_id, unit_ids) in enumerate(GROUPS):
            audio = sha(f"wav{locale}{group_id}")
            write(job / "receipts" / f"unit-{index:04d}.intent.json", {
                "schemaVersion": "sermon-formal-target-speech-render-v2", "unitIndex": index,
                "jobJsonSha256": "a" * 64, "sourceJsonSha256": layer1["englishSourcePackageJsonSha256"],
                "anchorJsonSha256": layer1["anchorManifestSha256"], "targetLocale": locale, "groupId": group_id,
                "sourceUnitIds": unit_ids, "textSha256": sha(TEXT[locale][group_id]), "rendererSha256": RENDERER,
                "speakerId": "speaker", "seed": 43, "temperature": 0.7, "batchWindowStart": 0,
                "batchWindowUnitIndices": [0, 1, 2, 3]})
            wav = job / "languages" / locale / "audio" / f"unit-{index:04d}.wav"
            wav.parent.mkdir(parents=True, exist_ok=True)
            wav.write_bytes(f"wav{locale}{group_id}".encode("utf-8"))  # sha() of these bytes is ``audio``
            write(job / "receipts" / f"unit-{index:04d}.json", {
                "targetLocale": locale, "jobJsonSha256": "a" * 64, "unitIndex": index,
                "translationGroupId": group_id, "sourceUnitIds": unit_ids,
                "targetTextSha256": sha(TEXT[locale][group_id]), "audioRelativePath": wav.relative_to(job).as_posix(),
                "audioSha256": audio, "fullDecode": "pass"})
            write(job / "asr-unit-cache-c1" / f"unit-{index:04d}.json", {
                "identity": {"audioSha256": audio, "targetTextSha256": sha(TEXT[locale][group_id]),
                             "implementationSha256": ASR}, "recognizedSha256": sha("recognized")})
        write(job / "asr-screening.json", {
            "schemaVersion": "sermon-target-language-audio-screening-v2", "targetLocale": locale,
            "targetLanguageSpeechJobJsonSha256": "a" * 64, "asrSettingsSha256": ASR_SETTINGS,
            "results": [{"textGroupId": g, "status": "pass", "similarity": 1.0,
                         "audioSha256": sha(f"wav{locale}{g}"), "targetTextSha256": sha(TEXT[locale][g])}
                        for g, _ in GROUPS]})
        write(base / "audio-qc.json", {
            "schemaVersion": "sermon-target-audio-auto-qc-v1", "locale": locale, "implementationSha256": QC,
            "durationNormalization": {"speechJobJsonSha256": "a" * 64}, "thresholds": THRESHOLDS, "repairLedger": {"priorFailedAttempts": {}},
            "results": [{"groupId": g, "sourceUnitIds": s, "audioSha256": sha(f"wav{locale}{g}"),
                         "textSha256": sha(TEXT[locale][g]), "sourceSeconds": 2.0, "status": "pass",
                         "issues": []} for g, s in GROUPS]})
        write(base / "asr-settings.json", ASR_SETTINGS_VALUE)
        return {"candidate": f"{locale}/candidate.json", "policy": "policy.json", "plugin": "plugin.py",
                "asrSettings": f"{locale}/asr-settings.json",
                "languageReview": f"{locale}/language-review.json", "layer2Rounds": [f"{locale}/round-001"],
                "textQcReceipt": f"{locale}/text-qc.json", "speechJob": f"{locale}/speech-job",
                "asrScreening": f"{locale}/speech-job/asr-screening.json", "audioQcReceipt": f"{locale}/audio-qc.json"}


def identities(**changes):
    value = {"runnerImplementationSha256": RUN, "machineQcImplementationSha256": QC,
             "rendererSoundIdentitySha256": RENDERER, "asrImplementationSha256": ASR,
             "audioQcThresholdsSha256": records.json_sha256(THRESHOLDS),
             "locales": {locale: {"pluginImplementationSha256": PLUGIN, "languageReviewPolicySha256": LANGUAGE_POLICY,
                                  "asrSettingsSha256": ASR_SETTINGS} for locale in TEXT}}
    for key, item in changes.items():
        if key == "plugin":
            value["locales"]["ko"]["pluginImplementationSha256"] = item
        else:
            value[key] = item
    return value


def statuses(report, locale, group_id):
    row = next(row for row in report["locales"][locale]["groups"] if row["translationGroupId"] == group_id)
    return {stage: value["status"] for stage, value in row["stages"].items()}


ALL_FRESH = {"T": "fresh", "R": "fresh", "P": "fresh", "Q": "fresh", "C": "not_applicable",
             "S": "fresh", "A": "fresh", "U": "fresh"}


class InputKeyTests(unittest.TestCase):
    def setUp(self):
        self.layer1 = records.layer1_identity("a" * 64, "b" * 64)
        self.inputs = {"textSha256": "c" * 64, "synthesisIdentitySha256": "d" * 64}

    def key(self, **changes):
        arguments = {"stage": "S", "layer1": self.layer1, "target_locale": "ko", "translation_group_id": "g1",
                     "inputs": self.inputs, "stage_implementation_sha256": "e" * 64} | changes
        return records.input_key(**arguments)

    def test_same_inputs_give_the_same_key_and_any_change_another(self):
        self.assertEqual(self.key(), self.key(inputs=dict(reversed(list(self.inputs.items())))))
        variants = [self.key(target_locale="es"), self.key(translation_group_id="g2"),
                    self.key(stage_implementation_sha256="f" * 64),
                    self.key(layer1=records.layer1_identity("a" * 64, "0" * 64)),
                    self.key(inputs=dict(self.inputs, textSha256="0" * 64))]
        self.assertEqual(len({self.key(), *variants}), 6)

    def test_every_stage_names_its_inputs_and_rejects_others(self):
        self.assertEqual(set(records.STAGE_INPUTS), set(records.STAGES))
        with self.assertRaisesRegex(ValueError, "stage_inputs_mismatch"):
            self.key(inputs={"textSha256": "c" * 64})
        with self.assertRaisesRegex(ValueError, "stage_inputs_mismatch"):
            self.key(inputs=dict(self.inputs, unitIndex="0" * 64))
        with self.assertRaisesRegex(ValueError, "stage_input_not_sha256"):
            self.key(inputs=dict(self.inputs, textSha256="short"))

    def test_records_are_never_release_or_approval_and_keys_cannot_be_edited(self):
        record = records.make_record("S", self.layer1, "ko", "g1", ["u1"], self.inputs, "e" * 64,
                                     {"audioSha256": "9" * 64}, "pass")
        self.assertFalse(record["releaseEligible"])
        self.assertFalse(record["humanApproval"])
        for field, value in (("releaseEligible", True), ("humanApproval", True), ("inputKey", "0" * 64),
                             ("inputs", dict(self.inputs, textSha256="0" * 64))):
            with self.subTest(field=field), self.assertRaises(ValueError):
                records.validate_record(dict(record, **{field: value}))
        for verdict in ({"status": "pass", "codes": ["x"]}, {"status": "fail", "codes": [3]}):
            with self.subTest(verdict=verdict), self.assertRaisesRegex(ValueError, "invalid_record_verdict"):
                records.validate_record(dict(record, verdict=verdict))
        for bad in ([], {"audioSha256": "short"}):
            with self.subTest(outputs=bad), self.assertRaisesRegex(ValueError, "invalid_record_outputs"):
                records.validate_record(dict(record, outputs=bad))
        for missing in ({}, {"audioSha256": None}):
            with self.subTest(outputs=missing), self.assertRaisesRegex(ValueError, "record_missing_required_output"):
                records.validate_record(dict(record, outputs=missing))
        failed = records.make_record("S", self.layer1, "ko", "g1", ["u1"], self.inputs, "e" * 64, {}, "fail",
                                     codes=["full_decode_failed"])
        self.assertEqual(failed["outputs"], {})  # a failure need not name bytes
        with self.assertRaisesRegex(ValueError, "codes_only_on_fail_or_stop"):
            records.make_record("S", self.layer1, "ko", "g1", ["u1"], self.inputs, "e" * 64, {}, "pass",
                                codes=["x"])

    def test_store_leaves_no_partial_record_when_a_write_fails(self):
        record = records.make_record("S", self.layer1, "ko", "g1", ["u1"], self.inputs, "e" * 64,
                                     {"audioSha256": "9" * 64}, "pass")
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            target = store.path("ko", "g1", "S", record["inputKey"])
            with patch.object(records.os, "fsync", side_effect=OSError("disk full")), self.assertRaises(OSError):
                store.put(record)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])
            self.assertEqual(store.put(record), target)  # a retry succeeds
            self.assertEqual(store.records("ko", "g1", "S"), [record])

    def test_store_is_append_only_and_never_serves_another_locale(self):
        record = records.make_record("S", self.layer1, "ko", "g1", ["u1"], self.inputs, "e" * 64,
                                     {"audioSha256": "9" * 64}, "pass")
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            path = store.put(record)
            self.assertEqual(store.put(copy.deepcopy(record)), path)
            path.write_text(path.read_text().replace("9" * 64, "8" * 64))
            with self.assertRaisesRegex(ValueError, "already_written_with_other_bytes"):
                store.put(record)
            path.unlink()
            store.put(record)
            self.assertEqual(store.records("ko", "g1", "S"), [record])
            self.assertEqual(store.records("es", "g1", "S"), [])
            # A ko record copied under es is refused, never served as es evidence.
            target = Path(directory) / "es" / "g1" / "S" / path.name
            target.parent.mkdir(parents=True)
            target.write_bytes(path.read_bytes())
            with self.assertRaisesRegex(ValueError, "record_filed_under_other_identity"):
                store.records("es", "g1", "S")

    def test_record_schema_matches_the_python_contract(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "schemas/sermon-group-stage-record-v1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        record = records.make_record("S", self.layer1, "ko", "g1", ["u1"], self.inputs, "e" * 64,
                                     {"audioSha256": "9" * 64}, "pass")
        Draft202012Validator(schema).validate(record)
        self.assertEqual(set(schema["required"]), set(record))
        self.assertEqual(schema["properties"]["stage"]["enum"], list(records.STAGES))


class LegacyReaderTests(unittest.TestCase):
    def test_group_boundaries_and_context_match_the_layer2_runner(self):
        run = Run(Path("unused"))
        request = {"sourceUnits": [{"sourceUnitId": u["sourceUnitId"], "english": u["english"]}
                                   for u in run.anchor["sourceUnits"]]}
        plan_rows = models.group_plan(request, run.anchor)
        self.assertEqual(group_plan.group_plan_rows(run.anchor), plan_rows)
        contexts = legacy.group_contexts(run.anchor, plan_rows)
        for index, row in enumerate(plan_rows):
            self.assertEqual(contexts[row["translationGroupId"]], models.surrounding_context(request, plan_rows, index))
        no_requests = {"sourceUnits": run.anchor["sourceUnits"]}
        self.assertEqual(group_plan.group_plan_rows(no_requests), models.group_plan(request, no_requests))

    def test_wrapped_utterances_are_read_like_the_runner(self):
        wrapped = {"sourceUnitIds": ["u1"], "targetUtterances": [{"sourceUnitIds": ["u1"], "targetText": "안녕"}]}
        self.assertEqual(legacy.result_utterances(wrapped), ["안녕"])
        self.assertIsNone(legacy.result_utterances({"sourceUnitIds": ["u1"], "targetUtterances": [{"x": 1}]}))

    def test_synthesis_identity_ignores_assembly_and_batch_fields(self):
        intent = {"seed": 43, "speakerId": "s", "unitIndex": 1, "jobJsonSha256": "a" * 64,
                  "batchWindowUnitIndices": [0, 1], "candidateJsonSha256": "b" * 64}
        moved = dict(intent, unitIndex=9, jobJsonSha256="c" * 64, batchWindowUnitIndices=[8, 9],
                     candidateJsonSha256="d" * 64)
        self.assertEqual(legacy.synthesis_identity_sha256(intent), legacy.synthesis_identity_sha256(moved))
        self.assertNotEqual(legacy.synthesis_identity_sha256(intent),
                            legacy.synthesis_identity_sha256(dict(intent, seed=44)))

    def test_an_unreadable_translator_cache_gives_no_translation_record(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(Path(directory))
            run.build()
            astra = run.root / "ko/round-001/group-0002-astra.json"
            value = json.loads(astra.read_text())
            value["result"]["targetUtterances"] = [{"unexpected": 1}]
            astra.write_text(json.dumps(value))
            report = group_plan.plan(json.loads((run.root / "inputs.json").read_text()), run.root, identities())
            self.assertEqual(statuses(report, "ko", "g2")["T"], "missing")
            self.assertEqual(statuses(report, "ko", "g2")["R"], "missing")

    def test_missing_runner_identity_is_reported_not_borrowed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Run(Path(directory))
            run.build()
            (run.root / "ko/round-001/group-0001-payload-cache-success.json").unlink()
            report = group_plan.plan(json.loads((run.root / "inputs.json").read_text()), run.root, identities())
            translator = report["locales"]["ko"]["groups"][0]["stages"]["T"]
            self.assertEqual(translator["status"], "fresh")
            self.assertIn("stageImplementation", translator["notCompared"])
            self.assertIn("stageImplementation", report["locales"]["ko"]["groups"][1]["stages"]["T"]["compared"])
            # A round that records its runner identity makes it comparable again.
            write(run.root / "ko/round-001/runner-identity.json", {
                "schemaVersion": "sermon-layer2-round-runner-identity-v1", "runnerImplementationSha256": "9" * 64,
                "payloadCacheImplementationSha256": None, "runIdentitySha256": "a" * 64})
            report = group_plan.plan(json.loads((run.root / "inputs.json").read_text()), run.root, identities())
            translator = report["locales"]["ko"]["groups"][0]["stages"]["T"]
            self.assertEqual((translator["status"], translator["reasons"]), ("stale", ["stage_implementation_changed"]))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.run = Run(Path(self.directory.name))

    def plan(self, current=None, **options):
        manifest = json.loads(self.run.build().read_text())
        return group_plan.plan(manifest, self.run.root, current or identities(), **options)

    def test_an_unchanged_run_is_fresh_everywhere_without_any_call_or_write(self):
        self.run.build()
        before = sorted((p.relative_to(self.run.root), p.read_bytes()) for p in self.run.root.rglob("*") if p.is_file())
        with patch.object(models, "_model_call", side_effect=AssertionError("no model call")):
            report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root, identities())
        after = sorted((p.relative_to(self.run.root), p.read_bytes()) for p in self.run.root.rglob("*") if p.is_file())
        self.assertEqual(before, after)
        self.assertEqual((report["dispatched"], report["modelCalls"], report["releaseEligible"],
                          report["humanApproval"]), (False, 0, False, False))
        for locale in TEXT:
            for group_id, _ in GROUPS:
                self.assertEqual(statuses(report, locale, group_id), ALL_FRESH)
            self.assertEqual(report["locales"][locale]["paidStageRedoCount"], 0)

    def test_any_layer1_change_makes_every_group_and_locale_stale(self):
        self.run.anchor["sourceUnits"][4]["english"] = "Let us pray together."
        self.run.source["anchors"]["artifact"]["jsonSha256"] = records.json_sha256(self.run.anchor)
        report = self.plan()
        for locale in TEXT:
            for group_id, _ in GROUPS:
                values = report["locales"][locale]["groups"]
                row = next(r for r in values if r["translationGroupId"] == group_id)
                for stage in ("T", "R", "P", "Q", "S", "A", "U"):
                    self.assertEqual(row["stages"][stage]["status"], "stale", (locale, group_id, stage))
                    self.assertIn("layer1_identity_changed", row["stages"][stage]["reasons"])

    def test_a_plugin_change_makes_only_p_stale(self):
        report = self.plan(identities(plugin="9" * 64))
        for group_id, _ in GROUPS:
            self.assertEqual(statuses(report, "ko", group_id), dict(ALL_FRESH, P="stale"))
            self.assertEqual(statuses(report, "es", group_id), ALL_FRESH)
        self.assertEqual(report["locales"]["ko"]["paidStageRedoCount"], 0)

    def test_one_group_with_new_text_is_stale_from_r_on_and_no_other_group_moves(self):
        self.run.texts["ko"]["g3"] = "하나님은 모든 것을 합력하여 선을 이루십니다."
        report = self.plan()
        changed = statuses(report, "ko", "g3")
        self.assertEqual(changed["T"], "fresh")
        for stage in ("R", "P", "Q", "S", "A", "U"):
            self.assertEqual(changed[stage], "stale", stage)
        for group_id in ("g1", "g2", "g4"):
            self.assertEqual(statuses(report, "ko", group_id), ALL_FRESH)
        for group_id, _ in GROUPS:
            self.assertEqual(statuses(report, "es", group_id), ALL_FRESH)

    def test_operator_named_groups_redo_from_t_and_only_those_groups(self):
        report = self.plan(directives={"ko": ["g2"]})
        self.assertEqual(statuses(report, "ko", "g2"),
                         {"T": "stale", "R": "stale", "P": "stale", "Q": "stale", "C": "not_applicable",
                          "S": "stale", "A": "stale", "U": "stale"})
        self.assertIn("operator_directive", report["locales"]["ko"]["groups"][1]["stages"]["T"]["reasons"])
        for group_id in ("g1", "g3", "g4"):
            self.assertEqual(statuses(report, "ko", group_id), ALL_FRESH)
        self.assertEqual(report["locales"]["ko"]["directiveGroupIds"], ["g2"])
        with self.assertRaisesRegex(ValueError, "directive_names_unknown_group"):
            self.plan(directives={"ko": ["g9"]})

    def test_voice_and_qc_changes_rerun_only_their_stages(self):
        voice = self.plan(identities(rendererSoundIdentitySha256="9" * 64))
        self.assertEqual(statuses(voice, "ko", "g1"), dict(ALL_FRESH, S="stale", A="stale", U="stale"))
        qc = self.plan(identities(machineQcImplementationSha256="9" * 64))
        self.assertEqual(statuses(qc, "ko", "g1"), dict(ALL_FRESH, Q="stale", U="stale"))
        asr = self.plan(identities(asrImplementationSha256="9" * 64))
        self.assertEqual(statuses(asr, "es", "g4"), dict(ALL_FRESH, A="stale", U="stale"))

    def test_a_recorded_failure_stays_failed_and_missing_products_are_missing(self):
        receipt_path = self.run.root / "ko/text-qc.json"
        self.run.build()
        receipt = json.loads(receipt_path.read_text())
        receipt["results"][0].update(status="fail", problems=["english_leak"], nextAction="repair")
        receipt_path.write_text(json.dumps(receipt))
        manifest = json.loads((self.run.root / "inputs.json").read_text())
        del manifest["locales"]["es"]["speechJob"]
        report = group_plan.plan(manifest, self.run.root, identities())
        self.assertEqual(report["locales"]["ko"]["groups"][0]["stages"]["Q"]["status"], "failed")
        self.assertEqual(report["locales"]["ko"]["groups"][0]["stages"]["Q"]["codes"], ["english_leak"])
        es = statuses(report, "es", "g1")
        self.assertEqual((es["S"], es["A"], es["U"]), ("missing", "missing", "missing"))

    def test_store_records_for_another_locale_are_never_used(self):
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            layer1 = self.run.layer1
            store.put(records.make_record("S", layer1, "ko", "g1", ["u1"],
                                          {"textSha256": "0" * 64, "synthesisIdentitySha256": "0" * 64},
                                          RENDERER, {"audioSha256": "0" * 64}, "pass"))
            manifest = json.loads(self.run.build().read_text())
            del manifest["locales"]["es"]["speechJob"]
            report = group_plan.plan(manifest, self.run.root, identities(), store=store)
            self.assertEqual(statuses(report, "es", "g1")["S"], "missing")
            self.assertEqual(statuses(report, "ko", "g1")["S"], "fresh")

    def test_any_model_facing_policy_change_makes_t_and_r_stale_but_plugin_fields_do_not(self):
        self.run.policy["languageReview"] = {"registerRules": ["Use a natural register."],
                                             "pluginImplementationSha256": "1" * 64}
        self.run.produced_policy = copy.deepcopy(self.run.policy)
        self.assertEqual(statuses(self.plan(), "ko", "g1"), ALL_FRESH)
        plugin_only = copy.deepcopy(self.run.policy)
        plugin_only["languageReview"]["pluginImplementationSha256"] = "2" * 64
        plugin_only["componentSha256"] = {"x": "3" * 64}
        self.run.policy = plugin_only
        self.assertEqual(statuses(self.plan(), "ko", "g1"), ALL_FRESH)
        for change in ({"languageReview": dict(plugin_only["languageReview"], registerRules=["Formal."])},
                       {"translator": dict(plugin_only["translator"], promptVersion="v2")}):
            self.run.policy = dict(plugin_only, **change)
            report = self.plan()
            self.assertEqual(statuses(report, "es", "g2")["T"], "stale", change)
            self.assertIn("input_changed:modelFacingPolicySha256",
                          report["locales"]["es"]["groups"][1]["stages"]["T"]["reasons"])

    def test_asr_and_audio_qc_verdicts_count_only_for_the_screened_job(self):
        manifest = json.loads(self.run.build().read_text())
        screening = self.run.root / "ko/speech-job/asr-screening.json"
        value = json.loads(screening.read_text())
        value["targetLanguageSpeechJobJsonSha256"] = "b" * 64
        screening.write_text(json.dumps(value))
        audio_qc = self.run.root / "es/audio-qc.json"
        value = json.loads(audio_qc.read_text())
        value["durationNormalization"]["speechJobJsonSha256"] = "b" * 64
        audio_qc.write_text(json.dumps(value))
        report = group_plan.plan(manifest, self.run.root, identities())
        self.assertEqual(statuses(report, "ko", "g1")["A"], "missing")
        self.assertEqual(statuses(report, "es", "g1")["U"], "missing")
        self.assertEqual(statuses(report, "es", "g1")["A"], "fresh")

    def test_store_records_feed_downstream_and_same_key_conflicts_are_reported(self):
        layer1 = self.run.layer1
        manifest = json.loads(self.run.build().read_text())
        derived = group_plan.derive_records(manifest, self.run.root, layer1, self.run.anchor)
        translator = derived["ko"]["records"]["g1"]["T"]
        reviewer = derived["ko"]["records"]["g1"]["R"]
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            # A stored T whose draft differs from what the stored R reviewed.
            other_draft = records.make_record("T", translator["layer1"], "ko", "g1", ["u1"], translator["inputs"],
                                              translator["stageImplementationSha256"],
                                              dict(translator["outputs"], draftTextSha256="0" * 64), "pass")
            store.put(other_draft)
            store.put(reviewer)
            del manifest["locales"]["ko"]["layer2Rounds"]
            report = group_plan.plan(manifest, self.run.root, identities(), store=store)
            stage_r = report["locales"]["ko"]["groups"][0]["stages"]["R"]
            self.assertEqual(stage_r["status"], "stale")
            self.assertIn("input_changed:draftTextSha256", stage_r["reasons"])
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            conflicting = dict(copy.deepcopy(translator), verdict={"status": "unknown", "codes": []})
            store.put(conflicting)
            report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root,
                                     identities(), store=store)
            stage_t = report["locales"]["ko"]["groups"][0]["stages"]["T"]
            self.assertEqual((stage_t["status"], stage_t["inputKeys"]), ("conflict", [translator["inputKey"]]))
            self.assertEqual(statuses(report, "ko", "g1")["R"], "stale")

    def test_a_stored_condensation_is_compared_with_the_current_text(self):
        layer1 = self.run.layer1
        manifest = json.loads(self.run.build().read_text())
        receipt_path = self.run.root / "ko/text-qc.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["results"][0]["mode"] = "shorten"
        receipt_path.write_text(json.dumps(receipt))
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            store.put(records.make_record(
                "C", layer1, "ko", "g1", ["u1"],
                {"condensationRequestSha256": "c" * 64, "englishSha256": "0" * 64,
                 "targetTextSha256": sha(TEXT["ko"]["g1"])}, QC, {"spokenTextSha256": "d" * 64}, "pass"))
            report = group_plan.plan(manifest, self.run.root, identities(), store=store)
            stage_c = report["locales"]["ko"]["groups"][0]["stages"]["C"]
            self.assertEqual(stage_c["status"], "stale")
            self.assertIn("input_changed:englishSha256", stage_c["reasons"])
            self.assertIn("condensationRequestSha256", stage_c["notCompared"])

    def test_current_identities_resolve_policy_and_plugin_beside_the_manifest(self):
        from tongxing_production.text import candidate
        from tongxing_production.text import policy as policy_tools
        manifest = json.loads(self.run.build().read_text())
        seen = []
        with patch.object(policy_tools, "validate_policy", return_value={"languageReviewPolicySha256": LANGUAGE_POLICY}), \
                patch.object(candidate, "plugin_implementation_sha256", side_effect=lambda path: seen.append(path) or PLUGIN):
            current = group_plan.current_identities(manifest, self.run.root)
        self.assertEqual(seen, [self.run.root / "plugin.py"] * 2)
        self.assertEqual(current["locales"]["ko"]["pluginImplementationSha256"], PLUGIN)

    def test_a_candidate_bound_to_another_layer1_is_never_fresh(self):
        self.run.build()
        candidate_path = self.run.root / "ko/candidate.json"
        candidate = json.loads(candidate_path.read_text())
        candidate["anchorManifestSha256"] = "0" * 64
        candidate_path.write_text(json.dumps(candidate))
        report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root, identities())
        self.assertFalse(report["locales"]["ko"]["candidateLayer1Current"])
        stage_t = report["locales"]["ko"]["groups"][0]["stages"]["T"]
        self.assertEqual(stage_t["status"], "stale")
        self.assertIn("candidate_layer1_changed", stage_t["reasons"])
        self.assertIn("BOUND TO ANOTHER LAYER 1", group_plan.text_summary(report))
        self.assertEqual(statuses(report, "es", "g1"), ALL_FRESH)

    def test_compatible_records_under_different_keys_are_a_conflict(self):
        manifest = json.loads(self.run.build().read_text())
        derived = group_plan.derive_records(manifest, self.run.root, self.run.layer1, self.run.anchor)
        translator = derived["ko"]["records"]["g1"]["T"]
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            # Differs only in an input this plan does not recompute, and its paid outcome is unknown.
            store.put(records.make_record("T", translator["layer1"], "ko", "g1", ["u1"],
                                          dict(translator["inputs"], revisionSha256="5" * 64),
                                          translator["stageImplementationSha256"], translator["outputs"], "unknown"))
            report = group_plan.plan(manifest, self.run.root, identities(), store=store)
        stage_t = report["locales"]["ko"]["groups"][0]["stages"]["T"]
        self.assertEqual((stage_t["status"], stage_t["reasons"]), ("conflict", ["multiple_compatible_input_keys"]))

    def test_records_claiming_other_units_are_a_conflict(self):
        manifest = json.loads(self.run.build().read_text())
        derived = group_plan.derive_records(manifest, self.run.root, self.run.layer1, self.run.anchor)
        synthesis = derived["ko"]["records"]["g2"]["S"]
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            store.put(records.make_record("S", synthesis["layer1"], "ko", "g2", ["u2"], synthesis["inputs"],
                                          synthesis["stageImplementationSha256"], synthesis["outputs"], "pass"))
            report = group_plan.plan(manifest, self.run.root, identities(), store=store)
        stage_s = report["locales"]["ko"]["groups"][1]["stages"]["S"]
        self.assertEqual((stage_s["status"], stage_s["reasons"]), ("conflict", ["record_source_units_mismatch"]))

    def test_speech_results_need_their_own_intent_binding_and_bytes(self):
        self.run.build()
        receipt_path = self.run.root / "ko/speech-job/receipts/unit-0000.json"
        receipt = json.loads(receipt_path.read_text())
        receipt_path.write_text(json.dumps(dict(receipt, jobJsonSha256="b" * 64)))
        (self.run.root / "es/speech-job/languages/es/audio/unit-0001.wav").write_bytes(b"changed")
        report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root, identities())
        self.assertEqual(statuses(report, "ko", "g1")["S"], "missing")
        self.assertEqual(statuses(report, "es", "g2")["S"], "missing")
        self.assertEqual(statuses(report, "ko", "g2")["S"], "fresh")

    def test_a_success_receipt_for_other_caches_does_not_lend_its_runner(self):
        self.run.build()
        success = self.run.root / "ko/round-001/group-0001-payload-cache-success.json"
        value = json.loads(success.read_text())
        value["roles"]["translator"]["cacheSha256"] = "0" * 64
        success.write_text(json.dumps(value))
        report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root, identities())
        self.assertIn("stageImplementation", report["locales"]["ko"]["groups"][0]["stages"]["T"]["notCompared"])

    def test_full_text_groups_ignore_historical_condensation(self):
        manifest = json.loads(self.run.build().read_text())
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            store.put(records.make_record(
                "C", self.run.layer1, "ko", "g1", ["u1"],
                {"condensationRequestSha256": "c" * 64, "englishSha256": "0" * 64, "targetTextSha256": "0" * 64},
                QC, {"spokenTextSha256": "d" * 64}, "pass"))
            report = group_plan.plan(manifest, self.run.root, identities(), store=store)
        self.assertEqual(statuses(report, "ko", "g1"), ALL_FRESH)

    def test_condensed_speech_is_compared_with_the_condensed_text(self):
        manifest = json.loads(self.run.build().read_text())
        receipt_path = self.run.root / "ko/text-qc.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["results"][0]["mode"] = "shorten"
        receipt_path.write_text(json.dumps(receipt))
        rows = legacy.english_rows(self.run.anchor, ["u1"])
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            # C produced exactly the text S synthesized.
            store.put(records.make_record(
                "C", self.run.layer1, "ko", "g1", ["u1"],
                {"condensationRequestSha256": "c" * 64, "englishSha256": legacy.qc_english_sha256(rows),
                 "targetTextSha256": sha(TEXT["ko"]["g1"])}, QC, {"spokenTextSha256": sha(TEXT["ko"]["g1"])}, "pass"))
            fresh = group_plan.plan(manifest, self.run.root, identities(), store=store)
        self.assertEqual(statuses(fresh, "ko", "g1"), dict(ALL_FRESH, C="fresh"))
        with tempfile.TemporaryDirectory() as directory:
            store = records.RecordStore(Path(directory))
            store.put(records.make_record(
                "C", self.run.layer1, "ko", "g1", ["u1"],
                {"condensationRequestSha256": "c" * 64, "englishSha256": legacy.qc_english_sha256(rows),
                 "targetTextSha256": sha(TEXT["ko"]["g1"])}, QC, {"spokenTextSha256": "e" * 64}, "pass"))
            shorter = group_plan.plan(manifest, self.run.root, identities(), store=store)
        stage_s = shorter["locales"]["ko"]["groups"][0]["stages"]["S"]
        self.assertEqual(stage_s["status"], "stale")
        self.assertIn("input_changed:textSha256", stage_s["reasons"])

    def test_a_failed_synthesis_invalidates_its_consumers_and_is_redone(self):
        self.run.build()
        receipt_path = self.run.root / "ko/speech-job/receipts/unit-0002.json"
        receipt = json.loads(receipt_path.read_text())
        receipt_path.write_text(json.dumps(dict(receipt, fullDecode="fail")))
        report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root, identities())
        self.assertEqual({k: v for k, v in statuses(report, "ko", "g3").items() if k in "SAU"},
                         {"S": "failed", "A": "stale", "U": "stale"})
        self.assertEqual(report["locales"]["ko"]["redoCounts"]["S"], 1)

    def test_asr_evidence_needs_the_desired_settings_and_follows_them(self):
        changed = identities()
        changed["locales"]["ko"]["asrSettingsSha256"] = records.json_sha256(dict(ASR_SETTINGS_VALUE, batchSize=8))
        changed["locales"]["es"]["asrSettingsSha256"] = None
        report = self.plan(changed)
        stage_a = report["locales"]["ko"]["groups"][0]["stages"]["A"]
        self.assertEqual(stage_a["status"], "stale")
        self.assertIn("input_changed:asrSettingsSha256", stage_a["reasons"])
        self.assertEqual(statuses(report, "ko", "g1")["U"], "stale")
        stage_a = report["locales"]["es"]["groups"][0]["stages"]["A"]
        self.assertEqual((stage_a["status"], stage_a["reasons"]), ("stale", ["asr_settings_not_supplied"]))

    def test_a_shortening_group_without_condensation_is_missing_it(self):
        self.run.build()
        receipt_path = self.run.root / "ko/text-qc.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["results"][0]["mode"] = "shorten"
        receipt_path.write_text(json.dumps(receipt))
        report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root, identities())
        self.assertEqual(statuses(report, "ko", "g1")["C"], "missing")
        self.assertEqual(statuses(report, "ko", "g1")["S"], "stale")

    def test_a_reviewer_only_policy_change_starts_at_review(self):
        self.run.produced_policy = copy.deepcopy(self.run.policy)
        self.run.policy = dict(self.run.policy, reviewer=dict(self.run.policy["reviewer"], promptVersion="review-v2"))
        report = self.plan()
        changed = statuses(report, "ko", "g1")
        self.assertEqual((changed["T"], changed["R"]), ("fresh", "stale"))
        self.assertIn("input_changed:modelFacingPolicySha256", report["locales"]["ko"]["groups"][0]["stages"]["R"]["reasons"])

    def test_a_review_the_runner_would_reject_is_not_a_pass(self):
        self.run.build()
        sol = self.run.root / "ko/round-001/group-0001-sol.json"
        value = json.loads(sol.read_text())
        value["result"]["semanticReview"]["uncertainty"] = ["Is this the right verse?"]
        sol.write_text(json.dumps(value))
        report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root, identities())
        self.assertEqual(statuses(report, "ko", "g1")["R"], "failed")

    def test_without_the_plugin_file_p_is_never_fresh(self):
        current = identities()
        current["locales"]["ko"]["pluginImplementationSha256"] = None
        report = self.plan(current)
        stage_p = report["locales"]["ko"]["groups"][0]["stages"]["P"]
        self.assertEqual((stage_p["status"], stage_p["reasons"]), ("stale", ["plugin_not_supplied"]))

    def test_a_candidate_whose_text_disagrees_with_its_utterances_is_not_reused(self):
        self.run.build()
        candidate_path = self.run.root / "ko/candidate.json"
        candidate = json.loads(candidate_path.read_text())
        candidate["groups"][0]["targetText"] = "다른 문장입니다."
        candidate_path.write_text(json.dumps(candidate))
        report = group_plan.plan(json.loads((self.run.root / "inputs.json").read_text()), self.run.root, identities())
        row = report["locales"]["ko"]["groups"][0]["stages"]
        self.assertEqual(row["T"]["status"], "fresh")
        for stage in ("R", "P", "Q", "S", "A", "U"):
            self.assertEqual(row[stage]["status"], "stale", stage)
            self.assertIn("candidate_text_inconsistent", row[stage]["reasons"])

    def test_cli_plan_prints_a_summary_and_writes_only_its_report(self):
        manifest = self.run.build()
        output = self.run.root / "out" / "plan.json"
        stdout = io.StringIO()
        with patch.object(group_plan, "current_identities", return_value=identities()), redirect_stdout(stdout):
            self.assertEqual(group_plan.main(["plan", "--manifest", str(manifest), "--locale", "ko",
                                              "--group-id", "g4", "--output", str(output)]), 0)
        report = json.loads(output.read_text())
        self.assertEqual(list(report["locales"]), ["ko"])
        self.assertEqual(report["locales"]["ko"]["redoCounts"]["T"], 1)
        self.assertIn("0 model calls, nothing dispatched", stdout.getvalue())
        with patch.object(group_plan, "current_identities", return_value=identities()), \
                self.assertRaisesRegex(ValueError, "group_id_needs_one_locale"):
            group_plan.main(["plan", "--manifest", str(manifest), "--group-id", "g4"])


if __name__ == "__main__":
    unittest.main()


class GroupBudgetTests(unittest.TestCase):
    """DEV-GRP-003: the allowance follows the selected groups, never the first round."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.run = Run(Path(self.directory.name))
        self.profile = json.loads((ROOT / "config/weekly-run-profile.json").read_text())

    def plan(self, current=None, *, scale="week", profile=None, **options):
        manifest = json.loads(self.run.build().read_text())
        return group_plan.plan(manifest, self.run.root, current or identities(),
                               budget={"profile": profile or self.profile, "scale": scale}, **options)

    def bounds(self):
        from tongxing_production.orchestration import group_budget
        return group_budget.per_try_bounds(self.profile, self.run.policy, "gpt-6.1-sol")

    def test_a_named_group_gets_every_try_it_has_left_even_after_a_full_cache_replay(self):
        from tongxing_production.review import text_qc
        report = self.plan(directives={"ko": ["g2"]})
        budget = report["locales"]["ko"]["budget"]
        self.assertEqual([row["translationGroupId"] for row in budget["groups"]], ["g2"])
        row = budget["groups"][0]
        self.assertEqual((row["basis"], row["status"], row["tries"]),
                         ("operator_directive", "reserved", text_qc.MAX_TEXT_REPAIR_ATTEMPTS))
        bounds = self.bounds()
        per_try = bounds["translation"]["costMicrousd"]
        self.assertEqual(row["reserve"]["layer2"]["costMicrousd"], per_try * row["tries"])
        self.assertEqual(row["reserve"]["qc"]["costMicrousd"], bounds["textQc"]["costMicrousd"] * row["tries"])
        self.assertGreater(per_try, 0)
        # Nothing else spends money: every other group is reused at $0.
        self.assertEqual(budget["reusedGroupCount"], 3)
        self.assertEqual(report["locales"]["es"]["budget"]["groups"], [])

    def test_ledger_attempts_shrink_the_tries_and_an_exhausted_group_reserves_nothing(self):
        from tongxing_production.review import text_qc
        self.run.build()
        receipt_path = self.run.root / "ko/text-qc.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["results"][1]["failedAttempts"] = 3
        receipt["results"][2]["failedAttempts"] = text_qc.MAX_TEXT_REPAIR_ATTEMPTS
        receipt_path.write_text(json.dumps(receipt))
        manifest = json.loads((self.run.root / "inputs.json").read_text())
        report = group_plan.plan(manifest, self.run.root, identities(), directives={"ko": ["g2", "g3"]},
                                 budget={"profile": self.profile, "scale": "week"})
        rows = {row["translationGroupId"]: row for row in report["locales"]["ko"]["budget"]["groups"]}
        self.assertEqual((rows["g2"]["tries"], rows["g2"]["status"]), (text_qc.MAX_TEXT_REPAIR_ATTEMPTS - 3, "reserved"))
        self.assertEqual((rows["g3"]["tries"], rows["g3"]["status"]), (0, "repair_limit_reached"))
        self.assertEqual(rows["g3"]["reserve"]["layer2"]["costMicrousd"], 0)

    def test_a_group_that_does_not_fit_stops_before_dispatch_and_others_keep_their_reservation(self):
        from tongxing_production.orchestration import group_budget
        bounds = self.bounds()
        one_group = bounds["translation"]["costMicrousd"] * 4
        profile = copy.deepcopy(self.profile)
        # Room for one named group's layer-2 tries, not two.
        profile["layer2"]["capUsdPerLocale"]["week"] = (one_group + one_group // 2) / 1_000_000
        report = self.plan(profile=profile, directives={"ko": ["g3", "g1", "g4"]})
        budget = report["locales"]["ko"]["budget"]
        self.assertEqual([(row["translationGroupId"], row["status"]) for row in budget["groups"]],
                         [("g3", "reserved"), ("g1", "repair_spend_cap"), ("g4", "repair_spend_cap")])
        self.assertEqual(group_budget.admit(budget, "g3"), budget["groups"][0]["reserve"])
        with self.assertRaisesRegex(ValueError, "repair_spend_cap:g1"):
            group_budget.admit(budget, "g1")
        with self.assertRaisesRegex(ValueError, "group_not_budgeted:g2"):
            group_budget.admit(budget, "g2")
        self.assertEqual(budget["totals"]["reservedMicrousd"]["layer2"], one_group)

    def test_only_the_paid_steps_that_will_run_again_are_budgeted(self):
        plugin = self.plan(identities(plugin="9" * 64))
        self.assertEqual(plugin["locales"]["ko"]["budget"]["groups"], [])  # P runs locally at no cost
        qc = self.plan(identities(machineQcImplementationSha256="9" * 64))
        rows = qc["locales"]["ko"]["budget"]["groups"]
        self.assertEqual({tuple(row["steps"]) for row in rows}, {("textQc",)})
        self.assertEqual(rows[0]["reserve"]["qc"]["costMicrousd"], self.bounds()["textQc"]["costMicrousd"])
        self.assertEqual(rows[0]["reserve"]["layer2"]["costMicrousd"], 0)
        voice = self.plan(identities(rendererSoundIdentitySha256="9" * 64))
        self.assertEqual({tuple(row["steps"]) for row in voice["locales"]["es"]["budget"]["groups"]},
                         {("secondaryAsr",)})

    def test_a_failed_synthesis_is_budgeted_for_new_audio(self):
        self.run.build()
        receipt_path = self.run.root / "es/speech-job/receipts/unit-0001.json"
        receipt = json.loads(receipt_path.read_text())
        receipt_path.write_text(json.dumps(dict(receipt, fullDecode="fail")))
        manifest = json.loads((self.run.root / "inputs.json").read_text())
        report = group_plan.plan(manifest, self.run.root, identities(), budget={"profile": self.profile, "scale": "week"})
        rows = report["locales"]["es"]["budget"]["groups"]
        self.assertEqual([(row["translationGroupId"], row["steps"]) for row in rows], [("g2", ["secondaryAsr"])])

    def test_a_shortened_group_also_budgets_condensation(self):
        self.run.build()
        receipt_path = self.run.root / "ko/text-qc.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["results"][0]["mode"] = "shorten"
        receipt_path.write_text(json.dumps(receipt))
        manifest = json.loads((self.run.root / "inputs.json").read_text())
        report = group_plan.plan(manifest, self.run.root, identities(), directives={"ko": ["g1"]},
                                 budget={"profile": self.profile, "scale": "week"})
        row = report["locales"]["ko"]["budget"]["groups"][0]
        self.assertIn("condensation", row["steps"])
        bounds = self.bounds()
        self.assertEqual(row["perTry"]["qc"]["costMicrousd"],
                         bounds["textQc"]["costMicrousd"] + bounds["condensation"]["costMicrousd"])

    def test_bounds_come_from_the_profile_limits_and_the_owning_constants(self):
        from tongxing_production.compute import provider_limits as limits
        from tongxing_production.compute import transcription_request as transcription
        from tongxing_production.review import condensation
        bounds = self.bounds()
        layer2, qc = self.profile["layer2"]["requestLimits"], self.profile["qc"]["requestLimits"]
        self.assertEqual(bounds["translation"]["costMicrousd"],
                         2 * limits._cost("gpt-6.1-sol", layer2["maxInputTokens"], layer2["maxCompletionTokens"]))
        call = limits._cost("gpt-6.1-sol", qc["maxInputTokens"], qc["maxCompletionTokens"])
        self.assertEqual(bounds["textQc"]["costMicrousd"], 2 * call)
        self.assertEqual(bounds["condensation"]["costMicrousd"], condensation.MAX_ATTEMPTS * call)
        self.assertEqual(bounds["secondaryAsr"]["costMicrousd"],
                         -(-transcription.MAX_DURATION_SECONDS // 60) * transcription.MICROUSD_PER_MINUTE)
        with self.assertRaisesRegex(ValueError, "unknown_profile_scale"):
            self.plan(scale="month")
