import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
from scripts import audit_portable_media as subject
from scripts import review_target_language_audio as review


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class PortableMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "machine-a"
        self.package_path = self.root / "package.json"
        self.approval_path = self.root / "approval.json"
        self.mapping_path = self.root / "mapping.json"
        self.manifest_path = self.root / "recovery.json"
        self.expectations = dict(expected_source="a" * 64, expected_locale="ko",
                                 expected_candidate="b" * 64)
        self.rows = []
        bindings = {}
        for artifact_id, filename, payload in (
            ("/units/0/audio", "audio/unit-0000.wav", b"synthetic-unit-one"),
            ("/units/1/audio", "audio/unit-0001.wav", b"synthetic-unit-two"),
            ("/track", "audio/track.wav", b"synthetic-track"),
            ("/captions", "synchronization/captions.json", b'{"targetLocale":"ko"}'),
            ("/schedule", "synchronization/schedule.json", b'{ "targetLocale": "ko", "items": [] }'),
        ):
            relative = f"languages/ko/{filename}"
            path = self.archive / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            binding = {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}
            if artifact_id == "/schedule":
                binding["jsonSha256"] = subject.json_sha256(json.loads(payload))
            bindings[artifact_id] = binding
            self.rows.append({"artifactId": artifact_id, "archiveRelativePath": relative})
        self.package = {
            "schemaVersion": "sermon-target-language-audio-package-v1",
            "packageId": "target-audio-ko-synthetic", "targetLocale": "ko",
            "englishSourcePackageJsonSha256": "a" * 64,
            "targetLanguageCandidateJsonSha256": "b" * 64,
            "targetLanguageSpeechJobJsonSha256": "c" * 64,
            "status": "human_reviewed", "ratePolicy": "natural_no_time_stretch", "voice": None,
            "units": [{"textGroupId": f"group-{i}", "targetTextSha256": "d" * 64,
                       "audio": bindings[f"/units/{i}/audio"], "durationSeconds": 1.0}
                      for i in range(2)],
            "track": bindings["/track"], "captions": bindings["/captions"],
            "schedule": bindings["/schedule"],
            "machineScreening": {"status": "pass", "model": "synthetic", "coverage": 1.0},
            "humanReview": {"status": "approved", "humanApproval": True,
                            "reviewedBy": "synthetic-reviewer", "reviewedAt": "2026-10-01T12:00:00Z",
                            "fullPlayback": "approved"}, "issues": [],
        }
        self.approval = {
            "schemaVersion": "sermon-target-language-audio-human-review-receipt-v2",
            "targetLocale": "ko", "englishSourcePackageJsonSha256": "a" * 64,
            "targetLanguageCandidateJsonSha256": "b" * 64,
            "trackSha256": bindings["/track"]["sha256"], "decision": "approved",
            "machineScreeningStatus": "pass", "machineScreeningReceiptJsonSha256": "e" * 64,
            "asrAdjudications": [], "reviewedBy": "synthetic-reviewer",
            "reviewedAt": "2026-10-01T12:00:00Z", "fullPlayback": "approved",
            "videoSync1x": "approved", "reviewedUnitIds": ["group-0", "group-1"],
            "checks": {key: "approved" for key in review.CHECKS}, "issues": [],
        }
        self.save_evidence()
        write_json(self.mapping_path, {"artifacts": self.rows})
        self.manifest = self.prepare()
        write_json(self.manifest_path, self.manifest)

    def save_evidence(self):
        self.package.pop("downstreamInvalidationKey", None)
        self.package["downstreamInvalidationKey"] = subject.json_sha256(self.package)
        self.approval["targetLanguageAudioPackageJsonSha256"] = subject.json_sha256(self.package)
        write_json(self.package_path, self.package)
        write_json(self.approval_path, self.approval)

    def prepare(self):
        return subject.prepare_manifest(self.package_path, self.approval_path,
                                        self.mapping_path, self.archive,
                                        archive_id="synthetic-week-r2", **self.expectations)

    def audit(self, root=None, **overrides):
        return subject.audit(self.package_path, self.approval_path, self.manifest_path,
                             root or self.archive, **{**self.expectations, **overrides})

    def codes(self, report):
        self.assertEqual(report["status"], "blocked")
        return [row["code"] for row in report["errors"]]

    def test_two_directory_relocation_keeps_original_bytes_and_has_no_writes(self):
        relocated = self.root / "machine-b"
        shutil.copytree(self.archive, relocated)
        shutil.rmtree(self.archive)
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with mock.patch.object(subject.os, "mkdir", side_effect=AssertionError("no writes")):
            report = self.audit(relocated)
        after = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["verifiedArtifactCount"], 5)
        self.assertTrue(report["readOnly"])
        self.assertFalse(report["releaseEligibilityEstablished"])
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertNotIn(str(self.root), json.dumps(self.manifest))
        self.assertNotIn("synthetic-reviewer", json.dumps(self.manifest))
        self.assertIn(str(self.archive), self.package_path.read_text())

    def test_manifest_is_valid_and_deterministic(self):
        schema, _ = subject.read_object(subject.SCHEMA_ROOT / f"{subject.SCHEMA}.schema.json")
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.manifest)
        self.assertEqual(self.prepare(), self.manifest)
        write_json(self.mapping_path, {"artifacts": list(reversed(self.rows))})
        self.assertEqual(self.prepare(), self.manifest)

    def test_collects_missing_and_corrupt_artifacts(self):
        (self.archive / self.rows[0]["archiveRelativePath"]).unlink()
        (self.archive / self.rows[2]["archiveRelativePath"]).write_bytes(b"corrupt")
        self.assertCountEqual(self.codes(self.audit()), ["artifact_missing", "artifact_sha256_mismatch"])
        with self.assertRaisesRegex(subject.AuditError, "archive_media_not_verified"):
            self.prepare()

    def test_empty_artifact(self):
        (self.archive / self.rows[0]["archiveRelativePath"]).write_bytes(b"")
        self.assertIn("artifact_empty", self.codes(self.audit()))

    def test_wrong_expected_source_locale_or_revision(self):
        for arguments, code in (({"expected_source": "f" * 64}, "expected_source_mismatch"),
                                ({"expected_locale": "es"}, "expected_locale_mismatch"),
                                ({"expected_candidate": "f" * 64}, "expected_revision_mismatch")):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(subject.AuditError, code):
                self.audit(**arguments)

    def test_rejects_traversal_absolute_windows_url_and_noncanonical_paths(self):
        for path in ("../outside", "/tmp/private", "languages/ko/../../outside", "languages/ko/./x",
                     "languages/ko//x", "languages/ko/x/", "languages\\ko\\x", "C:/private",
                     "https://host/x", "languages/ko/%2e%2e/x", "languages/ko/x\nsecret"):
            manifest = copy.deepcopy(self.manifest)
            manifest["artifacts"][0]["archiveRelativePath"] = path
            write_json(self.manifest_path, manifest)
            with self.subTest(path=path), self.assertRaises(subject.AuditError):
                self.audit()

    def test_rejects_wrong_locale_archive_mapping_even_when_bytes_match(self):
        shutil.copytree(self.archive / "languages/ko", self.archive / "languages/es")
        manifest = copy.deepcopy(self.manifest)
        manifest["artifacts"][0]["archiveRelativePath"] = manifest["artifacts"][0]["archiveRelativePath"].replace("/ko/", "/es/")
        write_json(self.manifest_path, manifest)
        with self.assertRaisesRegex(subject.AuditError, "archive_locale_mismatch"):
            self.audit()

    def test_rejects_file_symlink_even_inside_archive(self):
        path = self.archive / self.rows[0]["archiveRelativePath"]
        target = path.with_name("copy.wav")
        path.rename(target)
        path.symlink_to(target)
        self.assertIn("artifact_unreadable_or_symlink", self.codes(self.audit()))

    def test_rejects_intermediate_directory_symlink_outside_archive(self):
        path = self.archive / "languages/ko/audio"
        target = self.root / "outside-audio"
        path.rename(target)
        path.symlink_to(target, target_is_directory=True)
        self.assertIn("artifact_unreadable_or_symlink", self.codes(self.audit()))

    def test_rejects_root_and_root_parent_symlinks(self):
        link = self.root / "archive-link"
        link.symlink_to(self.archive, target_is_directory=True)
        parent_link = self.root / "parent-link"
        parent_link.symlink_to(self.root, target_is_directory=True)
        for path in (link, parent_link / "machine-a"):
            with self.subTest(path=path), self.assertRaisesRegex(subject.AuditError, "archive_root_unavailable_or_symlink"):
                self.audit(path)

    def test_special_file_is_rejected_without_blocking(self):
        path = self.archive / self.rows[0]["archiveRelativePath"]
        path.unlink()
        os.mkfifo(path)
        self.assertIn("artifact_not_regular", self.codes(self.audit()))

    def test_manifest_artifact_hash_cannot_override_original_package(self):
        self.manifest["artifacts"][0]["sha256"] = "f" * 64
        write_json(self.manifest_path, self.manifest)
        with self.assertRaisesRegex(subject.AuditError, "artifact_identity_mismatch"):
            self.audit()

    def test_original_package_byte_change_is_rejected_even_with_same_json(self):
        self.package_path.write_text(json.dumps(self.package))
        with self.assertRaisesRegex(subject.AuditError, "original_package_hash_mismatch"):
            self.audit()

    def test_approval_byte_change_is_rejected_even_with_same_json(self):
        self.approval_path.write_text(json.dumps(self.approval))
        with self.assertRaisesRegex(subject.AuditError, "approval_receipt_hash_mismatch"):
            self.audit()

    def test_changed_package_invalidates_approval(self):
        self.package["targetLanguageSpeechJobJsonSha256"] = "f" * 64
        self.package.pop("downstreamInvalidationKey")
        self.package["downstreamInvalidationKey"] = subject.json_sha256(self.package)
        write_json(self.package_path, self.package)
        with self.assertRaisesRegex(subject.AuditError, "approval_package_mismatch"):
            self.audit()

    def test_invalid_derived_package_identity(self):
        self.package["downstreamInvalidationKey"] = "f" * 64
        write_json(self.package_path, self.package)
        with self.assertRaisesRegex(subject.AuditError, "package_identity_mismatch"):
            self.audit()

    def test_manifest_source_identity_mismatch(self):
        self.manifest["identity"]["englishSourcePackageJsonSha256"] = "f" * 64
        write_json(self.manifest_path, self.manifest)
        with self.assertRaisesRegex(subject.AuditError, "manifest_identity_mismatch"):
            self.audit()

    def test_approval_locale_and_coverage_mismatch(self):
        for key, value, code in (("targetLocale", "es", "approval_identity_mismatch"),
                                 ("reviewedUnitIds", ["group-0"], "approval_unit_mismatch"),
                                 ("reviewedBy", "someone-else", "approval_review_mismatch"),
                                 ("machineScreeningStatus", "requires_review", "approval_screening_mismatch")):
            approval = {**self.approval, key: value}
            write_json(self.approval_path, approval)
            with self.subTest(key=key), self.assertRaisesRegex(subject.AuditError, code):
                self.audit()

    def test_nonapproved_package_fails(self):
        self.package["status"] = "candidate"
        self.save_evidence()
        with self.assertRaisesRegex(subject.AuditError, "package_not_human_reviewed"):
            self.prepare()

    def test_legacy_v1_receipt_supported_without_relabeling(self):
        self.approval["schemaVersion"] = "sermon-target-language-audio-human-review-receipt-v1"
        for key in ("machineScreeningStatus", "machineScreeningReceiptJsonSha256", "asrAdjudications"):
            del self.approval[key]
        self.save_evidence()
        write_json(self.manifest_path, self.prepare())
        self.assertEqual(self.audit()["status"], "verified")

    def test_duplicate_missing_and_unknown_artifact_mappings(self):
        cases = ((self.rows + [self.rows[0]], "mapping_ambiguous_artifact"),
                 (self.rows[:-1], "mapping_incomplete"),
                 (self.rows + [{"artifactId": "/secret", "archiveRelativePath": "languages/ko/x"}],
                  "mapping_unknown_artifact"))
        for rows, code in cases:
            write_json(self.mapping_path, {"artifacts": rows})
            with self.subTest(code=code), self.assertRaisesRegex(subject.AuditError, code):
                self.prepare()

    def test_duplicate_path_mapping_and_hardlink_alias_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[1]["archiveRelativePath"] = rows[0]["archiveRelativePath"]
        write_json(self.mapping_path, {"artifacts": rows})
        with self.assertRaisesRegex(subject.AuditError, "mapping_ambiguous_path"):
            self.prepare()
        second = self.archive / self.rows[1]["archiveRelativePath"]
        second.unlink()
        os.link(self.archive / self.rows[0]["archiveRelativePath"], second)
        self.assertIn("mapping_ambiguous_file", self.codes(self.audit()))

    def test_identical_basename_elsewhere_never_guessed(self):
        extra = self.archive / "another-revision/languages/ko/audio/track.wav"
        extra.parent.mkdir(parents=True)
        shutil.copyfile(self.archive / self.rows[2]["archiveRelativePath"], extra)
        self.assertEqual(self.audit()["status"], "verified")
        (self.archive / self.rows[2]["archiveRelativePath"]).unlink()
        self.assertIn("artifact_missing", self.codes(self.audit()))

    def test_json_hash_verified_independently_from_bytes(self):
        self.package["schedule"]["jsonSha256"] = "f" * 64
        self.save_evidence()
        self.manifest["originalPackage"] = subject.read_object(self.package_path)[1]
        self.manifest["approvalReceipt"] = subject.read_object(self.approval_path)[1]
        self.manifest["identity"] = {key: self.package[key] for key in subject.IDENTITY_KEYS}
        next(row for row in self.manifest["artifacts"] if row["artifactId"] == "/schedule")["jsonSha256"] = "f" * 64
        write_json(self.manifest_path, self.manifest)
        self.assertIn("artifact_json_sha256_mismatch", self.codes(self.audit()))

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'[]', b'\xff'):
            with self.subTest(data=data), self.assertRaises(subject.AuditError):
                subject.parse_object(data)

    def test_json_inputs_reject_fifo_and_symlink_without_blocking(self):
        for path in (self.package_path, self.approval_path, self.mapping_path, self.manifest_path):
            original = path.read_bytes()
            target = path.with_name(path.name + ".target")
            target.write_bytes(original)
            path.unlink()
            path.symlink_to(target)
            with self.subTest(path=path, kind="symlink"), self.assertRaises(subject.AuditError):
                subject.read_object(path)
            path.unlink()
            os.mkfifo(path)
            with self.subTest(path=path, kind="fifo"), self.assertRaisesRegex(subject.AuditError, "not_regular_json"):
                subject.read_object(path)
            path.unlink()
            path.write_bytes(original)

    def test_malformed_version_and_surrogate_have_redacted_cli_errors(self):
        args = self.cli_args("audit") + ["--manifest", str(self.manifest_path)]
        for payload in (json.dumps({**self.approval, "schemaVersion": []}),
                        '{"x":1e400}', '{"x":"\\ud800"}'):
            self.approval_path.write_text(payload)
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                result = subject.main(args)
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(captured.getvalue())["status"], "blocked")
            self.assertNotIn(str(self.root), captured.getvalue())

    def cli_args(self, command):
        return [command, "--package", str(self.package_path), "--approval", str(self.approval_path),
                "--archive-root", str(self.archive), "--expected-source-sha256", "a" * 64,
                "--expected-locale", "ko", "--expected-candidate-sha256", "b" * 64]

    def test_cli_audit_subprocess_pass_and_redacted_failure(self):
        script = Path(subject.__file__)
        args = self.cli_args("audit") + ["--manifest", str(self.manifest_path)]
        result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "verified")
        self.manifest["artifacts"][0]["archiveRelativePath"] = "/private/SECRET-HOST-PATH"
        write_json(self.manifest_path, self.manifest)
        result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")
        self.assertNotIn("SECRET", result.stdout + result.stderr)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_prepare_cli_exclusive_output_preserves_package_and_approval(self):
        args = self.cli_args("prepare") + ["--mapping", str(self.mapping_path),
                                         "--archive-id", "synthetic-week-r2"]
        before = self.package_path.read_bytes(), self.approval_path.read_bytes()
        for output in (self.package_path, self.approval_path, self.manifest_path):
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                code = subject.main(args + ["--out", str(output)])
            self.assertEqual(code, 1)
            self.assertIn("sidecar_output_unavailable_or_exists", captured.getvalue())
        self.assertEqual(before, (self.package_path.read_bytes(), self.approval_path.read_bytes()))
        output = self.root / "new-sidecar.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(subject.main(args + ["--out", str(output)]), 0)
        self.assertEqual(subject.read_object(output)[0], self.manifest)

    def test_real_package_builder_and_review_producer_relocate(self):
        from tests.test_build_target_language_audio_package import AudioPackageTests
        fixture = AudioPackageTests("test_builds_machine_screened_package_but_never_human_approved")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        package = fixture.build()
        screening = json.loads((fixture.asset_root / fixture.manifest["machineScreeningReceipt"]["path"]).read_text())
        worksheet = review.prepare(package, screening)
        worksheet.update(decision="approved", reviewedBy="synthetic-reviewer",
                         reviewedAt="2026-10-01T12:00:00Z", fullPlayback="approved",
                         videoSync1x="approved", checks={key: "approved" for key in review.CHECKS})
        package, approval = review.approve(package, screening, worksheet)
        write_json(self.package_path, package)
        write_json(self.approval_path, approval)
        rows = [{"artifactId": key, "archiveRelativePath": str(Path(binding["path"]).relative_to(fixture.asset_root))}
                for key, binding in subject.artifact_bindings(package).items()]
        write_json(self.mapping_path, {"artifacts": rows})
        expected = dict(expected_source=package["englishSourcePackageJsonSha256"], expected_locale="ko",
                        expected_candidate=package["targetLanguageCandidateJsonSha256"])
        manifest = subject.prepare_manifest(self.package_path, self.approval_path, self.mapping_path,
                                            fixture.asset_root, archive_id="real-producer-synthetic-media", **expected)
        write_json(self.manifest_path, manifest)
        relocated = self.root / "producer-relocated"
        shutil.copytree(fixture.asset_root / "languages", relocated / "languages")
        shutil.rmtree(fixture.asset_root / "languages")
        report = subject.audit(self.package_path, self.approval_path, self.manifest_path, relocated, **expected)
        self.assertEqual(report["status"], "verified")


if __name__ == "__main__":
    unittest.main()
