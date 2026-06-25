import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_playback_captions.py"
SPEC = importlib.util.spec_from_file_location("export_playback_captions", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def write_simulation(path: Path, segments: list[dict]) -> None:
    payload = {
        "schemaVersion": 1,
        "translationStatus": "ready",
        "offlineSourceKind": "live_archive",
        "offlineRoute": {
            "strategy": "captions_first_then_asr",
            "decision": "use_caption_track",
            "selectedSourceKind": "live_archive",
            "asrFallbackRequired": False,
            "audioExtractionAttempted": False,
            "fallbackReason": None,
        },
        "segments": segments,
    }
    path.write_text(
        "window.SERMON_PLAYBACK_SIMULATION = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


class ExportPlaybackCaptionsTest(unittest.TestCase):
    def test_exports_ready_chinese_segments_to_vtt_and_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "playback.js"
            write_simulation(
                source,
                [
                    {
                        "startMs": 1000,
                        "endMs": 2500,
                        "zh": "神爱世人。",
                        "en": "God loved the world.",
                        "translationStatus": "ready",
                    },
                    {
                        "startMs": 2600,
                        "endMs": 5000,
                        "zh": "我们凭信心回应。",
                        "en": "We respond by faith.",
                        "translationStatus": "ready",
                    },
                ],
            )

            simulation = mod.read_simulation(source)
            cues = mod.cues_from_simulation(simulation, lang="zh", allow_draft=False)

            self.assertEqual(len(cues), 2)
            self.assertIn("00:00:01.000 --> 00:00:02.500", mod.render_vtt(cues))
            self.assertIn("神爱世人。", mod.render_vtt(cues))
            self.assertIn("00:00:01,000 --> 00:00:02,500", mod.render_srt(cues))

    def test_skips_placeholder_chinese_without_allow_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "playback.js"
            write_simulation(
                source,
                [
                    {
                        "startMs": 0,
                        "endMs": 1000,
                        "zh": "AI 中文待生成：God loved the world.",
                        "translationStatus": "needs_translation",
                    }
                ],
            )

            cues = mod.cues_from_simulation(mod.read_simulation(source), lang="zh", allow_draft=False)

            self.assertEqual(cues, [])

    def test_updates_manifest_with_exported_caption_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "playback.js"
            write_simulation(
                source,
                [
                    {
                        "startMs": 1000,
                        "endMs": 2500,
                        "zh": "神爱世人。",
                        "en": "God loved the world.",
                        "translationStatus": "ready",
                    }
                ],
            )
            manifest = root / "cloud-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "outputs": [
                            {
                                "localPath": "web/playback-simulation.generated.js",
                                "gcsUri": "gs://bucket/run/web/playback-simulation.generated.js",
                            }
                        ],
                        "apiKeyMaterialIncluded": False,
                        "secretResourceNamesIncluded": False,
                    }
                ),
                encoding="utf-8",
            )

            mod.update_manifest_outputs(
                manifest_path=manifest,
                outputs=[
                    {
                        "localPath": "artifacts/sermon.zh.live-aligned.vtt",
                        "gcsUri": "gs://bucket/run/artifacts/sermon.zh.live-aligned.vtt",
                    },
                    {
                        "localPath": "artifacts/sermon.zh.live-aligned.srt",
                        "gcsUri": "gs://bucket/run/artifacts/sermon.zh.live-aligned.srt",
                    },
                ],
                playback=mod.read_simulation(source),
            )

            updated = json.loads(manifest.read_text(encoding="utf-8"))
            paths = {item["localPath"] for item in updated["outputs"]}
            self.assertIn("web/playback-simulation.generated.js", paths)
            self.assertIn("artifacts/sermon.zh.live-aligned.vtt", paths)
            self.assertIn("artifacts/sermon.zh.live-aligned.srt", paths)
            self.assertEqual(updated["captionExportStatus"], "ready")
            self.assertEqual(updated["offlineSourceKind"], "live_archive")
            self.assertEqual(updated["offlineRoute"]["decision"], "use_caption_track")
            self.assertFalse(updated["offlineRoute"]["audioExtractionAttempted"])
            self.assertFalse(updated["apiKeyMaterialIncluded"])
            self.assertFalse(updated["secretResourceNamesIncluded"])

    def test_publish_uses_artifacts_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "artifacts"
            out_dir.mkdir()
            vtt = out_dir / "sermon.zh.live-aligned.vtt"
            vtt.write_text("WEBVTT\n\n", encoding="utf-8")

            uploads = mod.publish_files_to_gcs(
                files=[vtt],
                bucket="gs://sermon-zh-poc/",
                prefix="/sundays/2026-06-28/runs/test/",
                out_dir=out_dir,
                dry_run=True,
            )

            self.assertEqual(
                uploads,
                [
                    {
                        "localPath": "artifacts/sermon.zh.live-aligned.vtt",
                        "gcsUri": "gs://sermon-zh-poc/sundays/2026-06-28/runs/test/artifacts/sermon.zh.live-aligned.vtt",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
