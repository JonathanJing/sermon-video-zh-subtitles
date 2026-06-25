#!/usr/bin/env python3
"""Runtime-probe the public caption view's realtime event handling."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP_JS = REPO_ROOT / "web" / "app.js"


def main() -> int:
    args = parse_args()
    report = validate_public_caption_view_runtime(args.app_js, node_bin=args.node_bin)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-js", type=Path, default=DEFAULT_APP_JS)
    parser.add_argument("--node-bin", default="node")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def validate_public_caption_view_runtime(app_js: Path, *, node_bin: str = "node") -> dict[str, Any]:
    path = resolve_repo_path(app_js)
    checks: list[dict[str, Any]] = []
    if not path.is_file():
        checks.append(check("app_js_readable", False, {"appJs": str(app_js)}))
        return report_from_checks(app_js, checks, probe=None)
    checks.append(check("app_js_readable", True, {"appJs": str(app_js)}))

    try:
        probe = run_node_probe(path, node_bin=node_bin)
    except subprocess.CalledProcessError as exc:
        checks.append(
            check(
                "node_runtime_probe",
                False,
                {
                    "error": str(exc)[:300],
                    "stderr": (exc.stderr or "")[-1000:],
                    "stdout": (exc.stdout or "")[-1000:],
                },
            )
        )
        return report_from_checks(app_js, checks, probe=None)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        checks.append(check("node_runtime_probe", False, {"error": str(exc)[:300]}))
        return report_from_checks(app_js, checks, probe=None)

    checks.append(check("node_runtime_probe", probe.get("status") == "ok", probe))
    checks.append(
        check(
            "public_sse_subscription_registered",
            {"caption_delta", "caption_stable"}.issubset(set(probe.get("eventSourceListeners") or [])),
            {"eventSourceListeners": probe.get("eventSourceListeners") or []},
        )
    )
    checks.append(
        check(
            "realtime_draft_visible",
            probe.get("draftCaption") == "神爱世人",
            {"draftCaption": probe.get("draftCaption")},
        )
    )
    checks.append(
        check(
            "realtime_stable_commit_visible",
            probe.get("stableCommitCaption") == "神爱世人。",
            {"stableCommitCaption": probe.get("stableCommitCaption")},
        )
    )
    checks.append(
        check(
            "stable_correction_replaces_draft",
            probe.get("stableCaption") == "神爱世人。",
            {"stableCaption": probe.get("stableCaption")},
        )
    )
    checks.append(
        check(
            "english_delta_saved_in_segment",
            probe.get("segmentEn") == "God loved the world",
            {"segmentEn": probe.get("segmentEn")},
        )
    )
    checks.append(
        check(
            "stable_segment_marked",
            probe.get("segmentStable") is True and probe.get("segmentSourceMode") == "openai-realtime",
            {
                "segmentStable": probe.get("segmentStable"),
                "segmentSourceMode": probe.get("segmentSourceMode"),
            },
        )
    )
    checks.append(
        check(
            "admin_realtime_stage_history_visible",
            probe.get("segmentRealtimeStages") == ["draft", "stable", "final"]
            and "草稿 / 稳定 / 最终" in str(probe.get("segmentListHtml") or ""),
            {
                "segmentRealtimeStages": probe.get("segmentRealtimeStages"),
                "segmentListHtml": probe.get("segmentListHtml"),
            },
        )
    )
    checks.append(
        check(
            "stable_window_retained_on_segment",
            probe.get("stableWindowSegmentId") == "seg_runtime_1",
            {
                "stableWindowReceived": probe.get("stableWindowReceived"),
                "stableWindowSegmentId": probe.get("stableWindowSegmentId"),
            },
        )
    )
    checks.append(
        check(
            "no_secret_material",
            not contains_secret_material(json.dumps(probe, ensure_ascii=False)),
            None,
        )
    )
    return report_from_checks(app_js, checks, probe=probe)


def run_node_probe(app_js: Path, *, node_bin: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        probe_path = Path(tmp) / "public-caption-runtime-probe.js"
        probe_path.write_text(build_probe_js(app_js), encoding="utf-8")
        completed = subprocess.run(
            [node_bin, str(probe_path)],
            check=True,
            text=True,
            capture_output=True,
        )
    return json.loads(completed.stdout)


def build_probe_js(app_js: Path) -> str:
    return f"""
const fs = require("fs");
const vm = require("vm");

class ClassList {{
  constructor() {{ this.values = new Set(); }}
  add(value) {{ this.values.add(value); }}
  remove(value) {{ this.values.delete(value); }}
  toggle(value, force) {{
    const enabled = force === undefined ? !this.values.has(value) : Boolean(force);
    if (enabled) this.values.add(value);
    else this.values.delete(value);
    return enabled;
  }}
  contains(value) {{ return this.values.has(value); }}
}}

class Element {{
  constructor(id = "") {{
    this.id = id;
    this.textContent = "";
    this.value = "";
    this.dataset = {{}};
    this.style = {{ setProperty() {{}} }};
    this.classList = new ClassList();
    this.children = [];
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 200;
  }}
  addEventListener() {{}}
  appendChild(child) {{
    this.children.push(child);
    this.scrollHeight = this.children.length * 32;
    return child;
  }}
  prepend(child) {{
    this.children.unshift(child);
    this.scrollHeight = this.children.length * 32;
    return child;
  }}
  querySelector() {{ return new Element(); }}
  querySelectorAll() {{ return []; }}
  closest() {{ return null; }}
}}

const elements = new Map();
function getElement(id) {{
  if (!elements.has(id)) elements.set(id, new Element(id));
  return elements.get(id);
}}

const eventSources = [];
class FakeEventSource {{
  constructor(url) {{
    this.url = url;
    this.listeners = {{}};
    this.closed = false;
    eventSources.push(this);
  }}
  addEventListener(type, handler) {{ this.listeners[type] = handler; }}
  close() {{ this.closed = true; }}
}}

const document = {{
  title: "",
  body: new Element("body"),
  documentElement: new Element("html"),
  getElementById: getElement,
  createElement: (tag) => new Element(tag),
  querySelector: (selector) => selector === ".app-shell" ? getElement("shell") : new Element(selector),
  querySelectorAll: () => [],
  addEventListener() {{}}
}};

const window = {{
  document,
  location: {{ search: "", pathname: "/" }},
  innerWidth: 1280,
  innerHeight: 720,
  devicePixelRatio: 1,
  screen: {{ width: 1280, height: 720 }},
  EventSource: FakeEventSource,
  SERMON_PLAYBACK_SIMULATION: undefined,
  SERMON_SCRIPTURE_CMN_CU89S: {{}},
  localStorage: {{ getItem() {{ return null; }}, setItem() {{}} }},
  sessionStorage: {{ getItem() {{ return null; }}, setItem() {{}} }},
  crypto: {{ randomUUID() {{ return "runtime-probe-id"; }} }},
  setTimeout() {{ return 0; }},
  clearTimeout() {{}},
  setInterval() {{ return 0; }},
  clearInterval() {{}},
  URL,
  Blob
}};
window.window = window;
window.navigator = {{
  language: "zh-CN",
  sendBeacon() {{ return true; }},
  mediaDevices: {{ getUserMedia() {{ throw new Error("not used"); }} }}
}};
window.fetch = () => Promise.resolve({{ ok: true, json: () => Promise.resolve({{}}) }});

const context = {{
  window,
  document,
  navigator: window.navigator,
  URL,
  Blob,
  console: {{ log() {{}}, warn() {{}}, error() {{}} }},
  Intl,
  Date,
  Math,
  Set,
  Map,
  Promise,
  URLSearchParams,
  EventSource: FakeEventSource,
  clearTimeout: window.clearTimeout,
  setTimeout: window.setTimeout,
  clearInterval: window.clearInterval,
  setInterval: window.setInterval,
  fetch: window.fetch
}};
context.globalThis = window;

vm.runInNewContext(fs.readFileSync({json.dumps(str(app_js))}, "utf8"), context, {{ filename: "app.js" }});
const app = window.SermonCaptionPrototype;
app.pushRealtimeEvent({{
  type: "input_transcript_delta",
  segmentId: "seg_runtime_1",
  text: "God loved the world",
  en: "God loved the world",
  delta: "God loved the world",
  source: "openai-realtime-webrtc"
}});
app.pushRealtimeEvent({{
  type: "caption_delta",
  segmentId: "seg_runtime_1",
  text: "神爱世人",
  zh: "神爱世人",
  delta: "神爱世人",
  source: "openai-realtime-webrtc"
}});
const draftCaption = getElement("stableCaption").textContent;
app.pushRealtimeEvent({{
  type: "caption_stable",
  segmentId: "seg_runtime_1",
  text: "神爱世人。",
  zh: "神爱世人。",
  en: "God loved the world",
  final: false,
  source: "realtime-caption-stabilizer",
  stability: "stable",
  stabilizerWindow: {{
    windowMs: 8000,
    segmentId: "seg_runtime_1",
    sourceEventIds: [1, 2],
    inputTextEn: "God loved the world",
    draftZh: "神爱世人。"
  }}
}});
const stableCommitCaption = getElement("stableCaption").textContent;
app.pushRealtimeEvent({{
  type: "caption_final",
  segmentId: "seg_runtime_1",
  text: "神爱世人。",
  zh: "神爱世人。",
  en: "God loved the world",
  final: true,
  source: "gpt-5.4-mini-stable-correction",
  model: "gpt-5.4-mini"
}});
const segment = app.state.segments.find((item) => item.id === "seg_runtime_1") || {{}};
process.stdout.write(JSON.stringify({{
  status: "ok",
  eventSourceUrl: eventSources[0] ? eventSources[0].url : null,
  eventSourceListeners: eventSources[0] ? Object.keys(eventSources[0].listeners) : [],
  draftCaption,
  stableCommitCaption,
  stableCaption: getElement("stableCaption").textContent,
  stableWindowReceived: segment.stable === true,
  previousCaption: getElement("draftCaption").textContent,
  segmentCount: app.state.segments.length,
  segmentId: segment.id,
  segmentZh: segment.zh,
  segmentEn: segment.en,
  segmentStable: segment.stable === true,
  segmentRealtimeStage: segment.realtimeStage,
  segmentRealtimeStages: segment.realtimeStages || [],
  segmentListText: getElement("segmentList").textContent,
  segmentListHtml: getElement("segmentList").children.map((child) => child.innerHTML || child.textContent || "").join("\\n"),
  stableWindowSegmentId: segment.stabilizerWindow ? segment.stabilizerWindow.segmentId : null,
  segmentSourceMode: segment.sourceMode,
  apiKeyMaterialIncluded: false,
  secretResourceNamesIncluded: false,
  eventTokenIncluded: false,
  clientSecretIncluded: false
}}));
"""


def report_from_checks(app_js: Path, checks: list[dict[str, Any]], probe: dict[str, Any] | None) -> dict[str, Any]:
    failed = [item for item in checks if item["state"] != "pass"]
    return {
        "schemaVersion": 1,
        "status": "ok" if not failed else "failed",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "appJs": str(app_js),
        "checks": checks,
        "failedChecks": [item["name"] for item in failed],
        "probe": probe,
        "models": {
            "realtimeDraft": "gpt-realtime-translate",
            "stableCorrection": "gpt-5.4-mini",
        },
        "path": "public caption view receives realtime session events and replaces draft with stable correction",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
        "clientSecretIncluded": False,
    }


def check(name: str, passed: bool, observed: Any) -> dict[str, Any]:
    return {"name": name, "state": "pass" if passed else "fail", "observed": observed}


def contains_secret_material(text: str) -> bool:
    return any(needle in text for needle in ["OPENAI_API_KEY", "projects/", "/secrets/", "sk-", "Bearer "])


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
