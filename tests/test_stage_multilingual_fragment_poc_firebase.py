import hashlib
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from scripts import stage_multilingual_fragment_poc_firebase as subject


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class StageMultilingualFragmentPocFirebaseTests(unittest.TestCase):
    def test_all_advertised_variants_are_required_and_staged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public = root / "public"
            layer2 = root / "layer2"
            layer3 = root / "layer3"
            variants = root / "variants"
            variants.mkdir()
            page_id = "test-page"
            tracks = []
            for locale in subject.TARGET_LOCALES:
                candidate = {"targetLocale": locale}
                package = {"targetLanguageCandidateJsonSha256": subject.canonical_sha(candidate),
                           "track": {"sha256": sha(locale.encode())}}
                (layer2 / locale).mkdir(parents=True)
                (layer3 / locale).mkdir(parents=True)
                (layer2 / locale / "target-language-candidate.json").write_text(json.dumps(candidate))
                (layer3 / locale / "target-language-audio-package.json").write_text(json.dumps(package))
                (layer3 / locale / "audio.mp3").write_bytes(locale.encode())
                native_name = subject.native_audio_name(page_id, locale)
                tracks.append({"locale": locale, "sha256": sha(locale.encode()),
                               "file": native_name, "audioUrl": f"/media/{native_name}"})
                release = {"pageId": page_id, "targetLocale": locale,
                           "audioUrl": f"/media/{page_id}/{locale}.mp3",
                           "audioSha256": sha(locale.encode())}
                if locale == "zh-Hans":
                    release["defaultAudioVariantId"] = "natural"
                    release["audioVariants"] = [{"id": "natural", "audioUrl": f"/media/{page_id}/zh-Hans-natural.mp3",
                                                 "audioSha256": sha(b"natural audio") }]
                release_dir = public / "releases" / page_id
                release_dir.mkdir(parents=True, exist_ok=True)
                (release_dir / f"{locale}.json").write_text(json.dumps(release))
            (public / "weekly.json").write_text(json.dumps({"weeks": [{"id": page_id, "tracks": tracks}]}))
            argv = ["stage_multilingual_fragment_poc_firebase.py", "--layer2", str(layer2),
                    "--layer3", str(layer3), "--public", str(public), "--page-id", page_id,
                    "--variant-media-dir", str(variants)]
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(SystemExit, "Missing or mismatched release audio"):
                    subject.main()
                self.assertFalse((public / "media").exists())
                (variants / "zh-Hans-natural.mp3").write_bytes(b"natural audio")
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(subject.main(), 0)
            self.assertEqual((public / "media" / page_id / "zh-Hans-natural.mp3").read_bytes(), b"natural audio")
            for locale in subject.TARGET_LOCALES:
                self.assertEqual((public / "media" / subject.native_audio_name(page_id, locale)).read_bytes(),
                                 locale.encode())


if __name__ == "__main__":
    unittest.main()
