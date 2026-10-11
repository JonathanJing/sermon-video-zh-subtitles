import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import build_listening_sample as subject
from scripts import sermon_sentence_interpretation as identity


def fixtures(count=30):
    groups = [{"translationGroupId": f"translation-chunk-0000-u{i:03d}", "sourceUnitIds": [f"chunk-0000-u{i:03d}"],
               "targetText": f"译文第{i}句。"} for i in range(1, count + 1)]
    candidate = {"schemaVersion": "sermon-target-language-candidate-v1", "targetLocale": "zh-Hans", "groups": groups}
    units = [{"textGroupId": g["translationGroupId"], "durationSeconds": 2.0 + i,
              "targetTextSha256": hashlib.sha256(g["targetText"].encode()).hexdigest(),
              "audio": {"path": f"/run/audio/unit-{i:04d}.wav", "sha256": hashlib.sha256(f"wav{i}".encode()).hexdigest()}}
             for i, g in enumerate(groups)]
    package = {"schemaVersion": "sermon-target-language-audio-package-v1", "packageId": "p-zh", "targetLocale": "zh-Hans",
               "targetLanguageCandidateJsonSha256": identity.json_sha256(candidate), "units": units}
    anchors = {"schemaVersion": "sermon-sentence-anchor-manifest-v2",
               "translationRequests": [{"translationGroupId": g["translationGroupId"], "targetEnglish": f"English {i}."}
                                       for i, g in enumerate(groups, 1)]}
    qc = {"schemaVersion": "sermon-target-audio-auto-qc-v1", "results": [
        {"groupId": groups[4]["translationGroupId"], "status": "fail", "issues": ["asr_mismatch_confirmed"]},
        {"groupId": groups[7]["translationGroupId"], "status": "pass", "issues": []}]}
    screening = {"schemaVersion": "sermon-target-language-audio-screening-v2", "units": [
        {"textGroupId": groups[9]["translationGroupId"], "status": "requires_review"},
        {"textGroupId": groups[4]["translationGroupId"], "status": "requires_review"}]}
    return package, candidate, anchors, qc, screening


class ListeningSampleTests(unittest.TestCase):
    def test_flagged_units_always_appear_and_the_rest_is_a_seeded_sample(self):
        package, candidate, anchors, qc, screening = fixtures()
        sample = subject.build(package, candidate, anchors=anchors, receipts=[qc, screening], sample_size=10,
                               now=lambda: "2026-10-13T09:00:00+00:00")
        flagged = [row for row in sample["rows"] if row["reason"] == "flagged"]
        self.assertEqual([row["groupId"][-4:] for row in flagged], ["u005", "u010"])
        self.assertEqual(flagged[0]["flags"], ["fail: asr_mismatch_confirmed", "requires_review"])
        self.assertEqual(sum(row["reason"] == "random" for row in sample["rows"]), 10)
        self.assertEqual(sample["flaggedCount"], 2)
        self.assertEqual([row["index"] for row in sample["rows"]], sorted(row["index"] for row in sample["rows"]))
        self.assertEqual(sample["rows"][0]["english"][:7], "English")
        again = subject.build(package, candidate, anchors=anchors, receipts=[qc, screening], sample_size=10)
        self.assertEqual([r["groupId"] for r in again["rows"]], [r["groupId"] for r in sample["rows"]])
        other = subject.build(package, candidate, anchors=anchors, receipts=[qc, screening], sample_size=10, seed="other")
        self.assertNotEqual([r["groupId"] for r in other["rows"]], [r["groupId"] for r in sample["rows"]])
        self.assertEqual(sample["anchorManifestJsonSha256"], identity.json_sha256(anchors))
        self.assertFalse(sample["humanApproval"])

    def test_bindings_are_checked(self):
        package, candidate, anchors, qc, _ = fixtures()
        wrong = {**candidate, "groups": [dict(candidate["groups"][0], targetText="改了"), *candidate["groups"][1:]]}
        with self.assertRaisesRegex(ValueError, "not the one the audio package"):
            subject.build(package, wrong)
        tampered = json.loads(json.dumps(package))
        tampered["units"][0]["targetTextSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "text differs from the candidate group"):
            subject.build(tampered, candidate)
        with self.assertRaisesRegex(ValueError, "sample size"):
            subject.build(package, candidate, sample_size=99)

    def test_markdown_sheet_and_cli(self):
        package, candidate, anchors, qc, screening = fixtures()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for name, value in (("package", package), ("candidate", candidate), ("anchors", anchors), ("qc", qc), ("screening", screening)):
                paths[name] = root / f"{name}.json"
                paths[name].write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            out = root / "sheet"
            code = subject.main(["--audio-package", str(paths["package"]), "--candidate", str(paths["candidate"]),
                                 "--anchors", str(paths["anchors"]), "--audio-qc", str(paths["qc"]),
                                 "--screening", str(paths["screening"]), "--sample-size", "5", "--out", str(out)])
            self.assertEqual(code, 0)
            sheet = (out / "listening-sample.md").read_text(encoding="utf-8")
            manifest = json.loads((out / "listening-sample.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schemaVersion"], subject.SCHEMA)
            self.assertEqual(len(manifest["rows"]), 7)
            self.assertEqual(sheet.count("| [ ] |"), 7)
            self.assertIn("机器标记：fail: asr_mismatch_confirmed；requires_review", sheet)
            self.assertIn("`/run/audio/unit-0004.wav`", sheet)
            with self.assertRaises(SystemExit):
                subject.main(["--audio-package", str(paths["package"]), "--candidate", str(paths["candidate"]), "--out", str(out)])


if __name__ == "__main__":
    unittest.main()
