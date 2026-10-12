#!/usr/bin/env python3
"""Browser smoke for a published week: open the reader for each locale in a real
headless Chrome, watch what the page actually did, and bind it to the requested
release.

For every locale the page is loaded as ``<origin>/?week=<pageId>&contentLang=<locale>``
by ``scripts/smoke_browser_cdp.mjs``, which observes the browser over the DevTools
protocol and sends no request of its own. The smoke requires, for that locale:

- the page is the requested one: the URL keeps ``week`` and ``contentLang``, the
  content-language selector shows the locale, the ``<audio>`` source is the
  release's own audio asset, the title starts with that locale's content title,
  and the rendered caption and full text come from that locale's cues;
- no ``console.error``/``console.assert`` call, no uncaught exception, and no
  failed load of a shell file or of this release's assets;
- the page's own ``/api/session`` requests all answer 200 (the 2026-10-11 release
  failed here: its feedback catalog was never synced);
- the browser finished within the deadline.

Failed loads of other resources (optional probes such as another page's alignment
index) are reported as warnings, not hidden. The report is evidence of the deployed
page in one browser; it is not device or venue acceptance and does not replace
HTTP asset verification.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "sermon-published-page-browser-smoke-v2"
DEFAULT_BROWSER = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_OBSERVER = ROOT / "scripts" / "smoke_browser_cdp.mjs"
LOCALES = ("zh-Hans", "ko", "es")
# What the reader shows before any cue is loaded.
CAPTION_PLACEHOLDERS = ("配音就绪后，字幕会显示在这里。", "")


def shell_paths() -> set[str]:
    """The reader shell a release ships (see build_full_video_app_release.runtime_web_files)."""
    from scripts.build_full_video_app_release import RUNTIME_WEB_FILES
    return {"/", "/index.html"} | {"/" + name for name in RUNTIME_WEB_FILES}


def fetch_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Cache-Control": "no-cache"}), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def expected_identity(origin: str, page: dict, locale: str, release: dict, fetch, timeout: float) -> dict:
    """What a correct rendering of this page in this locale must show, read from its release."""
    assets = {row["role"]: row for row in release.get("assets", []) if isinstance(row, dict)}
    if release.get("pageId") != page["id"] or release.get("targetLocale") != locale or any(
            role not in assets for role in ("audio", "content", "captions")):
        raise ValueError(f"Release for {page['id']} {locale} lacks its identity or audio, content and captions")
    content = fetch(origin + assets["content"]["path"], timeout)
    captions = fetch(origin + assets["captions"]["path"], timeout)
    texts = [cue.get("text", "").strip() for cue in content.get("cues", []) + captions.get("cues", [])]
    return {"pageId": page["id"], "locale": locale, "title": content.get("title", "").strip(),
            "audioPath": assets["audio"]["path"], "cueTexts": {text for text in texts if text},
            "firstCueTexts": [cue.get("text", "").strip() for cue in content.get("cues", [])[:3]],
            "requiredPaths": {row["path"] for row in assets.values()} | {"/multilingual-v4.json"}}


def evaluate(expected: dict, observed: dict, *, required_paths: set[str], check_session: bool = True) -> tuple[list[str], list[str]]:
    """``(problems, warnings)`` for one locale's observation."""
    problems, warnings = [], []
    if observed.get("status") != "ok":
        return [f"browser did not finish: {observed.get('status')} ({observed.get('reason', 'no reason')})"], warnings
    dom = observed.get("dom") or {}
    if dom.get("week") != expected["pageId"] or dom.get("contentLang") != expected["locale"]:
        problems.append(f"page left the requested week/locale: week={dom.get('week')!r} contentLang={dom.get('contentLang')!r}")
    if dom.get("contentLanguage") not in (None, expected["locale"]):
        problems.append(f"content language selector shows {dom.get('contentLanguage')!r}")
    audio = urlsplit(dom.get("audioSrc") or "").path
    if audio != expected["audioPath"]:
        problems.append(f"audio is {audio or 'missing'!s}, not this release's {expected['audioPath']}")
    title = (dom.get("title") or "").strip()
    if not expected["title"] or not title.startswith(expected["title"] + " · "):
        problems.append(f"title {title!r} does not name this locale's sermon {expected['title']!r}")
    caption = (dom.get("captionText") or "").strip()
    if caption not in CAPTION_PLACEHOLDERS and caption not in expected["cueTexts"]:
        problems.append(f"caption {caption[:40]!r} is not one of this release's cues")
    reading = dom.get("fullReading") or ""
    if not any(text and text in reading for text in expected["firstCueTexts"]):
        problems.append("full text does not show this release's opening cues")
    for error in observed.get("consoleErrors", []):
        path = urlsplit(error.get("source") or "").path
        if path == "/api/session":
            continue  # judged from the session responses below
        if error.get("kind", "").startswith("log.") and error.get("kind") != "log.javascript" and path not in required_paths:
            warnings.append(f"optional resource failed: {path or error.get('source')}: {error.get('message', '')[:80]}")
        else:
            problems.append(f"{error.get('kind')}: {error.get('message', '')[:120]} ({path or 'no source'})")
    if check_session:
        sessions = observed.get("sessionRequests") or []
        if not sessions:
            problems.append("the page made no /api/session request")
        elif any(row.get("status") == 429 for row in sessions):
            problems.append("/api/session rate-limited (429): too many sessions from this address; rerun one smoke at a time")
        elif any(row.get("status") != 200 for row in sessions):
            problems.append("/api/session answered " + ", ".join(str(row.get("status")) for row in sessions))
    return problems, warnings


def load_in_browser(browser: str, url: str, *, settle_ms: int, deadline_ms: int) -> dict:
    """The CDP observer's JSON; a crash or unparsable output is an error observation."""
    command = ["node", str(CDP_OBSERVER), "--browser", browser, "--url", url,
               "--settle-ms", str(settle_ms), "--deadline-ms", str(deadline_ms)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=deadline_ms / 1000 + 15)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": "observer did not exit"}
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"status": "error", "reason": f"observer exit {completed.returncode}: {completed.stderr.strip()[:200]}"}


def smoke(origin: str, page_id: str, locales, *, browser: str, settle_ms: int = 4000, deadline_ms: int = 60000,
          timeout: float = 60, check_session: bool = True, loader=load_in_browser, fetch=fetch_json,
          shell=shell_paths) -> dict:
    catalog = fetch(origin + "/multilingual-v4.json", timeout)
    page = next((row for row in catalog.get("pages", []) if row.get("id") == page_id), None)
    if page is None:
        raise ValueError(f"Page {page_id} is not in the live v4 catalog")
    shell_files = shell()
    results = []
    for locale in locales:
        target = page["targets"].get(locale)
        if target is None:
            results.append({"locale": locale, "status": "fail", "problems": ["locale is not published for this page"], "warnings": []})
            continue
        release = fetch(origin + target["releasePackageUrl"], timeout)
        expected = expected_identity(origin, page, locale, release, fetch, timeout)
        url = f"{origin}/?week={page_id}&contentLang={locale}"
        observed = loader(browser, url, settle_ms=settle_ms, deadline_ms=deadline_ms)
        problems, warnings = evaluate(expected, observed, check_session=check_session,
                                      required_paths=expected["requiredPaths"] | {target["releasePackageUrl"]} | shell_files)
        dom = observed.get("dom") or {}
        results.append({"locale": locale, "url": url, "status": "pass" if not problems else "fail",
                        "problems": problems, "warnings": warnings, "browserStatus": observed.get("status"),
                        "elapsedMs": observed.get("elapsedMs"), "title": dom.get("title"), "audioSrc": dom.get("audioSrc"),
                        "captionText": (dom.get("captionText") or "")[:120], "consoleErrors": observed.get("consoleErrors", []),
                        "sessionRequests": observed.get("sessionRequests", [])})
    return {"schemaVersion": SCHEMA, "checkedAt": datetime.now(timezone.utc).isoformat(), "origin": origin,
            "pageId": page_id, "browser": browser, "settleMs": settle_ms, "deadlineMs": deadline_ms,
            "status": "pass" if all(row["status"] == "pass" for row in results) else "fail",
            "locales": results, "scope": "browser_render_and_feedback_session_only"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origin", required=True, help="https://… site origin (production or Dev)")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--locale", action="append", default=[], help="Repeatable; default zh-Hans, ko, es")
    parser.add_argument("--browser", default=DEFAULT_BROWSER, help="Chrome or Chromium binary")
    parser.add_argument("--settle-ms", type=int, default=4000, help="Wait after the load event before reading the page")
    parser.add_argument("--deadline-ms", type=int, default=60000, help="Hard limit per locale; exceeding it fails the smoke")
    parser.add_argument("--no-session", action="store_true", help="Do not require the page's /api/session requests to answer 200")
    parser.add_argument("--out", type=Path, required=True, help="JSON report; refuses to overwrite")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("report already exists: " + str(args.out))
    if not Path(args.browser).is_file():
        parser.error("browser binary not found: " + args.browser)
    origin = args.origin.rstrip("/")
    if not origin.startswith("https://"):
        parser.error("origin must be https://")
    report = smoke(origin, args.page_id, args.locale or LOCALES, browser=args.browser, settle_ms=args.settle_ms,
                   deadline_ms=args.deadline_ms, check_session=not args.no_session)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for row in report["locales"]:
        print(f"{row['locale']}\t{row['status']}\t{row.get('title') or ''}\t{'; '.join(row['problems'])}")
        for warning in row.get("warnings", []):
            print(f"\twarning: {warning}")
    print(json.dumps({"status": report["status"], "report": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
