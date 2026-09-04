from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.content_pack import build_weekly_pack
from backend.replay_ab import read_asr_finals, run_replay, write_replay_artifacts


class ReplayAbTest(unittest.TestCase):
    def test_frozen_asr_finals_are_replayed_and_blinded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = Path(temporary) / "session"
            session.mkdir()
            events = [
                {"type": "asr.final", "segmentId": "seg-1", "sourceTextEn": "The promised land is before us.", "audioStartMs": 0, "audioEndMs": 3000},
                {"type": "translation.final", "segmentId": "seg-1", "targetTextZh": "ignored"},
            ]
            (session / "events.jsonl").write_text("".join(json.dumps(item) + "\n" for item in events))
            (session / "recording.webm").write_bytes(b"audio")
            pack = build_weekly_pack([{
                "segmentId": "sat-1",
                "sourceTextEn": "The promised land is before us.",
                "terms": [{"source": "promised land", "preferredZh": "应许之地", "status": "approved"}],
            }], service_date="2099-01-01", source_id="sat", audio_sha256="a" * 64, valid_until="2099-01-02")
            segments = read_asr_finals(session)
            def translate(source, context):
                term = context.get("approvedTerms", [])
                return {"targetTextZh": "有术语" if term else "无术语", "model": "fake"}
            results = run_replay(segments, ["none", "weekly_terms_v1"], translate, pack)
            self.assertEqual([item["targetTextZh"] for item in results], ["无术语", "有术语"])
            output = Path(temporary) / "output"
            run = write_replay_artifacts(session, output, ["none", "weekly_terms_v1"], results, "fake", pack)
            self.assertEqual(run["resultCount"], 2)
            self.assertTrue((output / "review.csv").is_file())
            self.assertIn("human_review_required", (output / "run.json").read_text())


if __name__ == "__main__":
    unittest.main()
