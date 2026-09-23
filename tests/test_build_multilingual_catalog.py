import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_multilingual_catalog", ROOT / "scripts" / "build_multilingual_catalog.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class BuildMultilingualCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.hash_a = "a" * 64
        self.hash_b = "b" * 64
        self.source_hash = "c" * 64

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded(value))
        return path

    def candidate(self, locale):
        return {
            "schemaVersion": "sermon-target-language-candidate-v2",
            "sourceLocale": "en",
            "targetLocale": locale,
            "englishSourcePackageJsonSha256": self.source_hash,
            "anchorManifestSha256": self.hash_a,
            "translationPolicySha256": self.hash_b,
            "status": "human_translation_approved",
            "releaseEligible": False,
            "generation": {
                "translator": {"model": "fixture", "promptVersion": "v1", "requestIds": ["req-1"]},
                "reviewer": {"model": "fixture", "promptVersion": "v1", "requestIds": ["req-2"]},
            },
            "groups": [{
                "translationGroupId": "group-1",
                "sourceUnitIds": ["unit-1"],
                "targetUtterances": [f"{locale} fixture"],
                "targetText": f"{locale} fixture",
                "coverage": [{"sourceUnitId": "unit-1", "targetText": f"{locale} fixture"}],
                "semanticReview": {
                    "status": "pass",
                    "checks": {"completeMeaning": "pass", "negationsNumbersNames": "pass",
                               "quotationAttribution": "pass", "noAddedMeaning": "pass"},
                    "evidence": "synthetic unit test", "uncertainty": [], "issues": [],
                },
                "languageReview": {
                    "status": "pass", "pluginId": f"fixture-{locale}", "policySha256": self.hash_a,
                    "checks": [{"checkId": "fixture", "status": "pass", "evidence": "synthetic unit test"}],
                },
            }],
            "modelReview": {"status": "pass", "reviewedGroupIds": ["group-1"]},
            "humanReview": {"translation": "approved", "reviewer": "test-fixture",
                            "reviewedAt": "2026-09-21T00:00:00Z", "reviewedGroupIds": ["group-1"]},
        }

    def release(self, locale, candidate_hash):
        return {
            "schemaVersion": "sermon-target-language-release-package-v1",
            "packageId": f"page-1-{locale}", "pageId": "page-1", "sourceLocale": "en",
            "targetLocale": locale, "targetLanguageCandidateJsonSha256": candidate_hash,
            "targetLanguageAudioPackageJsonSha256": None,
            "status": "published_http_verified", "contentStatus": "human_reviewed",
            "audioStatus": "unavailable", "interfaceLocale": locale, "contentLocale": locale,
            "audioLocale": None,
            "assets": [{"role": "page", "path": f"/pages/page-1/{locale}/index.html", "sha256": self.hash_a}],
            "httpVerification": {"status": "pass", "evidenceSha256": self.hash_b},
            "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
            "venueAcceptance": {"status": "not_run", "evidenceSha256": None},
            "issues": [],
        }

    def audio_unavailable_package(self, locale, candidate_hash):
        return {
            "schemaVersion": "sermon-target-language-audio-package-v1",
            "packageId": f"audio-unavailable-{locale}",
            "englishSourcePackageJsonSha256": self.source_hash,
            "targetLanguageCandidateJsonSha256": candidate_hash,
            "targetLanguageSpeechJobJsonSha256": self.hash_a,
            "targetLocale": locale, "status": "audio_unavailable",
            "ratePolicy": "natural_no_time_stretch", "voice": None,
            "units": [], "track": None, "captions": None, "schedule": None,
            "machineScreening": {"status": "not_run", "model": None, "coverage": 0},
            "humanReview": {"status": "pending", "humanApproval": False,
                            "reviewedBy": None, "reviewedAt": None, "fullPlayback": "pending"},
            "issues": ["voice_unavailable"], "downstreamInvalidationKey": self.hash_b,
        }

    def arguments(self, candidates, releases, *, audio_packages=(), allow_legacy=True,
                  default_target="zh-Hans"):
        return MODULE.parse_args([
            *sum((["--candidate", str(path)] for path in candidates), []),
            *sum((["--release", str(path)] for path in releases), []),
            *sum((["--audio-package", str(path)] for path in audio_packages), []),
            *(["--allow-legacy-null-audio"] if allow_legacy else []),
            "--page-date", "page-1=2026-09-21", "--default-target", f"page-1={default_target}",
            "--default-page", "page-1", "--generated-at", "2026-09-21T00:00:00Z",
            "--out", str(self.root / "multilingual.json"), "--report", str(self.root / "report.json"),
        ])

    def test_builds_two_locale_catalog_and_derives_capabilities(self):
        candidate_paths, release_paths = [], []
        for locale in ("zh-Hans", "ko"):
            candidate_path = self.write(f"candidate-{locale}.json", self.candidate(locale))
            candidate_paths.append(candidate_path)
            release_paths.append(self.write(f"release-{locale}.json", self.release(locale, digest(candidate_path.read_bytes()))))
        catalog, report = MODULE.build(self.arguments(candidate_paths, release_paths))
        self.assertEqual(list(catalog["pages"][0]["targets"]), ["ko", "zh-Hans"])
        self.assertEqual(catalog["pages"][0]["targets"]["ko"]["capabilities"], ["text"])
        self.assertEqual(report["targetCount"], 2)
        schema = json.loads((ROOT / "schemas" / "sermon-multilingual-catalog-v2.schema.json").read_text())
        self.assertEqual(list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(catalog)), [])

    def test_rejects_mixed_source_identity(self):
        zh = self.write("candidate-zh.json", self.candidate("zh-Hans"))
        ko_value = self.candidate("ko")
        ko_value["englishSourcePackageJsonSha256"] = "d" * 64
        ko = self.write("candidate-ko.json", ko_value)
        releases = [
            self.write("release-zh.json", self.release("zh-Hans", digest(zh.read_bytes()))),
            self.write("release-ko.json", self.release("ko", digest(ko.read_bytes()))),
        ]
        with self.assertRaisesRegex(MODULE.CatalogBuildError, "source identity"):
            MODULE.build(self.arguments([zh, ko], releases))

    def test_rejects_audio_asset_when_audio_is_unavailable(self):
        candidate = self.write("candidate.json", self.candidate("zh-Hans"))
        release = self.release("zh-Hans", digest(candidate.read_bytes()))
        release["assets"].append({"role": "audio", "path": "/media/not-allowed.mp3", "sha256": self.hash_b})
        release_path = self.write("release.json", release)
        with self.assertRaisesRegex(MODULE.CatalogBuildError, "unavailable audio"):
            MODULE.build(self.arguments([candidate], [release_path]))

    def test_text_only_four_layer_release_requires_matching_audio_unavailable_package(self):
        candidate = self.write("candidate.json", self.candidate("ko"))
        candidate_hash = digest(candidate.read_bytes())
        release = self.release("ko", candidate_hash)
        release_path = self.write("release.json", release)
        with self.assertRaisesRegex(MODULE.CatalogBuildError, "requires an audio_unavailable Layer 3 package"):
            MODULE.build(self.arguments([candidate], [release_path], allow_legacy=False,
                                        default_target="ko"))

        audio_path = self.write("audio.json", self.audio_unavailable_package("ko", candidate_hash))
        release["targetLanguageAudioPackageJsonSha256"] = digest(audio_path.read_bytes())
        release_path = self.write("release.json", release)
        catalog, _ = MODULE.build(self.arguments([candidate], [release_path],
                                                audio_packages=[audio_path], allow_legacy=False,
                                                default_target="ko"))
        self.assertEqual(catalog["pages"][0]["targets"]["ko"]["capabilities"], ["text"])

        wrong = self.audio_unavailable_package("es", candidate_hash)
        wrong_path = self.write("wrong-audio.json", wrong)
        release["targetLanguageAudioPackageJsonSha256"] = digest(wrong_path.read_bytes())
        release_path = self.write("release.json", release)
        with self.assertRaisesRegex(MODULE.CatalogBuildError, "binding or state is invalid"):
            MODULE.build(self.arguments([candidate], [release_path],
                                        audio_packages=[wrong_path], allow_legacy=False,
                                        default_target="ko"))


if __name__ == "__main__":
    unittest.main()
