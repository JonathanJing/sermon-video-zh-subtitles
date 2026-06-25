from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

from .config import AppConfig
from .manifest import SundaySliceService
from .observability import (
    client_ip_hash,
    command_stage,
    log_event,
    scheduler_job,
    stable_hash,
    trigger_source,
    url_summary,
)
from .realtime import (
    DEFAULT_REALTIME_MODEL,
    DEFAULT_TARGET_LANGUAGE,
    RealtimeEventArchive,
    RealtimeSessionStore,
    OPENAI_TRANSLATION_CALLS_URL,
    create_openai_translation_session,
    realtime_translation_policy_error,
    resolve_openai_api_key,
)
from .scripture import ScriptureNotFoundError, ScriptureService
from .storage import GcsArtifactReader
from .worker import build_generation_plan, parse_generation_request
from scripts import live_source_monitor


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"


class ApiHandler(BaseHTTPRequestHandler):
    config = AppConfig.from_env()
    service = SundaySliceService(config, GcsArtifactReader())
    scripture_service = ScriptureService()
    realtime_store = RealtimeSessionStore(
        RealtimeEventArchive(
            Path(config.realtime_event_log_dir),
            gcs_prefix=config.realtime_event_gcs_prefix,
        )
    )

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                self.handle_api_get(path)
                return
            self.serve_static(path)
        except KeyError:
            self.write_json({"error": "artifact_not_found"}, status=404)
        except FileNotFoundError:
            self.write_json({"error": "not_found"}, status=404)
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=400)

    def do_HEAD(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            self.serve_static(path, head_only=True)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def handle_api_get(self, path: str) -> None:
        path = unquote(path)
        if path == "/api/health":
            self.write_json({"status": "ok"})
            return
        if path == "/api/admin/status":
            self.write_json(self.admin_status())
            return
        parts = [part for part in path.split("/") if part]
        if parts[:2] == ["api", "scripture"]:
            self.handle_scripture_get(parts)
            return
        if parts[:3] == ["api", "realtime", "sessions"] and len(parts) == 5 and parts[4] == "events":
            self.handle_realtime_events_sse(parts[3])
            return
        if parts[:2] == ["api", "sundays"] and len(parts) == 3:
            self.write_json(self.service.get_public_slice(parts[2]))
            return
        if parts[:2] == ["api", "sundays"] and len(parts) == 5 and parts[3] == "artifacts":
            body, content_type = self.service.read_public_artifact(parts[2], parts[4])
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "public, max-age=30")
            self.end_headers()
            self.wfile.write(body)
            return
        self.write_json({"error": "not_found"}, status=404)

    def handle_scripture_get(self, parts: list[str]) -> None:
        if len(parts) == 2:
            self.write_json(self.scripture_service.metadata())
            return
        if parts[2] != "cmn-cu89s":
            self.write_json({"error": "translation_not_found"}, status=404)
            return
        try:
            if len(parts) == 3:
                self.write_json(self.scripture_service.metadata())
                return
            if len(parts) == 4 and parts[3] == "books":
                self.write_json(self.scripture_service.books())
                return
            if len(parts) == 5:
                self.write_json(self.scripture_service.chapter(parts[3], parts[4]))
                return
        except ScriptureNotFoundError:
            self.write_json({"error": "scripture_not_found"}, status=404)
            return
        self.write_json({"error": "not_found"}, status=404)

    def serve_static(self, path: str, head_only: bool = False) -> None:
        target = self.static_path_for(path)
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".webmanifest":
            content_type = "application/manifest+json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Cache-Control",
            "no-cache" if target.name == "index.html" else "public, max-age=60",
        )
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def static_path_for(self, path: str) -> Path:
        clean_path = unquote(path.split("?", 1)[0])
        if clean_path in {"", "/"}:
            clean_path = "/index.html"
        if clean_path in {"/admin", "/admin/"}:
            admin = WEB_ROOT / "admin.html"
            if admin.is_file():
                return admin
        if clean_path.endswith("/"):
            clean_path += "index.html"
        candidate = (WEB_ROOT / clean_path.lstrip("/")).resolve()
        if WEB_ROOT not in {candidate, *candidate.parents}:
            raise FileNotFoundError(clean_path)
        if candidate.is_file():
            return candidate
        if clean_path == "/admin/index.html":
            admin = WEB_ROOT / "admin.html"
            if admin.is_file():
                return admin
        # Keep direct Sunday/operator links browser-routable for the PWA.
        if "." not in Path(clean_path).name:
            return WEB_ROOT / "index.html"
        raise FileNotFoundError(clean_path)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            parts = [part for part in path.split("/") if part]
            if parts == ["api", "telemetry", "page-view"]:
                self.handle_page_view()
                return
            if parts == ["api", "admin", "realtime", "sessions"]:
                self.handle_realtime_session_create()
                return
            if parts == ["api", "admin", "realtime", "local-sessions"]:
                self.handle_realtime_local_session_create()
                return
            if parts[:3] == ["api", "realtime", "sessions"] and len(parts) == 5 and parts[4] == "events":
                self.handle_realtime_event_post(parts[3])
                return
            if parts[:3] == ["api", "admin", "sundays"] and len(parts) == 5 and parts[4] == "discover-source":
                self.handle_live_source_discovery(parts[3])
                return
            if parts[:3] == ["api", "admin", "sundays"] and len(parts) == 5 and parts[4] == "generate":
                if not self.authorized():
                    self.write_json({"error": "unauthorized"}, status=401)
                    return
                sunday = self.resolve_admin_sunday(parts[3])
                payload = self.read_json_body()
                request = parse_generation_request(payload, sunday)
                plan = build_generation_plan(request, self.config)
                source = trigger_source(self.headers, payload)
                log_event(
                    "live_capture_triggered",
                    component="api",
                    sunday=sunday,
                    sessionId=plan.session_id,
                    runPrefix=plan.prefix,
                    triggerSource=source,
                    schedulerJob=scheduler_job(self.headers),
                    liveSource=url_summary(request.live_url),
                    sermonStart=request.sermon_start,
                    dryRunGcs=request.dry_run_gcs,
                )
                if not self.config.enable_inline_worker:
                    log_event(
                        "live_capture_planned",
                        component="api",
                        sunday=sunday,
                        sessionId=plan.session_id,
                        runPrefix=plan.prefix,
                        triggerSource=source,
                        commandCount=len(plan.commands),
                    )
                    self.write_json(
                        {
                            "status": "planned",
                            "message": "Inline worker disabled; run the returned commands from a Cloud Run Job or enable ENABLE_INLINE_WORKER=1.",
                            "sessionId": plan.session_id,
                            "prefix": plan.prefix,
                            "commands": plan.commands,
                        },
                        status=202,
                    )
                    return
                import subprocess

                outputs = []
                for command in plan.commands:
                    log_event(
                        "worker_stage_started",
                        component="api-inline-worker",
                        sunday=sunday,
                        sessionId=plan.session_id,
                        stage=command_stage(command),
                    )
                    completed = subprocess.run(command, check=True, capture_output=True, text=True)
                    log_event(
                        "worker_stage_completed",
                        component="api-inline-worker",
                        sunday=sunday,
                        sessionId=plan.session_id,
                        stage=command_stage(command),
                    )
                    outputs.append(
                        {
                            "command": command,
                            "stdout": completed.stdout,
                            "stderr": completed.stderr,
                        }
                    )
                self.write_json(
                    {
                        "status": "completed",
                        "sessionId": plan.session_id,
                        "prefix": plan.prefix,
                        "outputs": outputs,
                    },
                    status=201,
                )
                return
            self.write_json({"error": "not_found"}, status=404)
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=400)

    def handle_live_source_discovery(self, sunday: str) -> None:
        if not self.authorized():
            self.write_json({"error": "unauthorized"}, status=401)
            return
        sunday = self.resolve_admin_sunday(sunday)
        payload = self.read_json_body()
        monitor_args = self.live_source_monitor_args(payload, sunday)
        report = live_source_monitor.run_monitor(monitor_args)
        log_event(
            "live_source_monitor_completed",
            component="api",
            sunday=sunday,
            status=report.get("status"),
            selectedService=(report.get("selectedSource") or {}).get("service"),
            selectedKind=(report.get("selectedSource") or {}).get("kind"),
            operatorAlert=report.get("operatorAlert"),
            candidateCount=len(report.get("candidates") or []),
            triggerSource=trigger_source(self.headers, payload),
            schedulerJob=scheduler_job(self.headers),
        )
        response = {
            "status": report.get("status"),
            "sunday": sunday,
            "selectedSource": report.get("selectedSource"),
            "operatorAlert": report.get("operatorAlert"),
            "fallbackReason": report.get("fallbackReason"),
            "generationRequest": report.get("generationRequest"),
            "candidateCount": len(report.get("candidates") or []),
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
        }
        if payload.get("includeCandidates"):
            response["candidates"] = report.get("candidates") or []
        if payload.get("autoGenerate") and isinstance(report.get("generationRequest"), dict):
            request = parse_generation_request(report["generationRequest"], sunday)
            plan = build_generation_plan(request, self.config)
            log_event(
                "live_capture_planned",
                component="api",
                sunday=sunday,
                sessionId=plan.session_id,
                runPrefix=plan.prefix,
                triggerSource="live-source-monitor",
                commandCount=len(plan.commands),
                liveSource=url_summary(request.live_url),
            )
            response["generationPlan"] = {
                "status": "planned",
                "sessionId": plan.session_id,
                "prefix": plan.prefix,
                "commandCount": len(plan.commands),
            }
        self.write_json(response, status=202)

    def resolve_admin_sunday(self, sunday: str) -> str:
        return self.service._resolve_sunday(sunday)

    def live_source_monitor_args(self, payload: dict, sunday: str) -> SimpleNamespace:
        manual_urls = payload.get("manualUrls") or payload.get("manual_urls") or []
        if payload.get("manualUrl") or payload.get("manual_url"):
            manual_urls = [payload.get("manualUrl") or payload.get("manual_url"), *manual_urls]
        if isinstance(manual_urls, str):
            manual_urls = [manual_urls]
        if not isinstance(manual_urls, list):
            manual_urls = []
        sources = payload.get("sources")
        if sources is not None and not isinstance(sources, list):
            sources = []
        return SimpleNamespace(
            sunday=sunday,
            service=str(payload.get("service") or "auto"),
            expected_title=payload.get("expectedTitle") or payload.get("expected_title"),
            manual_url=[str(url) for url in manual_urls if str(url or "").strip()],
            mariners_online_url=str(payload.get("marinersOnlineUrl") or live_source_monitor.DEFAULT_MARINERS_ONLINE_URL),
            youtube_streams_url=str(payload.get("youtubeStreamsUrl") or live_source_monitor.DEFAULT_YOUTUBE_STREAMS_URL),
            fixture_json=None,
            fixture_sources=sources,
            out=Path("artifacts/live-source-monitor/backend-report.json"),
            timezone=str(payload.get("timezone") or self.config.timezone),
            now=payload.get("now"),
            min_confidence=float(payload.get("minConfidence", 0.70)),
            operator_alert_time=str(payload.get("operatorAlertTime") or "09:58"),
            backend_url="",
            post_generate=False,
            admin_token=None,
            internal_task_token=None,
        )

    def handle_page_view(self) -> None:
        payload = self.read_json_body()
        device_id = str(payload.get("anonymousDeviceId") or payload.get("deviceId") or "")[:80]
        if not device_id:
            self.write_json({"error": "anonymousDeviceId_required"}, status=400)
            return
        log_event(
            "congregation_page_view",
            component="web",
            anonymousDeviceId=device_id,
            visitId=str(payload.get("visitId") or "")[:80],
            sunday=str(payload.get("sunday") or "")[:20],
            viewMode=str(payload.get("viewMode") or "")[:32],
            path=str(payload.get("path") or "")[:160],
            timezone=str(payload.get("timezone") or "")[:80],
            language=str(payload.get("language") or "")[:40],
            viewport=payload.get("viewport") if isinstance(payload.get("viewport"), dict) else None,
            screen=payload.get("screen") if isinstance(payload.get("screen"), dict) else None,
            userAgentHash=stable_hash(self.headers.get("User-Agent", "")) if self.headers.get("User-Agent") else None,
            clientIpHash=client_ip_hash(self.headers, self.client_address),
        )
        self.write_json({"status": "logged"}, status=202)

    def handle_realtime_session_create(self) -> None:
        if not self.authorized_for_admin_browser():
            self.write_json({"error": "unauthorized"}, status=401)
            return
        payload = self.read_json_body()
        sunday = str(payload.get("sunday") or self.service._resolve_sunday("current"))[:20]
        model = str(payload.get("model") or DEFAULT_REALTIME_MODEL)[:80]
        target_language = str(payload.get("targetLanguage") or DEFAULT_TARGET_LANGUAGE)[:20]
        policy_error = realtime_translation_policy_error(model, target_language)
        if policy_error:
            self.write_json(policy_error, status=400)
            return
        audio_source_kind = normalize_realtime_audio_source_kind(payload)
        try:
            api_key = resolve_openai_api_key(
                self.config.openai_api_key,
                self.config.openai_api_key_secret,
            )
            openai_session = create_openai_translation_session(
                api_key=api_key,
                model=model,
                target_language=target_language,
            )
        except Exception as exc:
            log_event(
                "realtime_session_create_failed",
                component="api",
                sunday=sunday,
                error=str(exc)[:200],
                severity="ERROR",
            )
            self.write_json({"error": "realtime_session_failed", "message": str(exc)}, status=502)
            return

        client_secret = openai_session.get("client_secret") if isinstance(openai_session, dict) else None
        if not isinstance(client_secret, dict) or not client_secret.get("value"):
            self.write_json({"error": "missing_client_secret"}, status=502)
            return

        session = self.realtime_store.create(
            sunday=sunday,
            model=model,
            target_language=target_language,
            audio_source_kind=audio_source_kind,
        )

        log_event(
            "realtime_session_created",
            component="api",
            sunday=sunday,
            sessionId=session.session_id,
            model=model,
            targetLanguage=target_language,
            audioSourceKind=audio_source_kind,
        )
        self.write_json(
            {
                "status": "ready",
                "sessionId": session.session_id,
                "eventToken": session.event_token,
                "model": model,
                "targetLanguage": target_language,
                "audioSourceKind": audio_source_kind,
                "clientSecret": {
                    "value": client_secret.get("value"),
                    "expiresAt": client_secret.get("expires_at"),
                },
                "webrtc": {
                    "url": OPENAI_TRANSLATION_CALLS_URL,
                    "model": model,
                },
            },
            status=201,
        )

    def handle_realtime_local_session_create(self) -> None:
        if not self.authorized_for_admin_browser():
            self.write_json({"error": "unauthorized"}, status=401)
            return
        payload = self.read_json_body()
        sunday = str(payload.get("sunday") or self.service._resolve_sunday("current"))[:20]
        model = str(payload.get("model") or DEFAULT_REALTIME_MODEL)[:80]
        target_language = str(payload.get("targetLanguage") or DEFAULT_TARGET_LANGUAGE)[:20]
        policy_error = realtime_translation_policy_error(model, target_language)
        if policy_error:
            self.write_json(policy_error, status=400)
            return
        audio_source_kind = normalize_realtime_audio_source_kind(payload)
        session = self.realtime_store.create(
            sunday=sunday,
            model=model,
            target_language=target_language,
            audio_source_kind=audio_source_kind,
        )
        log_event(
            "realtime_session_created",
            component="api",
            sunday=sunday,
            sessionId=session.session_id,
            model=model,
            targetLanguage=target_language,
            audioSourceKind=audio_source_kind,
            triggerSource=str(payload.get("triggerSource") or "local-realtime-session")[:80],
        )
        self.write_json(
            {
                "status": "ready",
                "sessionId": session.session_id,
                "eventToken": session.event_token,
                "model": model,
                "targetLanguage": target_language,
                "audioSourceKind": audio_source_kind,
                "webrtc": None,
            },
            status=201,
        )

    def handle_realtime_event_post(self, session_id: str) -> None:
        payload = self.read_json_body()
        token = self.headers.get("X-Realtime-Event-Token") or bearer_token(self.headers.get("Authorization", ""))
        event_token_authorized = self.realtime_store.validate_event_token(session_id, token)
        stable_admin_authorized = self.authorized() and is_stable_correction_payload(payload)
        if not event_token_authorized and not stable_admin_authorized:
            self.write_json({"error": "unauthorized"}, status=401)
            return
        event = self.realtime_store.append_event(session_id, payload)
        if event.get("type") in {"caption_delta", "caption_final", "input_transcript_delta", "input_transcript_final"}:
            log_event(
                "realtime_caption_event",
                component="api",
                sessionId=session_id,
                eventType=event.get("type"),
                segmentId=event.get("segmentId"),
            )
        if str(event.get("type") or "").startswith("media_worker_") or event.get("type") in {
            "audio_source_ready",
            "replay_source_ready",
        }:
            log_event(
                "realtime_media_worker_event",
                component="api",
                sessionId=session_id,
                eventType=event.get("type"),
                source=event.get("source"),
            )
        self.write_json({"status": "accepted", "id": event["id"]}, status=202)

    def handle_realtime_events_sse(self, session_id: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        cursor = self.sse_cursor()
        active_session_id = None if session_id == "current" else session_id
        try:
            self.write_sse_comment("connected")
            while True:
                if session_id == "current":
                    current = self.realtime_store.current_session_id() or self.realtime_store.wait_for_current_session_id(25)
                    if not current:
                        self.write_sse_comment("waiting-for-session")
                        continue
                    if current != active_session_id:
                        active_session_id = current
                        cursor = 0
                if not active_session_id or not self.realtime_store.get(active_session_id):
                    self.write_sse_comment("session-not-found")
                    return
                events = self.realtime_store.wait_for_events(active_session_id, cursor, 25)
                if not events:
                    self.write_sse_comment("keepalive")
                    continue
                for event in events:
                    cursor = int(event["id"])
                    self.write_sse_event(event)
        except (BrokenPipeError, ConnectionResetError):
            return

    def sse_cursor(self) -> int:
        query = parse_qs(urlparse(self.path).query)
        try:
            return max(0, int((query.get("cursor") or ["0"])[0]))
        except ValueError:
            return 0

    def write_sse_comment(self, text: str) -> None:
        self.wfile.write(f": {text}\n\n".encode("utf-8"))
        self.wfile.flush()

    def write_sse_event(self, event: dict) -> None:
        event_type = str(event.get("type") or "message")
        data = json.dumps(event, ensure_ascii=False)
        self.wfile.write(f"id: {event['id']}\nevent: {event_type}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def admin_status(self) -> dict:
        sunday = self.service._resolve_sunday("current")
        public_slice = None
        manifest_status = "missing"
        manifest_error = None
        try:
            public_slice = self.service.get_public_slice("current")
            manifest_status = str(public_slice.get("status") or "ready")
        except Exception as exc:
            manifest_error = str(exc)
        return {
            "schemaVersion": 1,
            "status": "ok",
            "sunday": sunday,
            "timezone": self.config.timezone,
            "service": {
                "runtime": "cloud-run-compatible",
                "health": "ok",
            },
            "artifact": {
                "bucket": self.config.artifact_bucket,
                "prefix": self.config.artifact_prefix,
                "manifestStatus": manifest_status,
                "manifestError": manifest_error,
                "artifactCount": public_slice.get("artifactCount") if public_slice else 0,
                "generationMode": public_slice.get("generationMode") if public_slice else None,
            },
            "captions": {
                "sermonTitle": public_slice.get("sermonTitle") if public_slice else None,
                "translationStatus": public_slice.get("translationStatus") if public_slice else "unknown",
                "totalSegments": public_slice.get("totalSegments") if public_slice else None,
                "translatedSegments": public_slice.get("translatedSegments") if public_slice else None,
                "readyTime": public_slice.get("readyTime") if public_slice else None,
                "publishedAt": public_slice.get("publishedAt") if public_slice else None,
                "lastUpdated": public_slice.get("lastUpdated") if public_slice else None,
            },
            "readiness": public_slice.get("readiness") if public_slice else {
                "state": "missing",
                "publicArtifactsReady": False,
                "fallback": False,
            },
            "settings": {
                "provider": "openai",
                "targetServiceTime": "11:30 PT",
                "readinessDeadline": "11:50 PT",
                "sourceDiscoveryEndpoint": "/api/admin/sundays/{sunday}/discover-source",
                "manualTriggerEndpoint": "/api/admin/sundays/{sunday}/generate",
                "realtimeSessionEndpoint": "/api/admin/realtime/sessions",
                "localRealtimeSessionEndpoint": "/api/admin/realtime/local-sessions",
                "realtimeEventsEndpoint": "/api/realtime/sessions/current/events",
                "telemetryEndpoint": "/api/telemetry/page-view",
            },
            "realtime": {
                "currentSessionId": self.realtime_store.current_session_id(),
                "eventArchive": self.realtime_store.archive_status(),
            },
            "secrets": {
                "openaiApiKey": "configured" if self.openai_key_configured() else "missing",
                "operatorAdminToken": "configured" if self.config.operator_admin_token else "missing",
                "internalTaskToken": "configured" if self.config.internal_task_token else "missing",
            },
            "observability": {
                "events": [
                    "live_capture_triggered",
                    "worker_stage_completed",
                    "realtime_session_created",
                    "realtime_media_worker_event",
                    "realtime_caption_event",
                    "captions_ready",
                    "congregation_page_view",
                ],
                "pageViewTelemetry": "enabled",
            },
        }

    def authorized(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        if self.config.operator_admin_token and auth_header == f"Bearer {self.config.operator_admin_token}":
            return True
        task_token = self.headers.get("X-Internal-Task-Token", "")
        if self.config.internal_task_token and task_token == self.config.internal_task_token:
            return True
        return False

    def authorized_for_admin_browser(self) -> bool:
        if self.authorized():
            return True
        return not self.config.operator_admin_token and not self.config.internal_task_token

    def openai_key_configured(self) -> bool:
        return bool(self.config.openai_api_key or self.config.openai_api_key_secret)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def write_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def bearer_token(value: str) -> str | None:
    prefix = "Bearer "
    return value[len(prefix) :] if value.startswith(prefix) else None


def normalize_realtime_audio_source_kind(payload: dict) -> str:
    raw_value = payload.get("audioSourceKind") or payload.get("source") or "unknown"
    value = str(raw_value).strip().lower().replace("-", "_")[:80]
    if value in {"ipad_microphone", "ipadmic"}:
        return "ipad_mic"
    if value in {"iphone_microphone", "iphonemic"}:
        return "iphone_mic"
    if value in {"youtube_live", "youtube", "authorized_youtube_live"}:
        return "authorized_youtube_source"
    if value in {"authorized_audio", "audio_url"}:
        return "authorized_audio_url"
    return value or "unknown"


def is_stable_correction_payload(payload: dict) -> bool:
    return (
        payload.get("type") == "caption_final"
        and payload.get("final") is True
        and payload.get("source") == "gpt-5.4-mini-stable-correction"
        and payload.get("model") == "gpt-5.4-mini"
        and bool(str(payload.get("segmentId") or "").strip())
        and bool(str(payload.get("text") or payload.get("zh") or "").strip())
    )


def main() -> None:
    import os

    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), ApiHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
