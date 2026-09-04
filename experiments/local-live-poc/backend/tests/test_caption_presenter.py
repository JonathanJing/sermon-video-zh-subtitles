from __future__ import annotations

import unittest

from backend.caption_presenter import CaptionPresenter


class CaptionPresenterTest(unittest.TestCase):
    def test_readable_policy_suppresses_tiny_flashes_and_emits_final(self) -> None:
        now = [10.0]
        presenter = CaptionPresenter(clock=lambda: now[0])
        common = {
            "segmentId": "seg-1",
            "sourceTextEn": "Grace changes how we face tomorrow.",
        }

        self.assertIsNone(presenter.partial({
            **common,
            "targetTextZh": "恩典",
        }))
        now[0] += 0.2
        self.assertIsNone(presenter.partial({
            **common,
            "targetTextZh": "恩典改变我们",
        }))
        now[0] += 0.2
        first = presenter.partial({
            **common,
            "targetTextZh": "恩典改变我们面对",
        })

        self.assertEqual(first["type"], "caption.display")
        self.assertEqual(first["displayKind"], "partial")
        self.assertEqual(first["presentationMetrics"]["firstPartialToVisibleMs"], 400)

        now[0] += 0.2
        self.assertIsNone(presenter.partial({
            **common,
            "targetTextZh": "恩典改变我们面对明天",
        }))
        final = presenter.final({
            **common,
            "targetTextZh": "恩典改变我们面对明天的方式。",
        })
        self.assertEqual(final["displayKind"], "final")
        self.assertEqual(final["phase"], "final")

    def test_legacy_policy_keeps_raw_events_visible(self) -> None:
        presenter = CaptionPresenter(policy="legacy")
        self.assertTrue(presenter.raw_events_are_visible)
        self.assertIsNone(presenter.partial({"segmentId": "seg-1", "targetTextZh": "恩典"}))
        self.assertIsNone(presenter.final({"segmentId": "seg-1", "targetTextZh": "恩典。"}))

    def test_terminal_fallback_is_a_stable_display_event(self) -> None:
        presenter = CaptionPresenter()
        event = presenter.terminal({
            "segmentId": "seg-1",
            "sourceTextEn": "Grace.",
        }, "翻译暂时不可用，请查看英文原文。")
        self.assertEqual(event["type"], "caption.display")
        self.assertEqual(event["phase"], "error")


if __name__ == "__main__":
    unittest.main()
