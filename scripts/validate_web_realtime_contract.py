#!/usr/bin/env python3
"""Validate the browser WebRTC realtime-caption contract."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP_JS = REPO_ROOT / "web" / "app.js"


REQUIREMENTS = [
    {
        "name": "ipad_mic_capture",
        "description": "Browser captures iPad/iPhone microphone audio.",
        "needles": [
            "navigator.mediaDevices.getUserMedia",
            "echoCancellation",
            "noiseSuppression",
            "autoGainControl",
        ],
    },
    {
        "name": "openai_realtime_webrtc",
        "description": "Browser creates an OpenAI WebRTC translation session.",
        "needles": [
            "new RTCPeerConnection()",
            'pc.createDataChannel("oai-events")',
            'model: "gpt-realtime-translate"',
            'targetLanguage: "zh"',
            'audioSourceKind: "ipad_mic"',
            'source: "ipad-mic"',
            '"Authorization": `Bearer ${session.clientSecret.value}`',
        ],
    },
    {
        "name": "no_browser_speech_success_fallback",
        "description": "iPad/iPhone realtime success path does not fall back to browser speech recognition when OpenAI Realtime fails.",
        "needles": [
            "不使用浏览器本地听写代替 gpt-realtime-translate",
            'updateTestPassState("失败：Realtime 翻译未启动", "error")',
            'setStatus("Realtime 翻译未启动", "error")',
        ],
        "forbidden": [
            "OpenAI Realtime 未启动，退回浏览器本地听写测试",
            "await startBrowserSpeechMicFallback();",
        ],
    },
    {
        "name": "openai_event_normalization",
        "description": "OpenAI input/output transcript events become backend caption events.",
        "needles": [
            "function realtimeCaptionEventFromOpenAI(event)",
            "extractRealtimeTranscriptText(event)",
            'type.includes("input_transcript")',
            'type.includes("input_audio_transcription")',
            'type.includes("output_transcript")',
            'type.includes("audio_transcript")',
            '"input_transcript_delta"',
            '"caption_delta"',
            '"caption_final"',
            "payload.en = text",
            "payload.zh = text",
            'source: "openai-realtime-webrtc"',
        ],
    },
    {
        "name": "openai_nested_transcript_payloads",
        "description": "OpenAI realtime transcript extraction handles flat and nested payload shapes.",
        "needles": [
            "function extractRealtimeTranscriptText(event)",
            "event.input_transcript_delta",
            "event.output_transcript",
            "event.input_transcript?.delta",
            "event.output_transcript?.delta",
            "event.input_audio_transcription?.delta",
            'nestedRealtimeTranscriptValues(event.input_transcript, "delta")',
            "event.audio_transcript",
            'nestedRealtimeTranscriptValues(event.output_transcript, "delta")',
            'nestedRealtimeTranscriptValues(event.input_audio_transcription, "delta")',
            'nestedRealtimeTranscriptValues(event.response, "delta")',
            "function nestedRealtimeTranscriptValues(value, mode)",
            "event.part?.transcript",
            "event.item?.content",
            "event.response?.output",
            "function realtimeContentTexts(content)",
            "function realtimeOutputTexts(output)",
            "function realtimeSegmentIdFromOpenAI(event)",
        ],
    },
    {
        "name": "backend_delta_persistence",
        "description": "Normalized English input and Chinese output deltas are posted to the backend session archive.",
        "needles": [
            "postRealtimeSessionEvent(captionEvent)",
            "createRealtimeSession,",
            "handleRealtimeDataChannelMessage,",
            "postRealtimeSessionEvent,",
            'fetch(`/api/realtime/sessions/${encodeURIComponent(rt.sessionId)}/events`',
            '"X-Realtime-Event-Token": rt.eventToken',
            "keepalive: true",
            "response.ok",
            "backendPersistedEvents",
            "backendPersistFailures",
            "Realtime deltas 已保存",
            "后台保存 realtime delta 失败",
        ],
    },
    {
        "name": "public_caption_sse",
        "description": "Public caption view subscribes to the current realtime session SSE stream.",
        "needles": [
            "function connectPublicRealtimeEvents()",
            'new EventSource("/api/realtime/sessions/current/events")',
            '["caption_delta", "caption_final", "input_transcript_delta", "input_transcript_final"]',
            "handleRealtimeCaptionEvent(payload)",
        ],
    },
    {
        "name": "stable_correction_display",
        "description": "Delayed gpt-5.5-mini stable corrections replace realtime draft segments.",
        "needles": [
            'String(event.source || "").includes("stable-correction")',
            'segment.note = "gpt-5.5-mini 稳定修正版。"',
            "segment.stable = Boolean(segment.stable || isStableCorrection)",
        ],
    },
]


FORBIDDEN_REPORT_NEEDLES = [
    "OPENAI_API_KEY",
    "projects/",
    "/secrets/",
]


def main() -> int:
    args = parse_args()
    report = validate_web_realtime_contract(args.app_js, node_bin=args.node_bin)
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


def validate_web_realtime_contract(app_js: Path, *, node_bin: str = "node") -> dict[str, Any]:
    path = resolve_repo_path(app_js)
    checks: list[dict[str, Any]] = []
    if not path.is_file():
        checks.append(
            {
                "name": "app_js_readable",
                "description": "web/app.js is readable.",
                "state": "fail",
                "missing": [str(app_js)],
            }
        )
        source = ""
    else:
        source = path.read_text(encoding="utf-8", errors="replace")
        checks.append(
            {
                "name": "app_js_readable",
                "description": "web/app.js is readable.",
                "state": "pass",
                "missing": [],
            }
        )

    for requirement in REQUIREMENTS:
        missing = [needle for needle in requirement["needles"] if needle not in source]
        forbidden_present = [
            needle for needle in requirement.get("forbidden", []) if needle in source
        ]
        checks.append(
            {
                "name": requirement["name"],
                "description": requirement["description"],
                "state": "pass" if not missing and not forbidden_present else "fail",
                "missing": missing,
                "forbiddenPresent": forbidden_present,
            }
        )

    probe: dict[str, Any] | None = None
    if source:
        try:
            probe = run_normalization_probe(path, node_bin=node_bin)
            checks.append(
                {
                    "name": "openai_event_normalization_runtime",
                    "description": "Browser normalization maps representative OpenAI realtime transcript payloads to backend caption events.",
                    "state": "pass" if probe.get("status") == "ok" else "fail",
                    "observed": probe,
                }
            )
        except subprocess.CalledProcessError as exc:
            checks.append(
                {
                    "name": "openai_event_normalization_runtime",
                    "description": "Browser normalization maps representative OpenAI realtime transcript payloads to backend caption events.",
                    "state": "fail",
                    "observed": {
                        "error": str(exc)[:300],
                        "stderr": (exc.stderr or "")[-1000:],
                        "stdout": (exc.stdout or "")[-1000:],
                    },
                }
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            checks.append(
                {
                    "name": "openai_event_normalization_runtime",
                    "description": "Browser normalization maps representative OpenAI realtime transcript payloads to backend caption events.",
                    "state": "fail",
                    "observed": {"error": str(exc)[:300]},
                }
            )

    failed = [check for check in checks if check["state"] != "pass"]
    report = {
        "schemaVersion": 1,
        "status": "ok" if not failed else "failed",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "appJs": str(app_js),
        "checks": checks,
        "failedChecks": [check["name"] for check in failed],
        "normalizationProbe": probe,
        "models": {
            "realtimeDraft": "gpt-realtime-translate",
            "stableCorrection": "gpt-5.5-mini",
        },
        "path": "ipad/iphone mic -> browser WebRTC -> gpt-realtime-translate -> backend session events -> public caption SSE",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
        "clientSecretIncluded": False,
        "eventMappings": [
            {
                "sourceEvent": "session.output_transcript.delta",
                "backendEvent": "caption_delta",
                "publicView": "handleRealtimeCaptionEvent -> upsertRealtimeChineseSegment",
            },
            {
                "sourceEvent": "session.input_transcript.delta",
                "backendEvent": "input_transcript_delta",
                "publicView": "handleRealtimeCaptionEvent -> updateRealtimeEnglish",
            },
            {
                "sourceEvent": "gpt-5.5-mini stable correction",
                "backendEvent": "caption_final",
                "publicView": "same segmentId replaces realtime draft",
            },
        ],
    }
    enforce_report_sanitized(report)
    return report


def run_normalization_probe(app_js: Path, *, node_bin: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        probe_path = Path(tmp) / "web-realtime-normalization-probe.js"
        probe_path.write_text(build_normalization_probe_js(app_js), encoding="utf-8")
        completed = subprocess.run(
            [node_bin, str(probe_path)],
            check=True,
            text=True,
            capture_output=True,
        )
    return json.loads(completed.stdout)


def build_normalization_probe_js(app_js: Path) -> str:
    return f"""
const fs = require("fs");
const vm = require("vm");

class ClassList {{
  add() {{}}
  remove() {{}}
  toggle(_value, force) {{ return Boolean(force); }}
  contains() {{ return false; }}
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
  appendChild(child) {{ this.children.push(child); return child; }}
  prepend(child) {{ this.children.unshift(child); return child; }}
  querySelector() {{ return new Element(); }}
  querySelectorAll() {{ return []; }}
  closest() {{ return null; }}
}}

const elements = new Map();
function getElement(id) {{
  if (!elements.has(id)) elements.set(id, new Element(id));
  return elements.get(id);
}}

class FakeEventSource {{
  constructor(url) {{ this.url = url; this.listeners = {{}}; }}
  addEventListener(type, handler) {{ this.listeners[type] = handler; }}
  close() {{}}
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
  crypto: {{ randomUUID() {{ return "normalization-probe-id"; }} }},
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
	const fetchRequests = [];
	const probeEventToken = ["probe", "event", "token"].join("-");
	const probeClientSecret = ["probe", "client", "secret"].join("-");
	window.fetch = (url, options = {{}}) => {{
  const request = {{
    url: String(url),
    method: options.method || "GET",
    headers: options.headers || {{}},
    body: options.body ? JSON.parse(options.body) : null,
    keepalive: Boolean(options.keepalive)
  }};
  fetchRequests.push(request);
  if (String(url) === "/api/admin/realtime/sessions") {{
    return Promise.resolve({{
      ok: true,
      status: 201,
      json: () => Promise.resolve({{
	        status: "ready",
	        sessionId: "rt_probe",
	        eventToken: probeEventToken,
	        model: "gpt-realtime-translate",
	        targetLanguage: "zh",
	        audioSourceKind: "ipad_mic",
	        clientSecret: {{ value: probeClientSecret, expiresAt: 1893456000 }},
	        webrtc: {{ url: "https://api.openai.com/v1/realtime/translations/calls", model: "gpt-realtime-translate" }}
      }})
    }});
  }}
  if (String(url).startsWith("/api/realtime/sessions/")) {{
    return Promise.resolve({{
      ok: true,
      status: 202,
      json: () => Promise.resolve({{ status: "stored" }})
    }});
  }}
  return Promise.resolve({{ ok: true, status: 200, json: () => Promise.resolve({{}}) }});
}};

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

(async () => {{
const prototype = window.SermonCaptionPrototype;
const normalize = prototype.normalizeRealtimeOpenAIEvent;
const cases = [
  {{
    name: "output_delta",
    event: {{ type: "session.output_transcript.delta", delta: "神爱世人", item_id: "seg_1" }},
    expected: {{ type: "caption_delta", zh: "神爱世人", segmentId: "seg_1" }}
  }},
  {{
    name: "nested_output_done",
    event: {{
      type: "session.output_transcript.done",
      output_transcript: {{ text: "神爱世人。" }},
      response: {{ id: "seg_2" }}
    }},
    expected: {{ type: "caption_final", zh: "神爱世人。", segmentId: "seg_2", final: true }}
  }},
  {{
    name: "nested_input_delta",
    event: {{
      type: "session.input_audio_transcription.delta",
      input_audio_transcription: {{ delta: "God loved the world" }},
      item: {{ id: "seg_3" }}
    }},
    expected: {{ type: "input_transcript_delta", en: "God loved the world", segmentId: "seg_3" }}
  }},
  {{
    name: "paired_input_delta",
    event: {{
      type: "session.input_transcript.delta",
      input_transcript: {{ delta: "God loved the world" }},
      item: {{ id: "seg_1" }}
    }},
    expected: {{ type: "input_transcript_delta", en: "God loved the world", segmentId: "seg_1" }}
  }},
  {{
    name: "input_final_content",
    event: {{
      type: "session.input_transcript.done",
      item: {{ id: "seg_4", content: [{{ transcript: "Jesus is Lord." }}] }}
    }},
    expected: {{ type: "input_transcript_final", en: "Jesus is Lord.", segmentId: "seg_4", final: true }}
  }}
];

const results = cases.map((item) => {{
  const actual = normalize(item.event);
  const mismatches = [];
  for (const [key, value] of Object.entries(item.expected)) {{
    if (!actual || actual[key] !== value) mismatches.push({{ key, expected: value, actual: actual && actual[key] }});
  }}
  if (!actual || actual.source !== "openai-realtime-webrtc") {{
    mismatches.push({{ key: "source", expected: "openai-realtime-webrtc", actual: actual && actual.source }});
  }}
  return {{ name: item.name, state: mismatches.length ? "fail" : "pass", actual, mismatches }};
}});

const createdSession = await prototype.createRealtimeSession();
prototype.state.realtime = {{
  sessionId: createdSession.sessionId,
  eventToken: createdSession.eventToken,
  backendPersistedEvents: 0,
  backendPersistFailures: 0,
  currentSegmentId: null,
  partialZh: "",
  partialEn: ""
}};
	prototype.handleRealtimeDataChannelMessage(JSON.stringify({{
	  type: "session.input_transcript.delta",
	  input_transcript: {{ delta: "God loved the world" }},
	  item: {{ id: "seg_post_1" }}
	}}));
	prototype.handleRealtimeDataChannelMessage(JSON.stringify({{
	  type: "session.output_transcript.delta",
	  delta: "神爱世人",
	  item_id: "seg_post_1"
	}}));
	await Promise.resolve();
	await Promise.resolve();
	await Promise.resolve();
	await Promise.resolve();
	
	const createRequest = fetchRequests.find((item) => item.url === "/api/admin/realtime/sessions");
	const postRequests = fetchRequests.filter((item) => item.url === "/api/realtime/sessions/rt_probe/events");
	const inputPostRequest = postRequests.find((item) => item.body && item.body.type === "input_transcript_delta");
	const outputPostRequest = postRequests.find((item) => item.body && item.body.type === "caption_delta");
	const sessionProbeChecks = {{
	  createUsesAdminEndpoint: Boolean(createRequest),
	  createUsesPost: createRequest && createRequest.method === "POST",
	  createUsesRealtimeTranslate: createRequest && createRequest.body && createRequest.body.model === "gpt-realtime-translate",
	  createTargetsChinese: createRequest && createRequest.body && createRequest.body.targetLanguage === "zh",
	  createUsesIpadMic: createRequest && createRequest.body && createRequest.body.audioSourceKind === "ipad_mic",
	  backendPostUsesSessionEndpoint: postRequests.length === 2,
	  backendPostUsesPost: postRequests.every((item) => item.method === "POST"),
	  backendPostUsesEventTokenHeader: postRequests.length === 2 && postRequests.every((item) => Boolean(item.headers["X-Realtime-Event-Token"])),
	  backendPostUsesKeepalive: postRequests.length === 2 && postRequests.every((item) => item.keepalive === true),
	  backendPostStoresEnglishDelta: inputPostRequest && inputPostRequest.body && inputPostRequest.body.en === "God loved the world",
	  backendPostStoresChineseDelta: outputPostRequest && outputPostRequest.body && outputPostRequest.body.zh === "神爱世人",
	  backendPostStoresSegmentId: inputPostRequest && outputPostRequest && inputPostRequest.body.segmentId === "seg_post_1" && outputPostRequest.body.segmentId === "seg_post_1",
	  backendPostSourceIsWebrtc: postRequests.length === 2 && postRequests.every((item) => item.body && item.body.source === "openai-realtime-webrtc"),
	  backendPostDoesNotIncludeClientSecret: postRequests.length === 2 && postRequests.every((item) => !JSON.stringify(item.body || {{}}).includes("clientSecret")),
	  backendPostDoesNotIncludeEventToken: postRequests.length === 2 && postRequests.every((item) => !JSON.stringify(item.body || {{}}).includes(probeEventToken))
	}};
const sessionProbe = {{
  status: Object.values(sessionProbeChecks).every(Boolean) ? "ok" : "failed",
  checks: sessionProbeChecks,
  createRequest: createRequest ? {{
    url: createRequest.url,
    method: createRequest.method,
    body: createRequest.body,
    hasAuthorizationHeader: Boolean(createRequest.headers.Authorization)
  }} : null,
	  backendPosts: postRequests.map((item) => ({{
	    url: item.url,
	    method: item.method,
	    hasRealtimeEventTokenHeader: Boolean(item.headers["X-Realtime-Event-Token"]),
	    keepalive: item.keepalive,
	    body: item.body
	  }})),
	  persistedEvents: prototype.state.realtime.backendPersistedEvents,
	  persistFailures: prototype.state.realtime.backendPersistFailures
	}};

process.stdout.write(JSON.stringify({{
  status: results.every((item) => item.state === "pass") && sessionProbe.status === "ok" ? "ok" : "failed",
  results,
  sessionProbe,
  apiKeyMaterialIncluded: false,
  secretResourceNamesIncluded: false,
  eventTokenIncluded: false,
  clientSecretIncluded: false
}}));
}})().catch((error) => {{
  process.stdout.write(JSON.stringify({{
    status: "failed",
    results: [],
    sessionProbe: {{ status: "failed", error: String(error && error.message || error) }},
    apiKeyMaterialIncluded: false,
    secretResourceNamesIncluded: false,
    eventTokenIncluded: false,
    clientSecretIncluded: false
  }}));
  process.exitCode = 1;
}});
"""


def enforce_report_sanitized(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    for needle in FORBIDDEN_REPORT_NEEDLES:
        if needle in serialized:
            raise SystemExit(f"Report contains forbidden material: {needle}")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
