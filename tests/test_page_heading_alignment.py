"""Header lines agree across web, iOS and the static page: series, title, date · speaker, scripture."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments" / "sentence-first-agent"
for entry in (str(EXPERIMENTS), str(ROOT), str(ROOT / "packages/production/src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from tools.ops import page_heading  # noqa: E402
from tools.ops import sfa_publish_gate as gate_module  # noqa: E402

SERIES = "启示录：耶稣带来的安慰与盼望"


def publisher():
    if "sfa_publish" in sys.modules:
        return sys.modules["sfa_publish"]
    spec = importlib.util.spec_from_file_location("sfa_publish", EXPERIMENTS / "sfa_publish.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sfa_publish"] = module  # dataclasses look the module up while it loads
    spec.loader.exec_module(module)
    return module


def sermon(**overrides):
    return {"title": "耶稣必再来", "series": SERIES, "scripture": "启示录 19:11–21:8",
            "speaker": "Eric Geiger", "date": "2026-11-22", **overrides}


def test_series_is_shown_once():
    assert page_heading.heading_lines("耶稣必再来", SERIES) == ("耶稣必再来", SERIES)
    assert page_heading.heading_lines(f"耶稣的应许 · {SERIES}", SERIES) == ("耶稣的应许", SERIES)
    # Approved podcast format keeps the published title; the series line is left out.
    assert page_heading.heading_lines("如果我有更多时间 · 耶稣必再来", "如果我有更多时间") == (
        "如果我有更多时间 · 耶稣必再来", "")
    assert page_heading.heading_lines("Grace", None) == ("Grace", "")
    assert page_heading.details_line("2026-11-22", "Eric Geiger · John Thomas") == "2026-11-22 · Eric Geiger · John Thomas"


def test_static_page_header_has_the_four_lines_in_order():
    html = publisher().static_heading_html(sermon())
    fragments = ['<p class="series">启示录：耶稣带来的安慰与盼望</p>', "<h1>耶稣必再来</h1>",
                 '<p class="details">2026-11-22 · Eric Geiger</p>', '<p class="scripture">启示录 19:11–21:8</p>']
    positions = [html.index(fragment) for fragment in fragments]
    assert positions == sorted(positions)


def test_static_page_header_for_a_podcast_leaves_out_the_repeated_series():
    html = publisher().static_heading_html(sermon(title="If I Had More Time · Jesús volverá",
                                                  series="If I Had More Time", speaker="Eric Geiger · John Thomas"))
    assert 'class="series"' not in html
    assert "<h1>If I Had More Time · Jesús volverá</h1>" in html


def fake_site(monkeypatch, content, page_html):
    def get(url, headers=None):
        if url.endswith("/content/page-1/zh-Hans.json"):
            return 200, json.dumps(content, ensure_ascii=False).encode()
        if url.endswith("/pages/page-1/zh-Hans/index.html"):
            return 200, page_html.encode()
        return 404, b""
    monkeypatch.setattr(gate_module, "get", get)


def test_gate_accepts_a_page_written_by_the_publisher(monkeypatch):
    content = sermon()
    page_html = f"<!doctype html><title>{content['title']}</title><body>{publisher().static_heading_html(content)}</body>"
    fake_site(monkeypatch, content, page_html)
    gate = gate_module.Gate()
    gate_module.check_page_heading(gate, "https://example.test", {"id": "page-1"}, "zh-Hans")
    assert not gate.failed, gate.checks


def test_gate_rejects_a_page_missing_series_and_scripture(monkeypatch):
    content = sermon()
    fake_site(monkeypatch, content, "<body><h1>耶稣必再来</h1><p>2026-11-22 · Eric Geiger</p></body>")
    gate = gate_module.Gate()
    gate_module.check_page_heading(gate, "https://example.test", {"id": "page-1"}, "zh-Hans")
    assert [c["check"] for c in gate.failed] == ["zh-Hans.page.heading"]
    assert "series" in gate.failed[0]["detail"] and "scripture" in gate.failed[0]["detail"]


def test_web_and_python_rules_match():
    """The JS rule in catalog.mjs mirrors page_heading.heading_lines; keep the cases in step."""
    source = (ROOT / "apps/listening-web/catalog.mjs").read_text(encoding="utf-8")
    assert "export function headingLines(title, series)" in source
