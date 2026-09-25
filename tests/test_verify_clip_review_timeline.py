import unittest

from scripts.verify_clip_review_timeline import verify


class ClipReviewTimelineTests(unittest.TestCase):
    def setUp(self):
        self.anchor = {"sourceUnits": [
            {"sourceUnitId": "block-09-u001", "start": 320.16, "end": 327.28},
            {"sourceUnitId": "block-09-u002", "start": 327.49, "end": 331.24},
        ]}

    def test_accepts_original_recording_times(self):
        markdown = ("| `block-09-u001` | 35:09.16–35:16.28 | text |\n"
                    "| `block-09-u002` | 35:16.49–35:20.24 | text |")
        self.assertEqual(verify(self.anchor, markdown, original_sermon_start=1789,
                                clip_start=2109.16, clip_end=2120.24), 2)

    def test_rejects_double_added_offset(self):
        markdown = ("| `block-09-u001` | 40:29.32–40:36.44 | text |\n"
                    "| `block-09-u002` | 40:36.65–40:40.40 | text |")
        with self.assertRaisesRegex(ValueError, "timebase mismatch"):
            verify(self.anchor, markdown, original_sermon_start=1789,
                   clip_start=2109.16, clip_end=2120.24)

    def test_accepts_bounded_trailing_silence(self):
        markdown = ("| `block-09-u001` | 35:09.16–35:16.28 | text |\n"
                    "| `block-09-u002` | 35:16.49–35:20.24 | text |")
        self.assertEqual(verify(self.anchor, markdown, original_sermon_start=1789,
                                clip_start=2109.16, clip_end=2120.47,
                                max_trailing_silence=0.25), 2)
        with self.assertRaisesRegex(ValueError, "Last anchor"):
            verify(self.anchor, markdown, original_sermon_start=1789,
                   clip_start=2109.16, clip_end=2121.0,
                   max_trailing_silence=0.25)


if __name__ == "__main__":
    unittest.main()
