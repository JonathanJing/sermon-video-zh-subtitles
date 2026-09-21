import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("run_expanded_sentence_anchor", HERE / "run_expanded_sentence_anchor.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExpandedSentenceAnchorTests(unittest.TestCase):
    def week(self):
        return {
            "id": "week",
            "sourceId": "source",
            "sourceSha256": "a" * 64,
            "sourceStartSeconds": 100,
            "sourceEndSeconds": 120,
            "transcript": {"blocks": [
                {"blockId": "0", "english": "First sentence.", "chinese": "第一句。"},
                {"blockId": "1", "english": "Second sentence. More.", "chinese": "第二句。更多。"},
            ]},
            "tracks": [{"cues": [
                {"blockId": 0, "start": 0.0, "end": 4.0, "text": "第一句。"},
                {"blockId": 1, "start": 5.0, "end": 9.0, "text": "第二句。更多。"},
            ]}],
        }

    def paths(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        paths = [root / name for name in ("catalog.json", "source.wav", "sermon.wav", "segments.json", "manifest.json", "runtime.json")]
        for path in paths:
            path.write_bytes(b"x")
        return temporary, paths

    def test_block_windows_use_next_published_block_start(self):
        windows = MODULE.block_windows(self.week())
        self.assertEqual((windows[0]["start"], windows[0]["end"]), (0.0, 5.0))
        self.assertEqual((windows[1]["start"], windows[1]["end"]), (5.0, 20.0))

    def test_report_preserves_non_release_machine_boundary(self):
        temporary, paths = self.paths()
        self.addCleanup(temporary.cleanup)
        catalog, source, sermon, segments_path, manifest, runtime = paths
        catalog.write_text(json.dumps({"weeks": [self.week()]}), encoding="utf-8")
        windows = MODULE.block_windows(self.week())
        segments = [
            {
                "referenceChunkId": "block-00",
                "text": "First sentence.",
                "start": 0.2,
                "end": 4.5,
                "wordTimes": [
                    {"text": "First", "start": 0.2, "end": 1.0},
                    {"text": "sentence.", "start": 3.5, "end": 4.5},
                ],
            },
            {
                "referenceChunkId": "block-01",
                "text": "Second sentence.",
                "start": 5.2,
                "end": 8.0,
                "wordTimes": [
                    {"text": "Second", "start": 5.2, "end": 6.0},
                    {"text": "sentence.", "start": 7.0, "end": 8.0},
                ],
            },
            {
                "referenceChunkId": "block-01",
                "text": "More.",
                "start": 8.5,
                "end": 9.5,
                "wordTimes": [{"text": "More.", "start": 8.5, "end": 9.5}],
            },
        ]
        report = MODULE.build_anchor_report(
            week=self.week(), windows=windows, selected_ids=[0, 1], segments=segments,
            catalog_path=catalog, source_path=source, sermon_audio=sermon,
            segments_path=segments_path, manifest_path=manifest, runtime_path=runtime,
        )
        self.assertTrue(report["structuralPass"])
        self.assertFalse(report["releaseEligible"])
        self.assertEqual(report["coverage"]["englishSentences"], 3)
        self.assertEqual(report["aggregate"]["blocksEndingOver2sEarly"], 0)

    def test_parse_block_ids_rejects_duplicates_and_unsorted_values(self):
        with self.assertRaises(ValueError):
            MODULE.parse_block_ids("1,1")
        with self.assertRaises(ValueError):
            MODULE.parse_block_ids("2,1")

    def test_srt_time_rounds_milliseconds(self):
        self.assertEqual(MODULE.srt_time(61.2346), "00:01:01,235")


if __name__ == "__main__":
    unittest.main()
