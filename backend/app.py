from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

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
from .storage import GcsArtifactReader
from .worker import build_generation_plan, parse_generation_request


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"


class ApiHandler(BaseHTTPRequestHandler):
    config = AppConfig.from_env()
    service = SundaySliceService(config, GcsArtifactReader())

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
        if path == "/api/health":
            self.write_json({"status": "ok"})
            return
        parts = [part for part in path.split("/") if part]
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
        if clean_path.endswith("/"):
            clean_path += "index.html"
        candidate = (WEB_ROOT / clean_path.lstrip("/")).resolve()
        if WEB_ROOT not in {candidate, *candidate.parents}:
            raise FileNotFoundError(clean_path)
        if candidate.is_file():
            return candidate
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
            if parts[:3] == ["api", "admin", "sundays"] and len(parts) == 5 and parts[4] == "generate":
                if not self.authorized():
                    self.write_json({"error": "unauthorized"}, status=401)
                    return
                payload = self.read_json_body()
                request = parse_generation_request(payload, parts[3])
                plan = build_generation_plan(request, self.config)
                source = trigger_source(self.headers, payload)
                log_event(
                    "live_capture_triggered",
                    component="api",
                    sunday=parts[3],
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
                        sunday=parts[3],
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
                        sunday=parts[3],
                        sessionId=plan.session_id,
                        stage=command_stage(command),
                    )
                    completed = subprocess.run(command, check=True, capture_output=True, text=True)
                    log_event(
                        "worker_stage_completed",
                        component="api-inline-worker",
                        sunday=parts[3],
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

    def authorized(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        if self.config.operator_admin_token and auth_header == f"Bearer {self.config.operator_admin_token}":
            return True
        task_token = self.headers.get("X-Internal-Task-Token", "")
        if self.config.internal_task_token and task_token == self.config.internal_task_token:
            return True
        return False

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


def main() -> None:
    import os

    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), ApiHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
