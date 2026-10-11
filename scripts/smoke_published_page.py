#!/usr/bin/env python3
"""Browser smoke for a published week: open the reader for each locale in a real
headless Chrome, and check what a visitor would see.

For every locale the page is loaded as ``<origin>/?week=<pageId>&contentLang=<locale>``
and the smoke requires: the document title names the sermon (not only the brand),
the subtitle area or the full reading list carries text, Chrome logged no
console error, and ``/api/session`` accepts the reader's own feedback source for
that locale's audio (the 2026-10-11 release failed exactly here: the shell was
stale and the feedback catalog was never synced). The ``/api/session`` check
mints one anonymous feedback session per locale, as a visitor's first page view
does.

The report is evidence of the deployed page in a browser; it is not device or
venue acceptance and does not replace HTTP asset verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

SCHEMA = "sermon-published-page-browser-smoke-v1"
DEFAULT_BROWSER = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LOCALES = ("zh-Hans", "ko", "es")
# What the reader shows before any cue is loaded; the smoke must see something else.
CAPTION_PLACEHOLDERS = ("配音就绪后，字幕会显示在这里。", "")
CONSOLE_ERROR = re.compile(r':ERROR:CONSOLE\(\d+\)\]\s*"(.*)"(?:, source: (\S+) \((\d+)\))?')


class _Text(HTMLParser):
    """Collect the text of <title> and of a few elements by id."""

    def __init__(self, ids):
        super().__init__()
        self.wanted = set(ids)
        self.text = {name: "" for name in ids}
        self.title = ""
        self._stack = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "title":
            self._in_title = True
        element = attributes.get("id")
        self._stack.append(element if element in self.wanted else None)
        # Count how deep we are inside a wanted element; nested wanted ids are rare.

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        for element in self._stack:
            if element:
                self.text[element] += data


def inspect_dom(document: str) -> dict:
    """Title and the visible text of the subtitle area and full reading list."""
    parser = _Text(("current-text", "full-reading-list", "edition-label"))
    parser.feed(document)
    caption = " ".join(parser.text["current-text"].split())
    reading = " ".join(parser.text["full-reading-list"].split())
    return {"title": " ".join(parser.title.split()), "captionText": caption[:120],
            "fullReadingChars": len(reading), "editionLabel": " ".join(parser.text["edition-label"].split())}


def console_errors(log: str) -> list[dict]:
    """Chrome's stderr console errors: ``[pid:tid:date:ERROR:CONSOLE(line)] "message", source: url (line)``."""
    errors = []
    for line in log.splitlines():
        match = CONSOLE_ERROR.search(line)
        if match:
            message, source, line_number = match.groups()
            errors.append({"message": message[:500], "source": source, "line": int(line_number) if line_number else None})
    return errors


def feedback_source(catalog: dict, release: dict, engagement: dict, locale: str) -> dict:
    """The source the reader posts to /api/session: published-weeks.mjs builds the
    track id as ``<pageId>-<locale>-<first 12 hex of the audio sha>``, feedback
    keeps the week date, and appVersion comes from /engagement.json."""
    page = next(page for page in catalog["pages"] if page["id"] == release["pageId"])
    audio = next(row for row in release["assets"] if row["role"] == "audio")
    if not re.fullmatch(r"[a-f0-9]{64}", audio["sha256"]) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", page["date"]):
        raise ValueError("Release package does not carry a bound audio hash and week date")
    return {"schemaVersion": 1, "week": page["date"], "trackId": f"{page['id']}-{locale}-{audio['sha256'][:12]}",
            "audioSha256": audio["sha256"], "appVersion": engagement["appVersion"]}


def evaluate(dom: dict, errors: list[dict], session_status: int | None, brand: str = "同行") -> list[str]:
    problems = []
    title = dom["title"]
    if not title or title.replace(brand, "").strip(" ·") == "" or "正在" in title:
        problems.append(f"title does not name the sermon: {title!r}")
    if dom["captionText"] in CAPTION_PLACEHOLDERS and dom["fullReadingChars"] == 0:
        problems.append("no subtitle or full reading text was rendered")
    if errors:
        problems.append(f"{len(errors)} console error(s): " + "; ".join(e["message"][:120] for e in errors[:3]))
    if session_status is not None and session_status != 200:
        problems.append(f"/api/session answered HTTP {session_status}")
    return problems


def fetch_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Cache-Control": "no-cache"}), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_session(origin: str, source: dict, timeout: float) -> int:
    # The API only serves its own origin, so the smoke speaks as the page would.
    request = urllib.request.Request(origin + "/api/session", data=json.dumps(source).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Origin": origin,
                                              "Referer": origin + "/"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def load_in_browser(browser: str, url: str, *, budget_ms: int, timeout: float) -> tuple[str, str]:
    """``(dom, log)`` after Chrome ran the page for ``budget_ms`` of virtual time."""
    with tempfile.TemporaryDirectory(prefix="sermon-smoke-") as profile:
        command = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--disable-background-networking", "--disable-sync", "--disable-extensions",
                   "--enable-logging=stderr", "--v=0", f"--virtual-time-budget={budget_ms}",
                   "--user-data-dir=" + profile, "--dump-dom", url]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            out, err = process.communicate()
            err += b"\n[smoke] browser deadline exceeded"
        return out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def smoke(origin: str, page_id: str, locales, *, browser: str, budget_ms: int = 20000, timeout: float = 90,
          check_session: bool = True, loader=load_in_browser, fetch=fetch_json, post=post_session) -> dict:
    catalog = fetch(origin + "/multilingual-v4.json", timeout)
    engagement = fetch(origin + "/engagement.json", timeout) if check_session else None
    page = next((row for row in catalog.get("pages", []) if row.get("id") == page_id), None)
    if page is None:
        raise ValueError(f"Page {page_id} is not in the live v4 catalog")
    results = []
    for locale in locales:
        target = page["targets"].get(locale)
        if target is None:
            results.append({"locale": locale, "status": "fail", "problems": ["locale is not published for this page"]})
            continue
        release = fetch(origin + target["releasePackageUrl"], timeout)
        url = f"{origin}/?week={page_id}&contentLang={locale}"
        dom_text, log = loader(browser, url, budget_ms=budget_ms, timeout=timeout)
        dom = inspect_dom(dom_text)
        errors = console_errors(log)
        session_status = post(origin, feedback_source(catalog, release, engagement, locale), timeout) if check_session else None
        problems = evaluate(dom, errors, session_status)
        results.append({"locale": locale, "url": url, "status": "pass" if not problems else "fail", **dom,
                        "consoleErrors": errors, "sessionStatus": session_status, "problems": problems,
                        "domSha256": hashlib.sha256(dom_text.encode("utf-8")).hexdigest()})
    return {"schemaVersion": SCHEMA, "checkedAt": datetime.now(timezone.utc).isoformat(), "origin": origin,
            "pageId": page_id, "browser": browser, "virtualTimeBudgetMs": budget_ms,
            "status": "pass" if all(row["status"] == "pass" for row in results) else "fail",
            "locales": results, "scope": "browser_render_and_feedback_session_only"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origin", required=True, help="https://… site origin (production or Dev)")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--locale", action="append", default=[], help="Repeatable; default zh-Hans, ko, es")
    parser.add_argument("--browser", default=DEFAULT_BROWSER, help="Chrome or Chromium binary")
    parser.add_argument("--virtual-time-budget-ms", type=int, default=20000)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--no-session", action="store_true", help="Skip the /api/session check")
    parser.add_argument("--out", type=Path, required=True, help="JSON report; refuses to overwrite")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("report already exists: " + str(args.out))
    if not Path(args.browser).is_file():
        parser.error("browser binary not found: " + args.browser)
    origin = args.origin.rstrip("/")
    if not origin.startswith("https://"):
        parser.error("origin must be https://")
    report = smoke(origin, args.page_id, args.locale or LOCALES, browser=args.browser,
                   budget_ms=args.virtual_time_budget_ms, timeout=args.timeout_seconds,
                   check_session=not args.no_session)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for row in report["locales"]:
        print(f"{row['locale']}\t{row['status']}\t{row.get('title', '')}\t{'; '.join(row['problems'])}")
    print(json.dumps({"status": report["status"], "report": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
