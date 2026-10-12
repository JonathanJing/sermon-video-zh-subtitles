import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import build_listening_sample as subject
from scripts import sermon_sentence_interpretation as identity


def fixtures(root: Path, count=30, *, screening_flags=(9, 4), qc_fail=4):
    """A candidate, its anchor manifest, a package with real unit files, its screening receipt and one audio QC entry."""
    groups = [{"translationGroupId": f"translation-chunk-0000-u{i:03d}", "sourceUnitIds": [f"chunk-0000-u{i:03d}"],
               "targetText": f"译文第{i}句。"} for i in range(1, count + 1)]
    anchors = {"schemaVersion": "sermon-sentence-anchor-manifest-v2",
               "translationRequests": [{"translationGroupId": g["translationGroupId"], "targetEnglish": f"English {i}."}
                                       for i, g in enumerate(groups, 1)]}
    candidate = {"schemaVersion": "sermon-target-language-candidate-v2", "targetLocale": "zh-Hans", "groups": groups,
                 "anchorManifestSha256": identity.json_sha256(anchors)}
    audio = root / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    units = []
    for i, g in enumerate(groups):
        path = audio / f"unit-{i:04d}.wav"
        path.write_bytes(f"RIFF wav {i}".encode())
        units.append({"textGroupId": g["translationGroupId"], "durationSeconds": 2.0 + i,
                      "targetTextSha256": hashlib.sha256(g["targetText"].encode()).hexdigest(),
                      "audio": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}})
    package = {"schemaVersion": "sermon-target-language-audio-package-v1", "packageId": "p-zh", "targetLocale": "zh-Hans",
               "targetLanguageCandidateJsonSha256": identity.json_sha256(candidate),
               "targetLanguageSpeechJobJsonSha256": "5" * 64, "track": {"path": "track.mp3", "sha256": "7" * 64},
               "units": units}
    screening = {"schemaVersion": "sermon-target-language-audio-screening-v2", "targetLocale": "zh-Hans",
                 "targetLanguageSpeechJobJsonSha256": "5" * 64, "trackSha256": "7" * 64,
                 "unitAudioSha256s": [u["audio"]["sha256"] for u in units],
                 "results": [{"textGroupId": u["textGroupId"], "targetTextSha256": u["targetTextSha256"],
                              "audioSha256": u["audio"]["sha256"],
                              "status": "requires_review" if i in screening_flags else "pass"} for i, u in enumerate(units)]}
    # Audio QC passes u010, which the screening flagged; it fails u005.
    qc = {"schemaVersion": "sermon-target-audio-auto-qc-v1", "locale": "zh-Hans", "results": [
        {"groupId": u["textGroupId"], "status": "fail" if i == qc_fail else "pass",
         "issues": ["asr_mismatch_confirmed"] if i == qc_fail else [], "audioSha256": u["audio"]["sha256"],
         "textSha256": u["targetTextSha256"]} for i, u in enumerate(units)]}
    return package, candidate, anchors, screening, qc


class ListeningSampleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.package, self.candidate, self.anchors, self.screening, self.qc = fixtures(self.root)

    def build(self, package=None, candidate=None, **changes):
        arguments = dict(anchors=self.anchors, screening=self.screening, audio_qc=[self.qc], sample_size=10,
                         now=lambda: "2026-10-13T09:00:00+00:00")
        arguments.update(changes)
        return subject.build(package or self.package, candidate or self.candidate, **arguments)

    def test_every_unit_any_check_flagged_appears_and_the_rest_is_a_seeded_sample(self):
        sample = self.build()
        flagged = [row for row in sample["rows"] if row["reason"] == "flagged"]
        # u010 was flagged by the screening and passed by audio QC: it stays on the sheet (review finding).
        self.assertEqual([row["groupId"][-4:] for row in flagged], ["u005", "u010"])
        self.assertEqual(flagged[0]["flags"], ["requires_review", "fail: asr_mismatch_confirmed"])
        self.assertEqual(flagged[1]["flags"], ["requires_review"])
        self.assertEqual(sum(row["reason"] == "random" for row in sample["rows"]), 10)
        self.assertEqual((sample["sampleSize"], sample["sampleSizeRequested"], sample["flaggedCount"]), (10, 10, 2))
        self.assertEqual([row["index"] for row in sample["rows"]], sorted(row["index"] for row in sample["rows"]))
        self.assertEqual(sample["rows"][0]["english"][:7], "English")
        again = self.build(now=lambda: "later")
        self.assertEqual([r["groupId"] for r in again["rows"]], [r["groupId"] for r in sample["rows"]])
        other = self.build(seed="other")
        self.assertNotEqual([r["groupId"] for r in other["rows"]], [r["groupId"] for r in sample["rows"]])
        self.assertEqual((sample["anchorManifestJsonSha256"], sample["screeningReceiptJsonSha256"],
                          sample["audioQcReceiptJsonSha256s"]),
                         (identity.json_sha256(self.anchors), identity.json_sha256(self.screening), [identity.json_sha256(self.qc)]))
        self.assertTrue(sample["audioBytesVerified"])
        self.assertFalse(sample["humanApproval"])

    def test_the_screening_receipt_must_be_this_packages(self):
        cases = {"another speech job": ("targetLanguageSpeechJobJsonSha256", "6" * 64, "another speech job"),
                 "another locale": ("targetLocale", "ko", "another locale"),
                 "another track": ("trackSha256", "8" * 64, "another track"),
                 "other unit audio": ("unitAudioSha256s", ["0" * 64] * 30, "unit audio differs"),
                 "not a screening": ("schemaVersion", "sermon-target-audio-auto-qc-v1", "not an ASR screening")}
        for name, (key, value, message) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, message):
                self.build(screening=dict(self.screening, **{key: value}))
        short = dict(self.screening, results=self.screening["results"][:-1])
        with self.assertRaisesRegex(ValueError, "does not cover every unit"):
            self.build(screening=short)
        swapped = copy.deepcopy(self.screening)
        swapped["results"][3]["targetTextSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "row for translation-chunk-0000-u004 names other text"):
            self.build(screening=swapped)

    def test_an_audio_qc_receipt_must_cover_this_package_exactly(self):
        stale = copy.deepcopy(self.qc)
        stale["results"][4]["audioSha256"] = "0" * 64  # QC of an earlier render
        with self.assertRaisesRegex(ValueError, "checked other audio or text for translation-chunk-0000-u005"):
            self.build(audio_qc=[stale])
        with self.assertRaisesRegex(ValueError, "another locale"):
            self.build(audio_qc=[dict(self.qc, locale="ko")])
        # Review finding: a truncated or partial receipt let a failed unit drop off the sheet.
        without_failure = dict(self.qc, results=[row for row in self.qc["results"] if row["status"] == "pass"])
        with self.assertRaisesRegex(ValueError, "does not cover every unit"):
            self.build(audio_qc=[without_failure])
        reordered = dict(self.qc, results=[self.qc["results"][1], self.qc["results"][0], *self.qc["results"][2:]])
        with self.assertRaisesRegex(ValueError, "does not list translation-chunk-0000-u001 in package order"):
            self.build(audio_qc=[reordered])
        with self.assertRaisesRegex(ValueError, "is not sermon-target-audio-auto-qc-v1"):
            self.build(audio_qc=[dict(self.qc, schemaVersion="sermon-target-language-audio-screening-v2")])

    def test_the_anchor_manifest_must_be_the_one_the_candidate_names(self):
        # Review finding: another run's manifest with reused group IDs showed the wrong English.
        other = copy.deepcopy(self.anchors)
        other["translationRequests"][0]["targetEnglish"] = "Some other sermon."
        with self.assertRaisesRegex(ValueError, "not the one the candidate was translated from"):
            self.build(anchors=other)

    def test_every_listed_units_audio_must_still_match_the_package(self):
        # Review finding: the sheet named the package hash while the operator heard replaced bytes.
        flagged_unit = Path(self.package["units"][4]["audio"]["path"])
        flagged_unit.write_bytes(b"replaced after assembly")
        with self.assertRaisesRegex(ValueError, "u005 audio at .* no longer matches the package"):
            self.build()
        flagged_unit.unlink()
        with self.assertRaisesRegex(ValueError, "u005 audio .* is missing"):
            self.build()

    def test_the_manifest_reports_how_many_units_were_actually_sampled(self):
        # Review finding: 12 units with 5 flagged sampled 7 but claimed 10.
        root = self.root / "small"
        package, candidate, anchors, screening, qc = fixtures(root, count=12, screening_flags=(0, 1, 2, 3, 4), qc_fail=4)
        sample = subject.build(package, candidate, anchors=anchors, screening=screening, audio_qc=[qc], sample_size=10)
        self.assertEqual((sample["sampleSizeRequested"], sample["sampleSize"], sample["unflaggedCount"]), (10, 7, 7))
        self.assertEqual(len(sample["rows"]), 12)
        self.assertIn("另随机抽 7 句（请求 10 句，未标记的只有 7 句）", subject.markdown(sample))
        with self.assertRaisesRegex(ValueError, "non-negative"):
            subject.build(package, candidate, anchors=anchors, screening=screening, sample_size=-1)

    def test_text_bindings_are_checked(self):
        wrong = {**self.candidate, "groups": [dict(self.candidate["groups"][0], targetText="改了"), *self.candidate["groups"][1:]]}
        with self.assertRaisesRegex(ValueError, "not the one the audio package"):
            self.build(candidate=wrong)
        tampered = copy.deepcopy(self.package)
        tampered["units"][0]["targetTextSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "text differs from the candidate group"):
            self.build(package=tampered)


class SheetAndVerdictTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.paths = {}
        for name, value in zip(("package", "candidate", "anchors", "screening", "qc"), fixtures(self.root)):
            self.paths[name] = self.root / f"{name}.json"
            self.paths[name].write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        self.out = self.root / "sheet"

    def cli(self, *extra):
        return subject.main(["build", "--audio-package", str(self.paths["package"]), "--candidate", str(self.paths["candidate"]),
                             "--anchors", str(self.paths["anchors"]), "--screening", str(self.paths["screening"]),
                             "--audio-qc", str(self.paths["qc"]), "--out", str(self.out), *extra])

    def fill(self, answer):
        sheet = self.out / subject.SHEET
        lines = sheet.read_text(encoding="utf-8").splitlines()
        filled, number = [], 0
        for line in lines:
            if line.endswith("| [ ] |"):
                number += 1
                line = line[: -len("[ ] |")] + answer(number) + " |"
            filled.append(line)
        sheet.write_text("\n".join(filled) + "\n", encoding="utf-8")

    def test_sheet_lists_rows_and_points_at_the_verdict_command(self):
        self.assertEqual(self.cli("--sample-size", "5"), 0)
        sheet = (self.out / subject.SHEET).read_text(encoding="utf-8")
        manifest = json.loads((self.out / subject.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], subject.SCHEMA)
        self.assertEqual(len(manifest["rows"]), 7)
        self.assertEqual(sheet.count("| [ ] |"), 7)
        self.assertIn("机器标记：requires_review；fail: asr_mismatch_confirmed", sheet)
        self.assertIn("build_listening_sample.py verdicts --sheet-dir", sheet)
        self.assertIn(f"--governs `{self.paths['package']}`", sheet)
        with self.assertRaises(SystemExit):
            self.cli()  # the output directory exists
        with self.assertRaises(SystemExit):  # the screening receipt is required
            subject.main(["build", "--audio-package", str(self.paths["package"]), "--candidate", str(self.paths["candidate"]),
                          "--anchors", str(self.paths["anchors"]), "--out", str(self.root / "other")])

    def test_verdicts_bind_the_filled_sheet_and_need_every_row(self):
        # Review finding: verdicts typed into the Markdown never reached the recorded JSON.
        self.assertEqual(self.cli("--sample-size", "5"), 0)
        numbers = [row["index"] + 1 for row in json.loads((self.out / subject.MANIFEST).read_text(encoding="utf-8"))["rows"]]
        with self.assertRaisesRegex(ValueError, "Rows without a verdict: " + ", ".join(map(str, numbers)) + " "):
            subject.verdicts(self.out)  # numbered as the sheet's 序 column
        self.fill(lambda n: "问题：第二句尾音被截" if n == 2 else "通过")
        self.assertEqual(subject.main(["verdicts", "--sheet-dir", str(self.out)]), 0)
        result = json.loads((self.out / subject.VERDICTS).read_text(encoding="utf-8"))
        manifest = json.loads((self.out / subject.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(result["counts"], {"pass": 6, "issue": 1})
        self.assertEqual(result["rows"][1]["note"], "第二句尾音被截")
        self.assertEqual(result["sampleJsonSha256"], identity.json_sha256(manifest))
        self.assertEqual(result["sheetSha256"], hashlib.sha256((self.out / subject.SHEET).read_bytes()).hexdigest())
        self.assertEqual(result["audioPackageJsonSha256"], manifest["audioPackageJsonSha256"])
        self.assertFalse(result["humanApproval"])

    def test_a_sheet_whose_rows_were_edited_is_refused(self):
        self.assertEqual(self.cli("--sample-size", "5"), 0)
        self.fill(lambda n: "pass")
        sheet = self.out / subject.SHEET
        text = sheet.read_text(encoding="utf-8")
        first_group = json.loads((self.out / subject.MANIFEST).read_text(encoding="utf-8"))["rows"][0]["groupId"]
        sheet.write_text(text.replace(f"`{first_group}`", "`translation-chunk-9999-u999`", 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "is not a row of this sample"):
            subject.verdicts(self.out)
        sheet.write_text("\n".join(line for line in text.splitlines() if f"`{first_group}`" not in line) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "lost rows"):
            subject.verdicts(self.out)

    def test_only_the_verdict_cell_may_change(self):
        # Review finding: an edited translation, English, audio path, duration or source cell was accepted.
        self.assertEqual(self.cli("--sample-size", "5"), 0)
        self.fill(lambda n: "通过")
        sheet = self.out / subject.SHEET
        text = sheet.read_text(encoding="utf-8")
        row = json.loads((self.out / subject.MANIFEST).read_text(encoding="utf-8"))["rows"][0]
        number = row["index"] + 1
        line = next(line for line in text.splitlines() if f"`{row['groupId']}`" in line)
        cells = subject.row_cells(row)
        edits = {"译文": (cells[2], "改过的译文"), "英文": (cells[3], "Other English."), "音频": (cells[4], "`/elsewhere/unit.wav`"),
                 "秒": (f"| {cells[5]} |", "| 9.9 |"), "来源": (f"| {cells[6]} |", "| 其他 |")}
        for column, (before, after) in edits.items():
            with self.subTest(column):
                sheet.write_text(text.replace(line, line.replace(before, after, 1)), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, f"Sheet row {number} changed {column}; only the verdict"):
                    subject.verdicts(self.out)
        sheet.write_text(text.replace("| 通过 |", "| 问题：前半 | 后半 |", 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, f"Sheet row {number} has 9 cells"):
            subject.verdicts(self.out)
        sheet.write_text(text.replace("| 通过 |", "| 问题：前半 \\| 后半 |", 1), encoding="utf-8")
        self.assertEqual(subject.verdicts(self.out)["rows"][0]["note"], "前半 \\| 后半")


if __name__ == "__main__":
    unittest.main()
