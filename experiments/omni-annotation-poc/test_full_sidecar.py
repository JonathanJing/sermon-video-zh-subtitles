#!/usr/bin/env python3
from __future__ import annotations

import unittest

from build_full_sidecar import build_sentence_timeline, merge_events, owner_window


class FullSidecarTest(unittest.TestCase):
    def test_sentence_timeline_uses_word_edges(self) -> None:
        blocks = [{"id": 0, "en": "Hello world. Read this now."}]
        report = {"blocks": [{"blockId": 0, "start": 1.0, "end": 4.0}]}
        words = [
            {"text": "Hello", "start": 1.0, "end": 1.4},
            {"text": "world", "start": 1.5, "end": 2.0},
            {"text": "Read", "start": 2.5, "end": 2.9},
            {"text": "this", "start": 3.0, "end": 3.3},
            {"text": "now", "start": 3.4, "end": 4.0},
        ]
        timeline, issues = build_sentence_timeline(blocks, report, words)
        self.assertEqual(issues, [])
        self.assertEqual([(item["startSeconds"], item["endSeconds"]) for item in timeline],
                         [(1.0, 2.0), (2.5, 4.0)])

    def test_owner_window_prefers_center_and_removes_overlap_vote(self) -> None:
        windows = [
            {"windowId": "a", "relativeStartSeconds": 0, "relativeEndSeconds": 60},
            {"windowId": "b", "relativeStartSeconds": 50, "relativeEndSeconds": 110},
        ]
        self.assertEqual(owner_window(windows, 52)["windowId"], "a")
        self.assertEqual(owner_window(windows, 58)["windowId"], "b")

    def test_merge_only_adjacent_same_type(self) -> None:
        labeled = [
            {"sentenceId": "s1", "startSeconds": 0, "endSeconds": 2,
             "geminiType": "scripture_reading", "geminiWindowId": "w1"},
            {"sentenceId": "s2", "startSeconds": 2.5, "endSeconds": 4,
             "geminiType": "scripture_reading", "geminiWindowId": "w2"},
            {"sentenceId": "s3", "startSeconds": 4.1, "endSeconds": 6,
             "geminiType": "sermon_explanation", "geminiWindowId": "w2"},
        ]
        merged = merge_events(labeled)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["sentenceIds"], ["s1", "s2"])
        self.assertEqual(merged[0]["sourceWindowIds"], ["w1", "w2"])


if __name__ == "__main__":
    unittest.main()
