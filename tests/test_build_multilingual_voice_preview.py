"""Guard the audition page against stale voice assets and review labels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import build_multilingual_voice_preview as preview


REPO = Path(__file__).resolve().parents[1]


class VoicePreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry_path = REPO / "config/speaker-voice-registry.json"
        self.registry = preview.read_json(self.registry_path)
        self.script = preview.read_json(
            REPO / "experiments/sermon-dubbing-poc/multilingual-voice-demo-script-v1.json")
        locale_text = {row["targetLocale"]: row["text"] for row in self.script["locales"]}
        generated = {"manifest.json": [], "vietnamese-manifest.json": []}
        delivered = []
        for speaker in self.registry["speakers"]:
            for capability in speaker["localeCapabilities"]:
                locale = capability["targetLocale"]
                key = speaker["speakerId"]
                wav_relative = f"{key}/{locale}.wav"
                mp3_relative = f"mp3/{key}/{locale}.mp3"
                wav = self.root / wav_relative
                mp3 = self.root / mp3_relative
                wav.parent.mkdir(parents=True, exist_ok=True)
                mp3.parent.mkdir(parents=True, exist_ok=True)
                wav.write_bytes(f"wav:{key}:{locale}".encode())
                mp3.write_bytes(f"mp3:{key}:{locale}".encode())
                adapter = "qwen3_tts_sft"
                source = {
                    "speakerId": key,
                    "targetLocale": locale,
                    "displayName": speaker["displayName"],
                    "capabilityStatus": capability["status"],
                    "humanListeningStatus": "pending",
                    "file": wav_relative,
                    "audioSha256": preview.sha256(wav),
                    "textSha256": hashlib.sha256(locale_text[locale].encode()).hexdigest(),
                }
                if locale == "vi":
                    adapter_row = capability["adapterOverride"]
                    adapter = adapter_row["adapter"]
                    source.update({
                        "adapter": adapter,
                        "model": adapter_row["model"],
                        "modelRevision": adapter_row["revision"],
                        "conditioningRef": adapter_row["conditioningRef"],
                        "referenceAudioSha256": adapter_row["conditioningRef"].rsplit("/", 1)[-1],
                    })
                    source_name = "vietnamese-manifest.json"
                else:
                    source.update({
                        "speakerKey": speaker["speakerKey"],
                        "checkpointRef": speaker["checkpoint"]["checkpointRef"],
                        "checkpointSha256": speaker["checkpoint"]["checkpointSha256"],
                        "modelLanguage": capability["modelLanguage"],
                    })
                    source_name = "manifest.json"
                generated[source_name].append(source)
                delivered.append({
                    "speakerId": key,
                    "targetLocale": locale,
                    "displayName": speaker["displayName"],
                    "adapter": adapter,
                    "capabilityStatus": capability["status"],
                    "humanListeningStatus": "pending",
                    "sourceWav": {"path": wav_relative, "sha256": preview.sha256(wav)},
                    "mp3": {"path": mp3_relative, "sha256": preview.sha256(mp3),
                            "fullDecode": "pass", "durationSeconds": 1.0},
                })
        sources = []
        for name, tracks in generated.items():
            path = self.root / name
            path.write_text(json.dumps({"scriptJsonSha256": preview.json_sha256(self.script),
                                        "registryJsonSha256": "a" * 64,
                                        "tracks": tracks}), encoding="utf-8")
            sources.append({"path": name, "sha256": preview.sha256(path)})
        self.delivery = {
            "schemaVersion": preview.DELIVERY_SCHEMA,
            "status": "encoded_and_fully_decoded",
            "scope": "voice_capability_audition_not_sermon_translation",
            "fullDecodeCoverage": 1,
            "registry": {"sha256": preview.sha256(self.registry_path)},
            "sourceManifests": sources,
            "speakerCount": 6,
            "targetLocales": list(preview.LOCALE_ORDER),
            "trackCount": 24,
            "tracks": delivered,
        }
        self.write_delivery()

    def write_delivery(self) -> None:
        (self.root / "delivery-manifest.json").write_text(
            json.dumps(self.delivery), encoding="utf-8")

    def change_source(self, name: str, field: str, value: str) -> None:
        path = self.root / name
        manifest = preview.read_json(path)
        manifest["tracks"][0][field] = value
        path.write_text(json.dumps(manifest), encoding="utf-8")
        next(item for item in self.delivery["sourceManifests"]
             if item["path"] == name)["sha256"] = preview.sha256(path)
        self.write_delivery()

    def test_fresh_delivery_uses_checked_in_snapshots_and_labels_pending_audio(self) -> None:
        page = self.root / "index.html"
        preview.build(self.root, page, decode=False)
        html = page.read_text(encoding="utf-8")
        self.assertEqual(html.count("本次样音待听审"), 24)
        self.assertEqual(html.count("旧中文样片已有能力认可"), 6)
        self.assertEqual(html.count("语言能力尚未晋升"), 18)

    def test_changed_checkpoint_is_rejected_even_if_manifest_hash_is_updated(self) -> None:
        self.change_source("manifest.json", "checkpointSha256", "0" * 64)
        with self.assertRaisesRegex(ValueError, "Qwen voice identity differs"):
            preview.build(self.root, self.root / "index.html", decode=False)
        self.assertFalse((self.root / "index.html").exists())

    def test_changed_vietnamese_adapter_is_rejected(self) -> None:
        self.change_source("vietnamese-manifest.json", "modelRevision", "other")
        with self.assertRaisesRegex(ValueError, "Vietnamese voice identity differs"):
            preview.build(self.root, self.root / "index.html", decode=False)


if __name__ == "__main__":
    unittest.main()
