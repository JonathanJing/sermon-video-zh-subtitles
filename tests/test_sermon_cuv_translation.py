import copy
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest import mock

from scripts import sermon_cuv_translation as mod
from scripts.cuv_scripture import CuvLibrary


class CuvTranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / "parent/job.json"
        self.out = self.root / "translation"
        self.map = self.root / "map.json"
        self.library = CuvLibrary.from_path()
        self.make_source(2)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def make_source(self, count):
        self.blocks = [{"id": i, "en": "I say: I am Alpha and Omega. Trust him." if i == 0 else f"Explanation number {i}.",
                        "zh": "旧译文", "start": i * 10, "end": i * 10 + 10} for i in range(count)]
        self.write(self.parent, {"blocks": self.blocks})
        self.mapping = {"schemaVersion": mod.MAP_SCHEMA, "parentJobSha256": mod.file_hash(self.parent),
            "issues": [], "blocks": [{"id": b["id"], "quotes": [], "speakerReferences": [], "uncertainty": []}
                                     for b in self.blocks]}
        self.mapping["blocks"][0]["quotes"] = [{"quoteId": "q1", "sourceText": "I am Alpha and Omega.",
            "reference": "REV 1:8", "evidence": "Direct partial quotation in sermon context", "uncertainty": []}]
        self.write(self.map, self.mapping)

    def response(self, result):
        return {"model": mod.MODEL, "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}

    def fake_chat(self, key, payload):
        instruction = payload["messages"][0]["content"]
        data = json.loads(payload["messages"][1]["content"])
        if mod.DISCOVER in instruction:
            return self.response(self.mapping)
        if mod.SELECT in instruction:
            text = self.library.lookup("REV 1:8")["text"]
            start = text.index("我是阿拉法")
            end = text.index("，是昔在")
            return self.response({"issues": [], "quotes": [{"quoteId": q["quoteId"],
                "parts": [{"reference": "REV 1:8", "text": text[start:end]}],
                "evidence": "Only the Alpha/Omega clause was read", "uncertainty": []}
                for q in data["quotations"]]})
        if mod.AUDIT_QUOTES in instruction:
            return self.response({"issues": [], "resolutions": [{"index": i, "status": "resolved", "evidence": "Reviewed input evidence"}
                for i in range(len(data["inputIssues"]))], "blocks": [{"id": b["id"], "quoteCoverage": "pass",
                "evidence": "Partial quoted clause only; narration preserved", "uncertainty": [], "issues": []}
                for b in data["sourceBlocks"]]})
        rows = []
        for b in data["targets"]:
            row = {"id": b["id"], "zhTemplate": "我说：" + "".join(q["token"] for q in b["quotes"]) + "请相信祂。",
                   "evidence": "Checked complete narration and tokens", "uncertainty": [], "issues": []}
            if mod.REVIEW in instruction:
                row.update(checks={k: "pass" for k in mod.CHECKS}, quoteCoverage="pass")
            rows.append(row)
        return self.response({"blocks": rows, "issues": []})

    def execute(self, **kwargs):
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=self.fake_chat) as call:
            result = mod.run(self.parent, self.out, reference_map_path=self.map, **kwargs)
        return result, call.call_count

    def test_full_chain_exact_injection_and_offline_spoken_gate(self):
        result, count = self.execute()
        self.assertEqual("passed", result["status"])
        self.assertEqual(4, count)
        blocks = mod.read(self.out / "blocks.json")
        self.assertEqual([b["en"] for b in self.blocks], [b["en"] for b in blocks])
        self.assertIn("我是阿拉法，我是俄梅戛", blocks[0]["zh"])
        self.assertNotIn("以后", blocks[0]["zh"], "Unread remainder must not be inserted")
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            self.assertEqual("passed", mod.validate_spoken_review(self.parent.parent, self.out / "spoken-review.json")["status"])
        review = mod.read(self.out / "spoken-review.json")
        self.assertFalse(review["humanApproval"])
        self.assertEqual([0, 1], review["reviewedBlockIds"])
        self.assertEqual({k: "pass" for k in mod.CHECKS}, review["checks"])

    def test_sixty_seven_blocks_complete_and_resume_without_model(self):
        self.make_source(67)
        result, _ = self.execute()
        self.assertEqual(67, result["blocks"])
        with mock.patch.dict(mod.os.environ, {}, clear=True), \
             mock.patch.object(mod, "chat_json", side_effect=AssertionError("cached")):
            self.assertEqual(result, mod.run(self.parent, self.out, reference_map_path=self.map))

    def caveat_chat(self, key, payload):
        instruction = payload["messages"][0]["content"]
        data = json.loads(payload["messages"][1]["content"])
        if mod.AUDIT_NARRATION_CAVEATS in instruction:
            return self.response({"issues": [], "caveats": [
                {**{k: c[k] for k in ("blockId", "uncertaintyIndex", "uncertainty")},
                 "status": "narration_only", "evidence": "The source preserves an unverified narrative association; no direct quotation is affected."}
                for c in data["caveats"]]})
        response = self.fake_chat(key, payload)
        if mod.AUDIT_QUOTES in instruction:
            audit = json.loads(response["choices"][0]["message"]["content"])
            for b in audit["blocks"]:
                if b["id"] in (7, 17, 37, 54, 61, 62, 64, 65):
                    b["uncertainty"] = ["候选经文背景尚未核实；保留为叙述，不提升为已确认出处。"]
                if b["id"] == 62:
                    b["uncertainty"].append("没有音频证据判断“John chapter 1”源于口误还是转录错误；保留现有英文，不影响其后直接引文来源的确认。")
            return self.response(audit)
        return response

    def test_caveat_resume_retains_nine_findings_and_reuses_existing_audit(self):
        self.make_source(67)
        def stopped(key, payload):
            if mod.AUDIT_NARRATION_CAVEATS in payload["messages"][0]["content"]:
                raise RuntimeError("Stop before new classification")
            return self.caveat_chat(key, payload)
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=stopped):
            with self.assertRaises(RuntimeError):
                mod.run(self.parent, self.out, reference_map_path=self.map, batch_size=8)
        audit_path = next((self.out / "cache").glob("audit-quotes-*.json"))
        before = audit_path.read_bytes()
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=self.caveat_chat) as call:
            mod.run(self.parent, self.out, reference_map_path=self.map, batch_size=8)
        self.assertEqual(19, call.call_count, "Only one classification plus nine translation/review batches")
        self.assertEqual(before, audit_path.read_bytes())
        report = mod.read(self.out / "report.json")
        self.assertEqual(9, len(report["caveatReview"]["review"]["caveats"]))
        self.assertEqual(8, sum(bool(b["uncertainty"]) for b in report["quotationAudit"]["blocks"]))
        self.assertEqual(9, len(report["caveatReview"]["inputCaveats"]))
        self.assertIn("lockedReferences", report["caveatReview"]["inputCaveats"][0])
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            self.assertEqual("passed", mod.validate(self.out)["status"])
        report["caveatReview"]["review"]["caveats"][0]["uncertainty"] = "erased"
        self.write(self.out / "report.json", report)
        with self.assertRaisesRegex(ValueError, "caveatReview"):
            mod.validate(self.out)

    def test_caveat_classifier_rejects_unresolved_or_missing_evidence(self):
        for mutation in (lambda r: r.update(status="quotation_unresolved"), lambda r: r.update(evidence="")):
            with self.subTest(mutation=mutation):
                def invalid(key, payload):
                    response = self.caveat_chat(key, payload)
                    if mod.AUDIT_NARRATION_CAVEATS in payload["messages"][0]["content"]:
                        value = json.loads(response["choices"][0]["message"]["content"])
                        mutation(value["caveats"][0])
                        return self.response(value)
                    return response
                self.make_source(8)
                self.out = self.root / ("failure-" + str(id(mutation)))
                with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
                     mock.patch.object(mod, "chat_json", side_effect=invalid):
                    with self.assertRaisesRegex(ValueError, "Unresolved quotation"):
                        mod.run(self.parent, self.out, reference_map_path=self.map)
                self.assertFalse((self.out / "spoken-review.json").exists())

    def test_caveat_classifier_rejects_coverage_identity_and_changed_uncertainty(self):
        mutations = [lambda r: r["caveats"].clear(), lambda r: r["caveats"][0].update(blockId=99),
                     lambda r: r["caveats"][0].update(uncertaintyIndex=1),
                     lambda r: r["caveats"][0].update(uncertainty="removed"),
                     lambda r: r.update(issues=["unresolved"])]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                self.make_source(8)
                self.out = self.root / ("coverage-" + str(index))
                def invalid(key, payload):
                    response = self.caveat_chat(key, payload)
                    if mod.AUDIT_NARRATION_CAVEATS in payload["messages"][0]["content"]:
                        value = json.loads(response["choices"][0]["message"]["content"])
                        mutation(value)
                        return self.response(value)
                    return response
                with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
                     mock.patch.object(mod, "chat_json", side_effect=invalid):
                    with self.assertRaisesRegex(ValueError, "Narration caveat"):
                        mod.run(self.parent, self.out, reference_map_path=self.map)

    def test_caveat_classifier_never_bypasses_failed_quote_audit(self):
        self.make_source(8)
        def invalid(key, payload):
            response = self.caveat_chat(key, payload)
            if mod.AUDIT_NARRATION_CAVEATS in payload["messages"][0]["content"]:
                self.fail("Failed quotation must block before classification")
            if mod.AUDIT_QUOTES in payload["messages"][0]["content"]:
                value = json.loads(response["choices"][0]["message"]["content"])
                value["blocks"][0]["quoteCoverage"] = "fail"
                return self.response(value)
            return response
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=invalid):
            with self.assertRaisesRegex(ValueError, "Independent quotation audit failed"):
                mod.run(self.parent, self.out, reference_map_path=self.map)

    def test_provisional_draft_concerns_reach_independent_review_with_caveat_evidence(self):
        self.make_source(8)
        seen = []
        def provisional(key, payload):
            instruction = payload["messages"][0]["content"]
            if mod.REVIEW in instruction:
                data = json.loads(payload["messages"][1]["content"])
                seen.append(data)
                self.assertIn(mod.REVIEW_DRAFT_CONCERNS, instruction)
            response = self.caveat_chat(key, payload)
            if mod.TRANSLATE in instruction:
                value = json.loads(response["choices"][0]["message"]["content"])
                value["issues"] = ["Check provisional narration in independent review"]
                value["blocks"][-1]["uncertainty"] = ["被提背景出处未核实，叙述译文保持讲员意思。"]
                value["blocks"][-1]["issues"] = ["Confirm this remains narration"]
                return self.response(value)
            return response
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=provisional):
            result = mod.run(self.parent, self.out, reference_map_path=self.map, batch_size=8)
        self.assertEqual("passed", result["status"])
        self.assertEqual(1, len(seen))
        self.assertTrue(seen[0]["draft"]["issues"])
        self.assertTrue(seen[0]["draft"]["blocks"][7]["uncertainty"])
        self.assertEqual(7, seen[0]["caveatReview"]["caveats"][0]["blockId"])
        mod.check_binding(seen[0]["caveatReview"]["evidence"])
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            self.assertEqual("passed", mod.validate(self.out)["status"])

    def test_malformed_draft_and_damaged_tokens_stop_before_review(self):
        mutations = [lambda r: r.update(uncertainty="not a list"), lambda r: r.update(issues=None),
                     lambda r: r.update(evidence=""), lambda r: r.update(zhTemplate="Missing locked quote")]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                self.out = self.root / ("bad-draft-" + str(index))
                def invalid(key, payload):
                    instruction = payload["messages"][0]["content"]
                    if mod.REVIEW in instruction:
                        self.fail("Malformed draft must not reach final review")
                    response = self.fake_chat(key, payload)
                    if mod.TRANSLATE in instruction:
                        value = json.loads(response["choices"][0]["message"]["content"])
                        mutation(value["blocks"][0])
                        return self.response(value)
                    return response
                with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
                     mock.patch.object(mod, "chat_json", side_effect=invalid):
                    with self.assertRaises(ValueError):
                        mod.run(self.parent, self.out, reference_map_path=self.map)

    def test_final_uncertainty_still_blocks_after_provisional_draft(self):
        def invalid(key, payload):
            response = self.fake_chat(key, payload)
            instruction = payload["messages"][0]["content"]
            if mod.TRANSLATE in instruction or mod.REVIEW in instruction:
                value = json.loads(response["choices"][0]["message"]["content"])
                value["blocks"][0]["uncertainty"] = ["Meaning unresolved"]
                return self.response(value)
            return response
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=invalid):
            with self.assertRaisesRegex(ValueError, "Unresolved translation/review"):
                mod.run(self.parent, self.out, reference_map_path=self.map)
        self.assertFalse((self.out / "spoken-review.json").exists())

    def test_last_three_blocks_accept_preserved_evidence_arrays(self):
        self.make_source(67)
        evidence = ["逐句对照英文，完整保留讲员的个人应用。", "未增补候选经文，数字、否定和引用归属均已核对。"]
        def arrays(key, payload):
            response = self.fake_chat(key, payload)
            instruction = payload["messages"][0]["content"]
            if mod.TRANSLATE in instruction or mod.REVIEW in instruction:
                value = json.loads(response["choices"][0]["message"]["content"])
                for row in value["blocks"]:
                    if row["id"] in (64, 65, 66):
                        row["evidence"] = evidence
                return self.response(value)
            return response
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=arrays):
            result = mod.run(self.parent, self.out, reference_map_path=self.map, batch_size=8)
        self.assertEqual(67, result["blocks"])
        report = mod.read(self.out / "report.json")
        self.assertEqual([evidence] * 3, [r["evidence"] for r in report["narrativeReviews"][-3:]])
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            self.assertEqual("passed", mod.validate(self.out)["status"])

    def test_draft_and_final_reject_empty_or_malformed_evidence(self):
        row = {"zhTemplate": "保留讲员叙述。", "uncertainty": [], "issues": [],
               "checks": {k: "pass" for k in mod.CHECKS}, "quoteCoverage": "pass"}
        invalid = [None, "", "  ", [], [""], ["valid", "  "], ["valid", 7],
                   ["valid", {"evidence": "wrong shape"}], {"evidence": "wrong shape"}, 7]
        for value in invalid:
            with self.subTest(value=value):
                row["evidence"] = value
                with self.assertRaises(ValueError):
                    mod.draft_row(row, [])
                with self.assertRaises(ValueError):
                    mod.reviewed_row(row, [], checks=True)

    def make_timing_source(self):
        source = self.root / "source.wav"
        source.write_bytes(b"frozen source fixture")
        old = mod.read(self.parent)
        old.update(inputs={"sourceAudio": mod.bind(source)}, voice={"checkpointSha256": "fixed-checkpoint"},
                   sourceStartSeconds=0, sourceDurationSeconds=20)
        self.write(self.parent, old)
        self.mapping["parentJobSha256"] = mod.file_hash(self.parent)
        self.write(self.map, self.mapping)
        self.execute()
        return self.make_measured_parent(self.out, self.root / "rendered")

    def make_measured_parent(self, prior, work):
        old_manifest = mod.read(prior / "cuv-manifest.json")
        old_parent = mod.read(old_manifest["parentJob"]["path"])
        blocks = mod.read(prior / "blocks.json")
        units = [{"id": i, "blockId": b["id"], "text": b["zh"], "gapAfterSeconds": .45}
                 for i, b in enumerate(blocks)]
        job = {**old_parent, "blocks": [{**b, "zh": new["zh"]} for b, new in zip(old_parent["blocks"], blocks)],
               "units": units, "inputs": {**old_parent["inputs"], "spokenScriptReview": mod.bind(prior / "spoken-review.json")},
               "revisionOf": {"path": str(Path(old_manifest["parentJob"]["path"]).parent),
                              "jobSha256": old_manifest["parentJob"]["sha256"]}}
        self.write(work / "job.json", job)
        job_hash = mod.file_hash(work / "job.json")
        def wav(path, frames):
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as f:
                f.setparams((1, 2, 24000, frames, "NONE", "not compressed"))
                f.writeframes(b"\0\0" * frames)
        cues, cursor = [], 0
        for index, unit in enumerate(units):
            frames = 96000 if index == 0 else 24000
            path = work / f"render/unit-{index:04d}.wav"
            wav(path, frames)
            self.write(path.with_suffix(".json"), {"unit": unit, "sha256": mod.file_hash(path),
                "identity": {"jobSha256": job_hash, "checkpointSha256": "fixed-checkpoint"}, "durationSeconds": frames / 24000})
            cues.append({"unitId": index, "blockId": unit["blockId"], "text": unit["text"],
                         "start": cursor / 24000, "end": (cursor + frames) / 24000})
            cursor += frames + (10800 if index + 1 < len(units) else 0)
        wav(work / "render/chinese.raw.wav", cursor)
        self.write(work / "render/report.json", {"status": "complete_candidate_render", "jobSha256": job_hash,
            "checkpointSha256": "fixed-checkpoint", "sha256": mod.file_hash(work / "render/chinese.raw.wav"),
            "durationSeconds": cursor / 24000, "cues": cues})
        anchors = [{"blockId": 0, "start": 0, "end": 1, "issues": []},
                   {"blockId": 1, "start": 3, "end": 5, "issues": []}]
        self.write(work / "source-alignment/report.json", {"jobSha256": job_hash,
            "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"], "timeOrigin": "approved_sermon_clip_start",
            "fullVideoOffsetSeconds": 0, "blocks": anchors})
        import sys
        sys.path.insert(0, str(mod.ROOT / "experiments/sermon-dubbing-poc"))
        from check_weekly_timing import budgets
        rows, failures = budgets(job["blocks"], anchors, cues, 20)
        self.write(work / "synchronization/report.json", {"schemaVersion": "sermon-video-sync-budget-v1",
            "jobSha256": job_hash, "alignmentSha256": mod.file_hash(work / "source-alignment/report.json"),
            "anchorReviewSha256": None, "anchorReviewType": "unreviewed_machine_anchors", "sourceVideoOffsetSeconds": 0,
            "durationSeconds": 20, "blocks": rows, "failures": failures, "status": "needs_timing_review"})
        return work

    def timing_chat(self, key, payload):
        instruction = payload["messages"][0]["content"]
        self.assertTrue(mod.COMPACT_NARRATION in instruction or mod.REVIEW in instruction)
        data = json.loads(payload["messages"][1]["content"])
        rows = []
        for target in data["targets"]:
            row = {"id": target["id"], "zhTemplate": target["currentTemplate"][1:],
                   "evidence": ["Narration shortened, all source meaning and CUV tokens preserved"],
                   "uncertainty": [], "issues": []}
            if mod.REVIEW in instruction:
                row.update(checks={k: "pass" for k in mod.CHECKS}, quoteCoverage="pass")
            rows.append(row)
        return self.response({"issues": [], "blocks": rows})

    def timing_execute(self, prior, work, out):
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=self.timing_chat) as call:
            result = mod.repair_timing(prior, work / "job.json", work / "synchronization/report.json", out)
        return result, call.call_count

    def test_timing_revision_reuses_locks_and_reviews_without_replaying_paid_stages(self):
        work = self.make_timing_source()
        prior = self.out
        original = {p: p.read_bytes() for p in prior.rglob("*.json")}
        revised = self.root / "timing-revision"
        result, calls = self.timing_execute(prior, work, revised)
        self.assertEqual(2, calls)
        self.assertEqual("passed", result["status"])
        old_blocks, new_blocks = mod.read(prior / "blocks.json"), mod.read(revised / "blocks.json")
        self.assertEqual(old_blocks[1], new_blocks[1])
        self.assertEqual(old_blocks[0]["quotes"], new_blocks[0]["quotes"])
        self.assertEqual(old_blocks[0]["en"], new_blocks[0]["en"])
        review = mod.read(revised / "spoken-review.json")
        self.assertEqual(mod.file_hash(work / "job.json"), review["parentJobSha256"])
        self.assertFalse(review["humanApproval"])
        report = mod.read(revised / "report.json")
        self.assertEqual([0], report["timingRevision"]["revisedBlockIds"])
        self.assertEqual([1], report["timingRevision"]["inheritedReviewBlockIds"])
        self.assertEqual("pending_new_synthesis_and_measurement", report["timingRevision"]["timingAcceptance"])
        self.assertTrue(all(p.read_bytes() == value for p, value in original.items()))
        self.assertEqual(0, self.timing_execute(prior, work, revised)[1])
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            mod.validate_spoken_review(work, revised / "spoken-review.json")
        next_work = self.make_measured_parent(revised, self.root / "rendered-again")
        self.assertEqual(2, self.timing_execute(revised, next_work, self.root / "revision-again")[1])

    def test_timing_revision_rejects_missing_render_and_tampered_measurement(self):
        work = self.make_timing_source()
        report = work / "synchronization/report.json"
        value = mod.read(report)
        value["blocks"][0]["availableSeconds"] += 1
        self.write(report, value)
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("No paid work")):
            with self.assertRaisesRegex(ValueError, "Timing report differs"):
                mod.repair_timing(self.out, work / "job.json", report, self.root / "bad-revision")
            (work / "render/report.json").unlink()
            with self.assertRaises(OSError):
                mod.repair_timing(self.out, work / "job.json", report, self.root / "missing-revision")
        self.assertFalse((self.root / "bad-revision").exists())

    def test_timing_revision_rejects_unit_audio_tampering(self):
        work = self.make_timing_source()
        with (work / "render/unit-0000.wav").open("ab") as f:
            f.write(b"changed")
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("No paid work")):
            with self.assertRaisesRegex(ValueError, "unit receipt changed"):
                mod.repair_timing(self.out, work / "job.json", work / "synchronization/report.json", self.root / "bad")

    def test_timing_revision_rejects_changed_tokens_and_failed_final_review(self):
        work = self.make_timing_source()
        for kind in ("tokens", "review"):
            def invalid(key, payload):
                response = self.timing_chat(key, payload)
                result = json.loads(response["choices"][0]["message"]["content"])
                if kind == "tokens":
                    result["blocks"][0]["zhTemplate"] = "删除经文是不允许的。"
                elif mod.REVIEW in payload["messages"][0]["content"]:
                    result["blocks"][0]["checks"]["completeMeaning"] = "fail"
                return self.response(result)
            with self.subTest(kind=kind), mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
                 mock.patch.object(mod, "chat_json", side_effect=invalid):
                target = self.root / ("bad-" + kind)
                with self.assertRaises(ValueError):
                    mod.repair_timing(self.out, work / "job.json", work / "synchronization/report.json", target)
                self.assertFalse((target / "spoken-review.json").exists())

    def test_timing_revision_rejects_anchor_failures_and_already_fitting_audio(self):
        work = self.make_timing_source()
        from check_weekly_timing import budgets
        for kind in ("uncertain-anchor", "already-fits"):
            work = self.make_measured_parent(self.out, self.root / kind)
            alignment_path = work / "source-alignment/report.json"
            alignment = mod.read(alignment_path)
            if kind == "uncertain-anchor":
                alignment["blocks"][0]["issues"] = ["Acoustic boundary needs review"]
            else:
                alignment["blocks"][1]["start"] = 6
                alignment["blocks"][1]["end"] = 7
            self.write(alignment_path, alignment)
            timing_path = work / "synchronization/report.json"
            timing = mod.read(timing_path)
            rows, failures = budgets(mod.read(work / "job.json")["blocks"], alignment["blocks"],
                                     mod.read(work / "render/report.json")["cues"], 20)
            timing.update(alignmentSha256=mod.file_hash(alignment_path), blocks=rows, failures=failures,
                          status="needs_timing_review" if failures else "natural_timing_fits")
            self.write(timing_path, timing)
            with self.subTest(kind=kind), mock.patch.object(mod, "chat_json", side_effect=AssertionError("No paid work")):
                with self.assertRaisesRegex(ValueError, "requires measured overflows"):
                    mod.repair_timing(self.out, work / "job.json", timing_path, self.root / (kind + "-revision"))

    def test_timing_revision_unchanged_model_text_is_not_a_repair(self):
        work = self.make_timing_source()
        def unchanged(key, payload):
            response = self.timing_chat(key, payload)
            data = json.loads(payload["messages"][1]["content"])
            result = json.loads(response["choices"][0]["message"]["content"])
            result["blocks"][0]["zhTemplate"] = data["targets"][0]["currentTemplate"]
            return self.response(result)
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=unchanged):
            with self.assertRaisesRegex(ValueError, "was not revised"):
                mod.repair_timing(self.out, work / "job.json", work / "synchronization/report.json", self.root / "unchanged")

    def test_timing_aware_policy_is_explicit_and_keeps_old_cache_replay(self):
        work = self.make_timing_source()
        legacy = self.root / "legacy-timing"
        self.timing_execute(self.out, work, legacy)
        self.assertNotIn("promptPolicy", mod.read(legacy / "cuv-manifest.json"))
        before = {p: p.read_bytes() for p in legacy.rglob("*.json")}
        modern = self.root / "modern-timing"
        seen = []
        def checked(key, payload):
            seen.append(payload)
            data = json.loads(payload["messages"][1]["content"])
            guidance = data["targets"][0]["timingCharacterGuidance"]
            self.assertTrue(guidance["advisoryOnly"])
            self.assertGreater(guidance["immutableScriptureChars"], 0)
            self.assertLess(guidance["suggestedNarrationChars"], guidance["currentNarrationChars"])
            if mod.REVIEW in payload["messages"][0]["content"]:
                self.assertIn(mod.TIMING_AWARE_REVIEW, payload["messages"][0]["content"])
                self.assertEqual(mod.narration_characters(data["draft"]["blocks"][0]["zhTemplate"]),
                                 data["targets"][0]["maximumFinalNarrationChars"])
            return self.timing_chat(key, payload)
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=checked):
            mod.repair_timing(self.out, work / "job.json", work / "synchronization/report.json", modern,
                              prompt_policy=mod.TIMING_AWARE_POLICY)
        self.assertEqual(2, len(seen))
        self.assertEqual(mod.TIMING_AWARE_POLICY, mod.read(modern / "cuv-manifest.json")["promptPolicy"])
        self.assertEqual(mod.TIMING_AWARE_POLICY, mod.read(modern / "report.json")["timingRevision"]["promptPolicy"])
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            mod.validate(legacy)
            mod.validate(modern)
        self.assertTrue(all(p.read_bytes() == value for p, value in before.items()))
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("frozen")):
            with self.assertRaisesRegex(ValueError, "Existing artifact differs"):
                mod.repair_timing(self.out, work / "job.json", work / "synchronization/report.json", legacy,
                                  prompt_policy=mod.TIMING_AWARE_POLICY)

    def test_timing_aware_policy_rejects_review_regrowth_while_legacy_keeps_its_contract(self):
        work = self.make_timing_source()
        def expanded(key, payload):
            response = self.timing_chat(key, payload)
            if mod.COMPACT_NARRATION in payload["messages"][0]["content"]:
                result = json.loads(response["choices"][0]["message"]["content"])
                data = json.loads(payload["messages"][1]["content"])
                result["blocks"][0]["zhTemplate"] = data["targets"][0]["currentTemplate"][2:]
                return self.response(result)
            return response
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=expanded):
            self.assertEqual("passed", mod.repair_timing(self.out, work / "job.json", work / "synchronization/report.json",
                                                        self.root / "legacy-expanded")["status"])
            with self.assertRaisesRegex(ValueError, "expanded the compact narration"):
                mod.repair_timing(self.out, work / "job.json", work / "synchronization/report.json", self.root / "modern-expanded",
                                  prompt_policy=mod.TIMING_AWARE_POLICY)
        self.assertFalse((self.root / "modern-expanded/spoken-review.json").exists())

    def test_unknown_timing_prompt_policy_fails_before_paid_work(self):
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("no API")):
            with self.assertRaisesRegex(ValueError, "Unknown timing prompt policy"):
                mod.repair_timing(self.out, self.parent, self.root / "missing-report", self.root / "unknown",
                                  prompt_policy="unrecognized-version")

    def test_timing_character_advice_uses_actual_ratio_and_never_budgets_scripture_edits(self):
        block = {"zhTemplate": "字" * 133, "quotes": []}
        guidance = mod.timing_character_guidance(block, {"naturalSeconds": 22.98}, 17.597)
        self.assertEqual(101, guidance["suggestedNarrationChars"])
        locked = {"zhTemplate": "说__CUV_LOCK_aaaaaaaaaaaaaaaaaaaaaaaa__", "quotes": [{"cuvText": "字" * 100}]}
        guidance = mod.timing_character_guidance(locked, {"naturalSeconds": 20}, 10)
        self.assertEqual(100, guidance["immutableScriptureChars"])
        self.assertEqual(0, guidance["suggestedNarrationChars"])
        self.assertTrue(guidance["advisoryOnly"])

    def reuse_run(self, **kwargs):
        old = self.out
        self.out = self.root / "translation-v2"
        second_map = self.root / "map-v2.json"
        self.mapping["revisionNote"] = "New audit metadata; unchanged source quotations"
        self.write(second_map, self.mapping)
        self.map = second_map
        return old, self.execute(reuse_from=old, **kwargs)

    def test_reuse_preserves_actual_request_and_skips_unchanged_selection(self):
        self.execute()
        old, (_, calls) = self.reuse_run()
        self.assertEqual(0, calls, "Metadata-only map revision reuses unchanged exact requests, including audit")
        cached = mod.read(next((self.out / "cache").glob("select-*.json")))
        original = mod.read(next((old / "cache").glob("select-*.json")))
        self.assertEqual(original["request"], cached["request"])
        self.assertEqual(original["response"], cached["response"])
        self.assertNotEqual(cached["request"]["identity"], cached["reusedForIdentity"])
        self.assertIn("reuseFrom", cached)
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            self.assertEqual("passed", mod.validate(self.out)["status"])

    def test_changed_selection_payload_is_not_reused(self):
        self.execute()
        self.mapping["blocks"][0]["quotes"][0]["evidence"] += "; corrected source analysis"
        _, (_, calls) = self.reuse_run()
        self.assertEqual(4, calls)
        selected = mod.read(next((self.out / "cache").glob("select-*.json")))
        self.assertNotIn("reuseFrom", selected)

    def test_changed_batch_size_reuses_only_exact_stage_requests(self):
        self.execute()
        old = self.out
        self.out = self.root / "other"
        result, calls = self.execute(reuse_from=old, batch_size=1)
        self.assertEqual("passed", result["status"])
        self.assertEqual(4, calls)
        for stage in ("select-0", "audit-quotes"):
            self.assertIn("reuseFrom", mod.read(next((self.out / "cache").glob(stage + "-*.json"))))
        for stage in ("translate-0", "review-0", "translate-1", "review-1"):
            self.assertNotIn("reuseFrom", mod.read(next((self.out / "cache").glob(stage + "-*.json"))))
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            self.assertEqual("passed", mod.validate(self.out)["status"])

    def test_parallel_batches_keep_source_order_and_offline_receipts(self):
        import threading
        self.make_source(8)
        barrier = threading.Barrier(2)
        def concurrent_chat(key, payload):
            if mod.TRANSLATE in payload["messages"][0]["content"]:
                barrier.wait(timeout=3)
            return self.fake_chat(key, payload)
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=concurrent_chat):
            result = mod.run(self.parent, self.out, reference_map_path=self.map,
                             batch_size=4, workers=2)
        self.assertEqual("passed", result["status"])
        self.assertEqual([b["id"] for b in self.blocks], [b["id"] for b in mod.read(self.out / "blocks.json")])
        with mock.patch.object(mod, "chat_json", side_effect=AssertionError("offline")):
            self.assertEqual("passed", mod.validate(self.out)["status"])

    def test_reuse_rejects_tampered_original_response(self):
        self.execute()
        cache = next((self.out / "cache").glob("select-*.json"))
        receipt = mod.read(cache)
        receipt["response"]["model"] = "tampered"
        self.write(cache, receipt)
        with self.assertRaisesRegex(ValueError, "cache hash"):
            self.reuse_run()

    def test_offline_gate_rejects_rewritten_reused_request(self):
        self.execute()
        self.reuse_run()
        cache = next((self.out / "cache").glob("select-*.json"))
        receipt = mod.read(cache)
        receipt["request"]["identity"] = receipt["reusedForIdentity"]
        receipt["requestSha256"] = mod.digest(receipt["request"])
        self.write(cache, receipt)
        with self.assertRaisesRegex(ValueError, "request/response was rewritten"):
            mod.validate(self.out)

    def failed_quote_run(self):
        self.blocks[1]["en"] = "I repeat: I am Alpha and Omega."
        self.write(self.parent, {"blocks": self.blocks})
        self.mapping["parentJobSha256"] = mod.file_hash(self.parent)
        self.mapping["blocks"][1]["quotes"] = [{**self.mapping["blocks"][0]["quotes"][0], "quoteId": "q2"}]
        self.write(self.map, self.mapping)
        original = self.fake_chat
        def failed(key, payload):
            response = original(key, payload)
            if mod.AUDIT_QUOTES in payload["messages"][0]["content"]:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["blocks"][0].update(quoteCoverage="fail", issues=[{"detail": "Selection requires repair"}],
                                           evidence="Independent finding: reconsider the selected extent")
                return self.response(result)
            return response
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), mock.patch.object(mod, "chat_json", side_effect=failed):
            with self.assertRaisesRegex(ValueError, "Independent quotation audit failed"):
                mod.run(self.parent, self.out, reference_map_path=self.map)
        return self.out

    def test_repair_context_only_changes_failed_selection_and_requires_new_audit(self):
        previous = self.failed_quote_run()
        old_audit = next((previous / "cache").glob("audit-quotes-*.json"))
        old_sha = mod.file_hash(old_audit)
        self.out = self.root / "repaired"
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=self.fake_chat) as call:
            mod.run(self.parent, self.out, reference_map_path=self.map, reuse_from=previous, repair_from=previous)
        self.assertEqual(4, call.call_count, "Only failed select + whole audit + translation/review should run")
        selections = [json.loads(c.args[1]["messages"][1]["content"]) for c in call.call_args_list
                      if mod.SELECT in c.args[1]["messages"][0]["content"]]
        self.assertEqual([0], [s["block"]["id"] for s in selections])
        repair = selections[0]["repairContext"]
        self.assertEqual("fail", repair["auditFinding"]["quoteCoverage"])
        self.assertEqual("q1", repair["previousSelection"]["quotes"][0]["quoteId"])
        self.assertEqual(old_sha, mod.file_hash(old_audit), "Original failed audit must remain unchanged")
        self.assertEqual("passed", mod.validate(self.out)["status"])

    def test_repair_rejects_tampered_audit_before_api(self):
        previous = self.failed_quote_run()
        path = next((previous / "cache").glob("audit-quotes-*.json"))
        receipt = mod.read(path)
        receipt["response"]["model"] = "tampered"
        self.write(path, receipt)
        with mock.patch.object(mod, "chat_json") as call:
            with self.assertRaisesRegex(ValueError, "cache hash"):
                mod.run(self.parent, self.root / "repaired", reference_map_path=self.map, repair_from=previous)
            call.assert_not_called()

    def test_repair_cannot_treat_passing_audit_as_failure(self):
        self.execute()
        with mock.patch.object(mod, "chat_json") as call:
            with self.assertRaisesRegex(ValueError, "no failed quotation blocks"):
                mod.run(self.parent, self.root / "repaired", reference_map_path=self.map, repair_from=self.out)
            call.assert_not_called()

    def test_automatic_discovery_uses_entire_english(self):
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), \
             mock.patch.object(mod, "chat_json", side_effect=self.fake_chat) as call:
            mod.run(self.parent, self.out)
        first = json.loads(call.call_args_list[0].args[1]["messages"][1]["content"])
        self.assertEqual([b["en"] for b in self.blocks], [b["en"] for b in first["blocks"]])

    def test_missing_key_fails_before_api_and_can_resume(self):
        with mock.patch.dict(mod.os.environ, {}, clear=True), mock.patch.object(mod, "chat_json") as call:
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                mod.run(self.parent, self.out, reference_map_path=self.map)
            call.assert_not_called()
        self.assertFalse((self.out / "spoken-review.json").exists())
        self.execute()

    def test_parent_hash_changes_rejected(self):
        self.execute()
        job = mod.read(self.parent)
        job["blocks"][0]["en"] += " Changed"
        self.write(self.parent, job)
        with self.assertRaisesRegex(ValueError, "Bound input changed"):
            mod.validate(self.out)

    def test_library_file_change_rejected_offline(self):
        library = self.root / "library.json"
        library.write_bytes(mod.DEFAULT_LIBRARY_PATH.read_bytes())
        self.execute(library=library)
        library.write_bytes(library.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "Bound input changed"):
            mod.validate(self.out)

    def test_modified_output_or_quote_cannot_pass(self):
        self.execute()
        blocks = mod.read(self.out / "blocks.json")
        blocks[0]["zh"] = blocks[0]["zh"].replace("阿拉法", "别的词")
        self.write(self.out / "blocks.json", blocks)
        with self.assertRaisesRegex(ValueError, "Bound input changed"):
            mod.validate(self.out)

    def test_cache_tamper_rejected(self):
        self.execute()
        cache = next((self.out / "cache").glob("review-*.json"))
        receipt = mod.read(cache)
        receipt["response"]["model"] = "other-model"
        self.write(cache, receipt)
        with self.assertRaisesRegex(ValueError, "cache hash"):
            mod.validate(self.out)

    def test_unresolved_independent_review_never_mints_approval(self):
        original = self.fake_chat
        def failed(key, payload):
            response = original(key, payload)
            if mod.REVIEW in payload["messages"][0]["content"]:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["blocks"][0]["checks"]["completeMeaning"] = "fail"
                return self.response(result)
            return response
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), mock.patch.object(mod, "chat_json", side_effect=failed):
            with self.assertRaisesRegex(ValueError, "Independent model review"):
                mod.run(self.parent, self.out, reference_map_path=self.map)
        self.assertFalse((self.out / "spoken-review.json").exists())
        self.assertFalse((self.out / "report.json").exists())

    def test_input_uncertainty_needs_explicit_independent_resolution(self):
        self.mapping["blocks"][0]["quotes"][0]["uncertainty"] = ["Partial verse wording"]
        self.mapping["issues"] = [{"detail": "Do not append unread clauses"}]
        self.write(self.map, self.mapping)
        self.execute()
        audit = mod.read(self.out / "report.json")["quotationAudit"]
        self.assertEqual([0, 1], [r["index"] for r in audit["resolutions"]])

    def test_missing_input_issue_resolution_blocks_approval(self):
        self.mapping["issues"] = [{"detail": "Possible missed partial quote"}]
        self.write(self.map, self.mapping)
        original = self.fake_chat
        def failed(key, payload):
            response = original(key, payload)
            if mod.AUDIT_QUOTES in payload["messages"][0]["content"]:
                result = json.loads(response["choices"][0]["message"]["content"])
                result["resolutions"] = []
                return self.response(result)
            return response
        with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), mock.patch.object(mod, "chat_json", side_effect=failed):
            with self.assertRaisesRegex(ValueError, "not explicitly resolved"):
                mod.run(self.parent, self.out, reference_map_path=self.map)
        self.assertFalse((self.out / "spoken-review.json").exists())

    def test_source_span_ambiguity_and_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            mod.exact_span("one one", {"sourceText": "one"})
        self.assertEqual((4, 7), mod.exact_span("one one", {"sourceText": "one", "start": 4, "end": 7}))
        mapping = copy.deepcopy(self.mapping)
        mapping["blocks"][0]["quotes"].append({**mapping["blocks"][0]["quotes"][0], "quoteId": "q2"})
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            mod.reference_map(mapping, self.blocks, mod.file_hash(self.parent))

    def test_wrong_reference_and_block_coverage_rejected(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["blocks"].reverse()
        with self.assertRaisesRegex(ValueError, "block IDs"):
            mod.reference_map(mapping, self.blocks, mod.file_hash(self.parent))
        self.mapping["blocks"][0]["quotes"][0]["reference"] = "REV 1:99"
        self.write(self.map, self.mapping)
        with mock.patch.object(mod, "chat_json") as call:
            with self.assertRaises(ValueError):
                mod.run(self.parent, self.out, reference_map_path=self.map)
            call.assert_not_called()

    def test_missing_duplicate_reordered_or_unknown_tokens_rejected(self):
        a, b = "__CUV_LOCK_" + "a" * 24 + "__", "__CUV_LOCK_" + "b" * 24 + "__"
        quotes = [{"token": a, "quoteId": "a", "cuvText": "甲"}, {"token": b, "quoteId": "b", "cuvText": "乙"}]
        for text in (a, a + a + b, b + a, a + b + "__CUV_LOCK_unknown__"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                mod.inject(text, quotes)

    def selected_parts(self, parts):
        mapping = copy.deepcopy(self.mapping)
        mapping["blocks"][0]["quotes"][0]["reference"] = "REV 1:17-18"
        mapping = mod.reference_map(mapping, self.blocks, mod.file_hash(self.parent))
        response = {"issues": [], "quotes": [{"quoteId": "q1", "parts": parts,
                    "evidence": "Exact source fragments", "uncertainty": []}]}
        with mock.patch.object(mod, "cached_call", return_value=(response, {"path": "mock", "sha256": "mock"})):
            result, _ = mod.selections(mapping, self.blocks, self.library, self.out, "source")
        return result[0]["quotes"][0]["cuvText"]

    def test_complete_adjacent_verses_do_not_insert_ellipsis(self):
        verses = self.library.lookup("REV 1:17-18")["verses"]
        text = self.selected_parts([{"reference": v["ref"], "text": v["text"]} for v in verses])
        self.assertEqual("".join(v["text"] for v in verses), text)

    def test_adjacent_substrings_do_not_insert_ellipsis(self):
        text = self.library.lookup("REV 1:17")["text"]
        split = text.index("他用右手")
        self.assertEqual(text, self.selected_parts([{"reference": "REV 1:17", "text": text[:split]},
                                                   {"reference": "REV 1:17", "text": text[split:]}]))

    def test_real_omission_inserts_ellipsis_and_reversal_fails(self):
        text = self.library.lookup("REV 1:17")["text"]
        first, last = text[:10], text[-10:]
        parts = [{"reference": "REV 1:17", "text": first}, {"reference": "REV 1:17", "text": last}]
        self.assertEqual(first + "……" + last, self.selected_parts(parts))
        with self.assertRaisesRegex(ValueError, "reverse"):
            self.selected_parts(parts[::-1])

    def test_changed_cuv_substring_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact unambiguous"):
            self.selected_parts([{"reference": "REV 1:17", "text": "程序不可编造的经文"}])

    def test_parent_directory_cannot_be_output(self):
        with self.assertRaisesRegex(ValueError, "outside the parent"):
            mod.run(self.parent, self.parent.parent)


    def test_new_run_distinguishes_evidence_block_from_execution_errors(self):
        original = self.fake_chat
        for kind in ("blocked", "runtime", "json"):
            with self.subTest(kind=kind):
                out = self.root / ("status-" + kind)
                def fail(key, payload):
                    if kind == "runtime":
                        raise RuntimeError("provider unavailable")
                    if kind == "json":
                        raise json.JSONDecodeError("invalid response", "?", 0)
                    response = original(key, payload)
                    if mod.SELECT in payload["messages"][0]["content"]:
                        selected = json.loads(response["choices"][0]["message"]["content"])
                        selected["issues"] = ["Unresolved source extent"]
                        return self.response(selected)
                    return response
                with mock.patch.dict(mod.os.environ, {"OPENAI_API_KEY": "test-only"}), mock.patch.object(mod, "chat_json", side_effect=fail):
                    with self.assertRaises((ValueError, RuntimeError)):
                        mod.run(self.parent, out, reference_map_path=self.map)
                self.assertEqual("blocked" if kind == "blocked" else "error", mod.read(out / "run-status.json")["status"])
                self.assertFalse((out / "spoken-review.json").exists())


if __name__ == "__main__":
    unittest.main()
