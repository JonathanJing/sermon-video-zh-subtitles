"""The weekly content schemas accepted by both published App readers."""

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64
PAGE = "2026-09-27-weekend-sermon-drive-530"
LOCALE = "zh-Hans"


def validate(schema_name: str, value: dict) -> list:
    schema = json.loads((ROOT / "schemas" / schema_name).read_text())
    Draft202012Validator.check_schema(schema)
    return list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))


def release() -> dict:
    return {
        "schemaVersion": "sermon-target-language-release-package-v2",
        "packageId": f"{PAGE}-{LOCALE}",
        "pageId": PAGE,
        "sourceLocale": "en",
        "targetLocale": LOCALE,
        "targetLanguageCandidateJsonSha256": SHA,
        "spokenTargetLanguageCandidateJsonSha256": SHA,
        "targetLanguageAudioPackageJsonSha256": SHA,
        "status": "published_http_verified",
        "contentStatus": "human_reviewed",
        "audioStatus": "human_reviewed",
        "interfaceLocale": LOCALE,
        "contentLocale": LOCALE,
        "audioLocale": LOCALE,
        "assets": [
            {"role": "page", "path": f"/pages/{PAGE}/{LOCALE}/index.html", "sha256": SHA},
            {"role": "content", "path": f"/content/{PAGE}/{LOCALE}.json", "sha256": SHA},
            {"role": "audio", "path": f"/media/{PAGE}/{LOCALE}.mp3", "sha256": SHA},
        ],
        "httpVerification": {"status": "pass", "evidenceSha256": SHA},
        "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
        "venueAcceptance": {"status": "not_run", "evidenceSha256": None},
        "issues": [],
    }


def catalog() -> dict:
    return {
        "schemaVersion": "sermon-multilingual-catalog-v3",
        "generatedAt": "2026-09-27T20:00:00Z",
        "defaultPageId": PAGE,
        "pages": [{
            "id": PAGE,
            "date": "2026-09-27",
            "sourceLocale": "en",
            "sourceIdentitySha256": SHA,
            "sourceMediaSha256": SHA,
            "title": "启示录：耶稣带来的安慰与盼望 · 耶稣配得",
            "defaultTargetLocale": LOCALE,
            "targets": {LOCALE: {
                "releasePackageUrl": f"/releases-v2/{PAGE}/{LOCALE}.json",
                "releasePackageJsonSha256": SHA,
                "contentStatus": "human_reviewed",
                "audioStatus": "human_reviewed",
                "capabilities": ["text", "captions", "audio"],
            }},
        }],
    }


class Layer4ProductionContentContractTests(unittest.TestCase):
    def test_production_pair_is_valid(self) -> None:
        self.assertEqual(validate("sermon-target-language-release-package-v2.schema.json", release()), [])
        self.assertEqual(validate("sermon-multilingual-catalog-v3.schema.json", catalog()), [])

    def test_catalog_requires_in_app_title_and_v2_release_path(self) -> None:
        no_title = copy.deepcopy(catalog())
        del no_title["pages"][0]["title"]
        self.assertTrue(validate("sermon-multilingual-catalog-v3.schema.json", no_title))
        old_path = copy.deepcopy(catalog())
        old_path["pages"][0]["targets"][LOCALE]["releasePackageUrl"] = f"/releases/{PAGE}/{LOCALE}.json"
        self.assertTrue(validate("sermon-multilingual-catalog-v3.schema.json", old_path))

    def test_release_requires_approved_spoken_script_binding(self) -> None:
        missing = release()
        del missing["spokenTargetLanguageCandidateJsonSha256"]
        self.assertTrue(validate("sermon-target-language-release-package-v2.schema.json", missing))

    def test_firebase_catalog_refresh_is_not_cached(self) -> None:
        config = json.loads((ROOT / "firebase/production-overlay/firebase.json").read_text())
        matches = [item for item in config["hosting"]["headers"] if item["source"] == "/multilingual-v3.json"]
        self.assertEqual(len(matches), 1)
        self.assertIn({"key": "Cache-Control", "value": "no-store"}, matches[0]["headers"])


if __name__ == "__main__":
    unittest.main()
