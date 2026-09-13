"""Archive routing integration: synthetic source handoff, no model or publication."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare_archive_sermon as archive
import weekly_dubbing as weekly
import build_weekly_app as app
from poc import write_json, sha256
import test_saturday_bridge as bridge_fixture


class ArchiveWeeklyTests(unittest.TestCase):
    def test_prepare_keeps_archive_identity_and_rejects_mixed_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, _, _, run = bridge_fixture.SaturdayBridgeTests().fixture(root)
            contract = {"schemaVersion": archive.SCHEMA, "week": "2026-09-06", "sourceId": "frqebLEtyqw", "canonicalURL": "https://www.youtube.com/watch?v=frqebLEtyqw", "durationSeconds": 10}
            write_json(run / archive.CONTRACT, contract)
            outline_path = run / "pipeline/sermon-interpretation/insights/openai-notes.json"
            outline = weekly.read(outline_path)
            outline["speaker"] = "Eric Geiger"
            write_json(outline_path, outline)
            source = run / 'source/audio.m4a'
            source.parent.mkdir()
            source.write_bytes(b'archive audio fixture')
            inputs = {key: {"path": str(path), "sha256": sha256(path)} for key, path in
                {"sourceContract": run / archive.CONTRACT, "sourceAudio": source}.items()}
            authorization = root / 'authorization.json'
            write_json(authorization, {"schemaVersion": "sermon-voice-authorization-v1", "statement": "Synthetic test authorization", "status": "confirmed_by_user", "purposes": ["chinese_dubbing"], "sources": [{"sourceId": contract['sourceId'], "sha256": sha256(source)}]})
            with patch.object(archive, 'validate_handoff', return_value=(contract, inputs)):
                job = weekly.prepare(run, root / 'voice', root / 'job', contract['week'], '标题', 'Eric Geiger', '诗篇 73', authorization, archive_contract=run / archive.CONTRACT)
                outline["speaker"] = "Jared Kirkwood"
                write_json(outline_path, outline)
                with self.assertRaisesRegex(ValueError, "outline speaker"):
                    weekly.prepare(run, root / "voice", root / "wrong-speaker-job", contract["week"], "标题", "Eric Geiger", "诗篇 73", authorization, archive_contract=run / archive.CONTRACT)
                outline["speaker"] = "Eric Geiger"
                write_json(outline_path, outline)
                self.assertEqual(job['sourceRoute'], 'archive_caption')
                self.assertEqual(job["archiveCaptionContractVersion"], archive.SCHEMA)
                contract["schemaVersion"] = archive.SCHEMA_V2
                version_two = weekly.prepare(run, root / "voice", root / "job-v2", contract["week"], "标题", "Eric Geiger", "诗篇 73", authorization, archive_contract=run / archive.CONTRACT)
                self.assertEqual(version_two["archiveCaptionContractVersion"], archive.SCHEMA_V2)
                contract["schemaVersion"] = archive.SCHEMA
                self.assertEqual(job['inputs']['sourceAudio'], inputs['sourceAudio'])
                self.assertEqual(job['inheritedReview']['humanWindow'], 'not_applicable')
                self.assertFalse(job['inheritedReview']['generationComplete'])
                self.assertNotIn('clipReceipt', job['inputs'])
                for key in ['sourceRoute', 'boundaryBasis', 'archiveCaptionContractVersion']:
                    changed = copy.deepcopy(job)
                    changed[key] = 'wrong'
                    with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                        weekly.validate_frozen(changed)
                changed = copy.deepcopy(job)
                changed['inputs']['sameVideoHandoff'] = inputs['sourceContract']
                with self.assertRaises(ValueError):
                    weekly.validate_frozen(changed)
                source.write_bytes(b'changed archive audio')
                with self.assertRaises(ValueError):
                    weekly.validate_frozen(job)

    def test_archive_page_identity_is_distinct_and_publication_is_blocked(self):
        job = {'week': '2026-09-06', 'sourceId': 'frqebLEtyqw', 'sourceRoute': 'archive_caption'}
        self.assertEqual(app.source_page(job)['id'], '2026-09-06-archive_caption-frqebLEtyqw')
        self.assertEqual(app.source_page(job)['sourceLabel'], 'YouTube 版')
        self.assertEqual(app.source_page({**job, "sourceRoute": "same_video"})["sourceLabel"], "YouTube 版")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            write_json(work / 'job.json', job)
            write_json(work / 'audio-review.json', {})
            with patch.object(weekly, 'validate_frozen'), self.assertRaisesRegex(ValueError, 'candidates only'):
                weekly.validate_review(work)


if __name__ == '__main__':
    unittest.main()
