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
    def test_public_and_admin_disclaimers_state_independence_and_source_boundary(self):
        required_text = [
            "独立个人开源项目",
            "并非 Mariners Church 官方项目",
            "公开可访问或已授权",
            "英文听写与中文翻译",
            "不绕过访问控制",
            "DRM",
            "版权保护",
        ]

        for name in ["index.html", "admin.html"]:
            text = (WEB_ROOT / name).read_text(encoding="utf-8")
            for expected in required_text:
                self.assertIn(expected, text, f"{name} missing disclaimer text: {expected}")

    def test_public_page_has_no_operator_controls_in_dom(self):
        public = parse_html("index.html")
        public_html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
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
        self.assertIn(">经文侧栏</button>", public_html)
        self.assertIn(">收起侧栏</button>", public_html)
        self.assertNotIn(">章</button>", public_html)
        self.assertNotIn(">收</button>", public_html)

    def test_admin_page_retains_operator_controls(self):
        admin = parse_html("admin.html")

        for action in [
            "trigger-manual-ingest",
            "start-archive-latency-test",
            "start-mic-latency-test",
            "live-playback-start",
            "review-list-compact",
            "review-list-toggle",
            "review-list-expand",
            "export-vtt",
            "export-srt",
        ]:
            self.assertIn(action, admin.actions)
        self.assertIn("control-panel", admin.classes)
        self.assertIn("admin-overview", admin.classes)
        self.assertGreater(admin.data_operator_only_count, 0)

    def test_admin_primary_flow_is_iphone_first_and_advanced_tools_start_collapsed(self):
        admin_html = (WEB_ROOT / "admin.html").read_text(encoding="utf-8")
        app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        styles = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn('data-sidebar="closed"', admin_html)
        self.assertIn('class="admin-run-panel"', admin_html)
        self.assertIn('id="adminMainFlow"', admin_html)
        self.assertIn('id="livePlaybackStartButton"', admin_html)
        self.assertIn('>开始字幕</button>', admin_html)
        self.assertIn('id="adminAdvancedTools"', admin_html)
        self.assertNotIn('id="adminAdvancedTools" open', admin_html)
        self.assertIn("admin-caption-tools", admin_html)
        self.assertIn('state.reviewListCollapsed = true', app_js)
        self.assertIn('function syncAdminMainFlow()', app_js)
        self.assertIn('function syncLivePlaybackControls(', app_js)
        self.assertIn('function adminPlaybackReady()', app_js)
        self.assertIn('state.publicPlaybackSunday === state.adminSettings.sunday', app_js)
        self.assertIn('.admin-run-panel', styles)
        self.assertIn('.admin-main-flow', styles)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr));', styles)

    def test_admin_review_strip_has_mobile_resize_contract(self):
        public = parse_html("index.html")
        admin = parse_html("admin.html")
        app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        styles = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertNotIn("review-list-compact", public.actions)
        self.assertIn("review-list-compact", admin.actions)
        self.assertIn("review-list-toggle", admin.actions)
        self.assertIn("review-list-expand", admin.actions)
        self.assertIn("function setReviewListSize(size)", app_js)
        self.assertIn("function toggleReviewList()", app_js)
        self.assertIn("dataset.reviewSize", app_js)
        self.assertIn("dataset.reviewCollapsed", app_js)
        self.assertIn(".admin-shell[data-review-size=\"compact\"]", styles)
        self.assertIn(".admin-shell[data-review-size=\"large\"]", styles)
        self.assertIn(".admin-shell[data-review-collapsed=\"true\"] .segment-list", styles)


if __name__ == "__main__":
    unittest.main()
