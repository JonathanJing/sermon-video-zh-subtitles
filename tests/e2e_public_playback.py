#!/usr/bin/env python3
"""Repeatable browser validation for the public playback prototype.

By default this serves ./web locally. Pass --base-url to validate a deployed
Cloud Run URL without starting a local server.
"""

from __future__ import annotations

import argparse
import http.server
import json
import re
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import expect, sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"
SECRET_RESOURCE_RE = re.compile(
    r"projects/[^/\"'\s]+/secrets/[^/\"'\s]+(?:/versions/[^/\"'\s]+)?"
)
FORBIDDEN_PATTERNS = [
    ("apiKeySecret", re.compile(r"apiKeySecret")),
    ("Secret Manager resource name", SECRET_RESOURCE_RE),
    ("OpenAI raw key", re.compile(r"sk-[A-Za-z0-9_-]{12,}")),
    ("Google API raw key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
]


VIEWPORTS = [
    ("iphone-portrait", 390, 844),
    ("ipad-landscape", 1024, 768),
    ("desktop", 1366, 900),
]


def main() -> int:
    args = parse_args()
    with maybe_local_server(args.base_url) as base_url:
        results = run_browser_checks(base_url, headed=args.headed)
    print(
        json.dumps(
            {"status": "ok", "baseUrl": base_url, "results": results},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        help="Existing site URL to validate, e.g. a Cloud Run deployment.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window for debugging.",
    )
    return parser.parse_args()


@contextmanager
def maybe_local_server(base_url: str | None) -> Iterator[str]:
    if base_url:
        yield base_url.rstrip("/")
        return

    port = free_port()
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *args,
        directory=str(WEB_ROOT),
        **kwargs,
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_browser_checks(base_url: str, headed: bool = False) -> list[dict[str, object]]:
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        try:
            for name, width, height in VIEWPORTS:
                page = browser.new_page(
                    viewport={"width": width, "height": height},
                    is_mobile=name.startswith("iphone"),
                )
                page.goto(base_url, wait_until="networkidle")
                check_disclaimer(page)
                check_public_controls_hidden(page)
                check_no_horizontal_overflow(page)
                check_public_playback(page)
                check_public_layout_bounds(page)
                results.append({"viewport": name, "width": width, "height": height, "ok": True})
                page.close()

            autoplay_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
            autoplay_page.goto(base_url.rstrip("/") + "/?autoplay=1", wait_until="networkidle")
            check_public_playback(autoplay_page)
            check_public_layout_bounds(autoplay_page)
            results.append({"viewport": "iphone-autoplay-param", "width": 390, "height": 844, "ok": True})
            autoplay_page.close()

            operator_page = browser.new_page(viewport={"width": 1366, "height": 900})
            operator_page.goto(base_url.rstrip("/") + "/?mode=operator", wait_until="networkidle")
            check_operator_mode(operator_page)
            check_playback(operator_page)
            results.append({"viewport": "operator-desktop", "width": 1366, "height": 900, "ok": True})
            operator_page.close()

            js_text = fetch_text(base_url.rstrip("/") + "/playback-simulation.generated.js")
            check_sanitized_text(js_text, "playback-simulation.generated.js")
            results.append({"artifact": "playback-simulation.generated.js", "ok": True})
        finally:
            browser.close()
    return results


def check_disclaimer(page) -> None:
    disclaimer = page.locator(".viewer-disclaimer")
    expect(disclaimer).to_be_visible()
    text = disclaimer.inner_text()
    if "AI 辅助生成" not in text or "讲员原文" not in text:
        raise AssertionError(f"Disclaimer text is incomplete: {text!r}")


def check_public_controls_hidden(page) -> None:
    body_text = page.locator("body").inner_text(timeout=5000)
    forbidden_visible_text = [
        "Admin Settings",
        "会前字幕源监控",
        "手动触发",
        "模拟播放",
        "导出 VTT",
        "导出 SRT",
        "运行日志",
        "冻结并发布",
        "时间轴平移",
    ]
    leaked = [text for text in forbidden_visible_text if text in body_text]
    if leaked:
        raise AssertionError(f"Public congregation view exposes operator controls: {leaked}")

    for selector in [
        ".control-panel",
        ".timeline-panel",
        "[data-action='start-playback']",
        "[data-action='trigger-manual-ingest']",
        "[data-action='export-vtt']",
    ]:
        expect(page.locator(selector)).to_be_hidden()


def check_no_horizontal_overflow(page) -> None:
    offenders = page.evaluate(
        """
        () => {
          const viewportWidth = document.documentElement.clientWidth;
          const offenders = [];
          for (const el of document.body.querySelectorAll("*")) {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && (rect.left < -1 || rect.right > viewportWidth + 1)) {
              offenders.push({
                tag: el.tagName.toLowerCase(),
                id: el.id || "",
                className: typeof el.className === "string" ? el.className : "",
                left: Math.round(rect.left),
                right: Math.round(rect.right),
                width: Math.round(rect.width),
                text: (el.innerText || el.textContent || "").trim().slice(0, 80)
              });
            }
          }
          return {
            viewportWidth,
            documentScrollWidth: document.documentElement.scrollWidth,
            bodyScrollWidth: document.body.scrollWidth,
            offenders
          };
        }
        """
    )
    if offenders["documentScrollWidth"] > offenders["viewportWidth"] + 1 or offenders["offenders"]:
        raise AssertionError(f"Horizontal overflow detected: {json.dumps(offenders, ensure_ascii=False)}")


def check_public_playback(page) -> None:
    expect(page.locator("#generationStatus")).to_contain_text("已加载", timeout=5000)
    expect(page.locator("#segmentCount")).not_to_have_text("0 segments", timeout=5000)
    stable_caption = page.locator("#stableCaption").inner_text(timeout=5000)
    if not stable_caption or "请先确认字幕源" in stable_caption:
        raise AssertionError(f"Public playback did not render a usable caption: {stable_caption!r}")
    runtime_state = page.evaluate(
        """
        () => ({
          captioning: window.SermonCaptionPrototype?.state?.captioning,
          playbackStartedAt: window.SermonCaptionPrototype?.state?.playbackStartedAt,
          playbackIndex: window.SermonCaptionPrototype?.state?.playbackIndex,
          segmentCount: window.SermonCaptionPrototype?.state?.segments?.length
        })
        """
    )
    if runtime_state["captioning"] or runtime_state["playbackStartedAt"]:
        raise AssertionError(f"Public page started playback on load: {runtime_state}")
    if runtime_state["segmentCount"] != runtime_state["playbackIndex"]:
        raise AssertionError(f"Public page did not load a static published snapshot: {runtime_state}")


def check_public_layout_bounds(page) -> None:
    layout = page.evaluate(
        """
        () => {
          const caption = document.querySelector("#captionWindow").getBoundingClientRect();
          const review = document.querySelector(".review-strip").getBoundingClientRect();
          const segmentList = document.querySelector("#segmentList");
          return {
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
            captionHeight: Math.round(caption.height),
            reviewHeight: Math.round(review.height),
            segmentClientHeight: segmentList.clientHeight,
            segmentScrollHeight: segmentList.scrollHeight,
            documentHeight: document.documentElement.scrollHeight
          };
        }
        """
    )
    caption_limit = max(460, int(layout["viewportHeight"] * 0.6))
    review_limit = max(260, int(layout["viewportHeight"] * 0.36))
    if layout["captionHeight"] > caption_limit:
        raise AssertionError(f"Caption window grew beyond viewport bounds: {layout}")
    if layout["reviewHeight"] > review_limit:
        raise AssertionError(f"Subtitle track grew beyond viewport bounds: {layout}")
    if layout["segmentScrollHeight"] > 0 and layout["segmentClientHeight"] <= 0:
        raise AssertionError(f"Subtitle track is not scrollable: {layout}")


def check_operator_mode(page) -> None:
    expect(page.locator(".control-panel")).to_be_visible()
    expect(page.locator("[data-action='trigger-manual-ingest']")).to_be_visible()
    expect(page.locator("[data-action='start-playback']")).to_be_visible()
    expect(page.locator("[data-action='export-vtt']")).to_be_visible()


def check_playback(page) -> None:
    page.locator("[data-action='start-playback']").click()
    expect(page.locator("#generationStatus")).to_contain_text("正在生成", timeout=3000)
    expect(page.locator("#segmentCount")).not_to_have_text("0 segments", timeout=5000)
    stable_caption = page.locator("#stableCaption").inner_text(timeout=5000)
    if not stable_caption or "请先确认字幕源" in stable_caption:
        raise AssertionError(f"Playback did not render a usable caption: {stable_caption!r}")


def fetch_text(url: str) -> str:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, urllib.request; "
                "print(urllib.request.urlopen(sys.argv[1], timeout=20).read().decode('utf-8'))"
            ),
            url,
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def check_sanitized_text(text: str, label: str) -> None:
    for name, pattern in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            raise AssertionError(f"{label} contains forbidden {name}.")


if __name__ == "__main__":
    raise SystemExit(main())
