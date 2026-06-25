import unittest
from html.parser import HTMLParser
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


class ActionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.actions = []
        self.classes = []
        self.data_operator_only_count = 0

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if "data-action" in attr_map:
            self.actions.append(attr_map["data-action"])
        if "class" in attr_map:
            self.classes.extend(attr_map["class"].split())
        if "data-operator-only" in attr_map:
            self.data_operator_only_count += 1


def parse_html(name):
    parser = ActionParser()
    parser.feed((WEB_ROOT / name).read_text(encoding="utf-8"))
    return parser


class PublicAdminBoundaryTest(unittest.TestCase):
    def test_public_page_has_no_operator_controls_in_dom(self):
        public = parse_html("index.html")
        forbidden_actions = {
            "start-monitor",
            "start-caption",
            "start-playback",
            "trigger-manual-ingest",
            "run-auto-discovery",
            "save-admin-settings",
            "use-fallback",
            "start-archive-latency-test",
            "start-mic-latency-test",
            "stop-mic-latency-test",
            "mark-sermon-start",
            "export-test-report",
            "mark-segment",
            "lock-segment",
            "toggle-stream",
            "freeze-review",
            "export-vtt",
            "export-srt",
            "apply-offset",
        }

        self.assertFalse(forbidden_actions.intersection(public.actions))
        self.assertNotIn("control-panel", public.classes)
        self.assertNotIn("admin-overview", public.classes)
        self.assertEqual(public.data_operator_only_count, 0)

    def test_admin_page_retains_operator_controls(self):
        admin = parse_html("admin.html")

        for action in [
            "trigger-manual-ingest",
            "start-archive-latency-test",
            "start-mic-latency-test",
            "export-vtt",
            "export-srt",
        ]:
            self.assertIn(action, admin.actions)
        self.assertIn("control-panel", admin.classes)
        self.assertIn("admin-overview", admin.classes)
        self.assertGreater(admin.data_operator_only_count, 0)


if __name__ == "__main__":
    unittest.main()
