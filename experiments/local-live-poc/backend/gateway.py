from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from .asr_client import AsrError, MlxAudioWebSocketClient, WhisperCliClient
from .caption_presenter import CAPTION_PRESENTATION_POLICIES
from .content_pack import (
    CONTEXT_POLICIES,
    CONTEXT_POLICY_LEVELS,
    PackValidationError,
    alignment_summary,
    load_pack,
    prompt_context,
    retrieve,
    sha256_file,
)
from .firebase_publisher import FirebaseCaptionPublisher, FirebasePublisherConfig
from .ollama_client import CONTEXT_PROMPT_VERSION, MILMMT_A0_PROMPT_VERSION, OllamaClient, OllamaError
from .runtime_identity import collect_runtime_identity, validate_frontend_origin
from .session_store import SessionStore, SessionStoreError
from .translation_units import TRANSLATION_UNIT_POLICIES
from .viewer_server import CaptionHub, ViewerService, viewer_urls


DEFAULT_OLLAMA_MODEL = "sermon-milmmt-46-4b-v1-q8:benchmark"
RUNTIME_RESTART_EXIT_CODE = 75


class GatewayState:
    def __init__(
        self,
        pack_path: str = "",
        ollama_model: str = "",
        ollama_url: str = "http://127.0.0.1:11434",
        session_root: str = "artifacts/sessions",
        asr_model: str = "",
        whisper_binary: str = "whisper-cli",
        vad_threshold_rms: int = 150,
        vad_silence_ms: int = 500,
        vad_max_segment_ms: int = 3000,
        ws_port: int = 8767,
        asr_provider: str = "whisper-cli",
        mlx_audio_url: str = "ws://127.0.0.1:18766/v1/audio/transcriptions/realtime",
        mlx_audio_model: str = "",
        viewer_port: int = 8780,
        default_context_policy: str = "none",
        caption_presentation_policy: str = "readable_chunks",
        translation_unit_policy: str = "legacy",
        source_fragment_policy: str = "content_words",
        frontend_origin: str = "http://127.0.0.1:4173",
    ) -> None:
        self.pack_path = pack_path
        self.pack = load_pack(pack_path) if pack_path else None
        self.pack_sha256 = sha256_file(pack_path) if pack_path else None
        self.ollama = OllamaClient(ollama_model, ollama_url)
        self.sessions = SessionStore(session_root)
        if asr_provider == "qwen-mlx-websocket":
            self.asr = MlxAudioWebSocketClient(mlx_audio_model, mlx_audio_url)
        elif asr_provider == "whisper-cli":
            self.asr = WhisperCliClient(asr_model, whisper_binary)
        else:
            raise ValueError(f"unsupported ASR provider: {asr_provider}")
        self.vad_threshold_rms = vad_threshold_rms
        self.vad_silence_ms = vad_silence_ms
        self.vad_max_segment_ms = vad_max_segment_ms
        self.ws_port = ws_port
        self.viewer_port = viewer_port
        if default_context_policy not in CONTEXT_POLICIES:
            raise ValueError(f"unsupported default context policy: {default_context_policy}")
        self.default_context_policy = (
            default_context_policy if self.pack and default_context_policy != "none" else "none"
        )
        if caption_presentation_policy not in CAPTION_PRESENTATION_POLICIES:
            raise ValueError(
                f"unsupported caption presentation policy: {caption_presentation_policy}"
            )
        self.caption_presentation_policy = caption_presentation_policy
        if translation_unit_policy not in TRANSLATION_UNIT_POLICIES:
            raise ValueError(f"unsupported translation unit policy: {translation_unit_policy}")
        if source_fragment_policy not in {"content_words", "off"}:
            raise ValueError(f"unsupported source fragment policy: {source_fragment_policy}")
        self.translation_unit_policy = translation_unit_policy
        self.source_fragment_policy = source_fragment_policy
        self.frontend_origin = validate_frontend_origin(frontend_origin)
        self.frontend_origins = (
            (self.frontend_origin, "http://localhost:4173")
            if self.frontend_origin == "http://127.0.0.1:4173" else (self.frontend_origin,)
        )
        self._runtime_identity_json: str | None = None
        self._runtime_identity_lock = threading.Lock()
        self.caption_hub = CaptionHub()
        firebase_config = FirebasePublisherConfig.from_environment()
        self.public_caption_publisher = (
            FirebaseCaptionPublisher(firebase_config) if firebase_config else None
        )
        self.asr_warmup: dict[str, Any] | None = None
        self.ollama_warmup: dict[str, Any] | None = None
        self.runtime_restart: Callable[[], None] = lambda: os._exit(RUNTIME_RESTART_EXIT_CODE)
        self.live_pipelines: dict[str, Any] = {}
        self.live_lock = threading.Lock()

    def capture_runtime_identity(
        self, *, provider_versions: dict[str, Any] | None = None,
        translation_model_digest: str | None = None,
        asr_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Freeze once before serving; return copies so callers cannot rewrite it."""
        with self._runtime_identity_lock:
            if self._runtime_identity_json is None:
                model_sha256 = (asr_status or {}).get("modelSha256")
                if model_sha256 is None:
                    model_sha256 = getattr(self.asr, "_model_sha256", None)
                qwen = isinstance(self.asr, MlxAudioWebSocketClient)
                context_enabled = self.default_context_policy not in {"none", "english_alignment_v1"}
                template_context = {
                    "approvedTerms": [{"source": "{{term.source}}", "preferredZh": "{{term.preferredZh}}"}],
                    "verifiedScriptureRefs": ["{{scripture_reference}}"],
                    "reviewedExactExamples": [{"sourceTextEn": "{{example.source}}", "targetTextZh": "{{example.target}}"}],
                    "reviewedAlignedReferences": [{"sourceTextEn": "{{reference.source}}", "targetTextZh": "{{reference.target}}"}],
                } if context_enabled else {}
                prompt_template = OllamaClient.build_prompt("{{source_text_en}}", template_context)
                configuration = {
                    "asrProvider": "qwen-mlx-websocket" if qwen else "whisper-cli",
                    "asrModelSha256": model_sha256,
                    "asrFinalizationMode": "vad_silence_frames" if qwen else "whisper_cli_segment",
                    "asrSilenceFrameCount": self.asr.finalize_silence_frames if qwen else None,
                    "vadThresholdRms": self.vad_threshold_rms,
                    "vadSilenceMs": self.vad_silence_ms,
                    "vadMaxSegmentMs": self.vad_max_segment_ms,
                    "asrQueueLimit": 2, "translationQueueLimit": 1,
                    "translationModel": self.ollama.model,
                    "translationModelDigest": translation_model_digest,
                    "translationPromptVersion": CONTEXT_PROMPT_VERSION if context_enabled else MILMMT_A0_PROMPT_VERSION,
                    "translationPromptFamily": "context_with_a0_no_hit_fallback" if context_enabled else "frozen_a0",
                    "translationPromptSha256": hashlib.sha256(prompt_template.encode("utf-8")).hexdigest(),
                    "translationPromptHashScope": "template_with_source_and_context_placeholders" if context_enabled else "template_with_source_placeholder",
                    "translationStreaming": True, "translationTemperature": 0,
                    "translationTopK": 1, "sampleRateHz": 16000, "frameDurationMs": 100,
                    "contextPolicy": self.default_context_policy,
                    "contentPackVersion": self.pack.get("packVersion") if self.pack else None,
                    "contentPackSha256": self.pack_sha256,
                    "captionPresentationPolicy": self.caption_presentation_policy,
                    "translationUnitPolicy": self.translation_unit_policy,
                    "translationUnitMaxWaitMs": 3200, "translationUnitMaxSegments": 2,
                    "translationUnitMaxAudioDurationMs": 6500, "translationUnitMaxAudioGapMs": 800,
                    "sourceFragmentPolicy": self.source_fragment_policy,
                    "frontendOrigin": self.frontend_origin,
                    "frontendOrigins": ",".join(self.frontend_origins),
                }
                identity = collect_runtime_identity(configuration, versions=provider_versions)
                self._runtime_identity_json = json.dumps(identity, ensure_ascii=False)
            return json.loads(self._runtime_identity_json)

    def resume_session(self, session_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        with self.live_lock:
            if session_id in self.live_pipelines:
                raise SessionStoreError("previous live stream is still draining; retry shortly")
            count = metadata.get("availableAudioChunks")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise SessionStoreError("availableAudioChunks must be a nonnegative integer")
            frame_sequence = metadata.get("pcmFrameSequence")
            if frame_sequence is not None:
                if type(frame_sequence) is not int or frame_sequence < 0:
                    raise SessionStoreError("pcmFrameSequence must be a nonnegative integer")
                # Inspect the durable position without reopening the session.
                with self.sessions._lock:
                    _, manifest = self.sessions._load(session_id)
                if frame_sequence < manifest["pcmFrameCount"]:
                    raise SessionStoreError("pcmFrameSequence cannot precede the durable PCM position")
                if frame_sequence - manifest["pcmFrameCount"] > 3000:
                    raise SessionStoreError("字幕中断超过五分钟，请停止保存录音并开始新会话")
            resumed = self.sessions.resume(session_id, count)
            runtime_identity = self.capture_runtime_identity()
            original_fingerprint = (resumed.get("metadata", {}).get("runtimeIdentity") or {}).get("fingerprintSha256")
            self.sessions.append_event(session_id, {
                "type": "stream.resume_requested", "resumeCount": resumed["resumeCount"],
                "runtimeIdentity": runtime_identity,
                "runtimeChanged": runtime_identity["fingerprintSha256"] != original_fingerprint if original_fingerprint else None,
            }, assign_sequence=True)
            return self.sessions.get_recording(session_id)

    def finalize_session(self, session_id: str, details: dict[str, Any]) -> dict[str, Any]:
        with self.live_lock:
            pipeline = self.live_pipelines.get(session_id)
            if session_id in self.live_pipelines and (
                pipeline is None or not pipeline.stopped
                or pipeline.asr_worker.is_alive() or pipeline.translation_worker.is_alive()
            ):
                raise SessionStoreError("live workers must stop before finalizing the recording")
            return self.sessions.finalize(session_id, details)

    def live_health(self) -> dict[str, Any]:
        with self.live_lock:
            snapshots = [pipeline.health() for pipeline in self.live_pipelines.values() if pipeline]
        return {"activeStreamCount": len(snapshots), "degraded": any(s["degraded"] for s in snapshots), "streams": snapshots}

    def resolve_context_policy(self, requested_policy: str | None) -> str:
        requested = str(requested_policy or self.default_context_policy)
        if requested not in CONTEXT_POLICIES:
            raise PackValidationError(
                "contextPolicy must be none, english_alignment_v1, "
                "weekly_terms_v1, or saturday_alignment_v1"
            )
        if CONTEXT_POLICY_LEVELS[requested] > CONTEXT_POLICY_LEVELS[self.default_context_policy]:
            raise PackValidationError(
                f"contextPolicy {requested} exceeds configured capability "
                f"{self.default_context_policy}"
            )
        return requested

    def create_session(self, metadata: dict[str, Any]) -> dict[str, Any]:
        safe_metadata = dict(metadata)
        safe_metadata["contextPolicy"] = self.resolve_context_policy(
            safe_metadata.get("contextPolicy")
        )
        safe_metadata["contentPack"] = None if not self.pack else {
            "packVersion": self.pack.get("packVersion"),
            "packSha256": self.pack_sha256,
            "serviceDate": self.pack.get("serviceDate"),
            "validUntil": self.pack.get("validUntil"),
        }
        safe_metadata["runtimeIdentity"] = self.capture_runtime_identity()
        return self.sessions.create(safe_metadata)

    def translate(
        self,
        source_text: str,
        cursor_sequence: int | None,
        context_policy: str,
    ) -> dict[str, Any]:
        context_policy = self.resolve_context_policy(context_policy)
        pack = self.pack
        hits = (
            retrieve(pack, source_text, limit=5, cursor_sequence=cursor_sequence)
            if pack and context_policy != "none" else []
        )
        context = prompt_context(hits, policy=context_policy)
        result = self.ollama.translate(source_text, context)
        return {
            "sourceTextEn": source_text,
            **result,
            "requestedContextPolicy": context_policy,
            "contextPolicy": context_policy if hits else "none",
            "contextHitIds": [hit["entryId"] for hit in hits],
            "alignment": alignment_summary(hits, cursor_sequence),
        }

    def translate_stream(
        self,
        source_text: str,
        cursor_sequence: int | None,
        context_policy: str,
        on_partial: Callable[[str, str], None],
    ) -> dict[str, Any]:
        context_policy = self.resolve_context_policy(context_policy)
        pack = self.pack
        hits = (
            retrieve(pack, source_text, limit=5, cursor_sequence=cursor_sequence)
            if pack and context_policy != "none" else []
        )
        context = prompt_context(hits, policy=context_policy)
        result = self.ollama.translate(source_text, context, on_partial=on_partial)
        return {
            "sourceTextEn": source_text,
            **result,
            "requestedContextPolicy": context_policy,
            "contextPolicy": context_policy if hits else "none",
            "contextHitIds": [hit["entryId"] for hit in hits],
            "alignment": alignment_summary(hits, cursor_sequence),
        }


class GatewayServer(ThreadingHTTPServer):
    state: GatewayState


class Handler(BaseHTTPRequestHandler):
    server: GatewayServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _origin(self) -> str:
        requested = self.headers.get("Origin", "")
        allowed = self.server.state.frontend_origins
        return requested if requested in allowed else allowed[0]

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as error:
            raise PackValidationError(f"invalid JSON body: {error}") from error
        if not isinstance(payload, dict):
            raise PackValidationError("request body must be a JSON object")
        return payload

    def _raw_body(self, max_bytes: int = 10 * 1024 * 1024) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise PackValidationError("invalid Content-Length") from error
        if length < 1 or length > max_bytes:
            raise PackValidationError(f"body must be between 1 and {max_bytes} bytes")
        return self.rfile.read(length)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", self._origin())
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:
        if urlparse(self.path).path != "/api/health":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        ollama = self.server.state.ollama.status()
        asr = self.server.state.asr.status()
        storage = self.server.state.sessions.health()
        pack = self.server.state.pack
        live_health = self.server.state.live_health()
        self._send(HTTPStatus.OK, {
            "service": "local-live-caption-gateway",
            "runtimeIdentity": self.server.state.capture_runtime_identity(),
            "status": "ready" if (
                ollama.get("configuredModelInstalled")
                and asr.get("available")
                and storage.get("available")
                and not live_health["degraded"]
            ) else "degraded",
            "contentPack": None if not pack else {
                "packVersion": pack["packVersion"],
                "serviceDate": pack["serviceDate"],
                "validUntil": pack["validUntil"],
                "entryCount": len(pack["entries"]),
            },
            "defaultContextPolicy": self.server.state.default_context_policy,
            "ollama": ollama,
            "ollamaWarmup": self.server.state.ollama_warmup,
            "asr": asr,
            "asrWarmup": self.server.state.asr_warmup,
            "liveStream": {
                "available": asr.get("available", False),
                "webSocketUrl": f"ws://127.0.0.1:{self.server.state.ws_port}/api/live",
                "format": "pcm_s16le/16000/mono/100ms",
                "asrFinalPolicy": {
                    "silenceMs": self.server.state.vad_silence_ms,
                    "maxSegmentMs": self.server.state.vad_max_segment_ms,
                },
                "translationStreaming": True,
                "translationUnitPolicy": self.server.state.translation_unit_policy,
                "sourceFragmentPolicy": self.server.state.source_fragment_policy,
                "captionPresentation": {
                    "policy": self.server.state.caption_presentation_policy,
                    "rollbackPolicy": "legacy",
                },
            },
            "viewer": {
                "available": True,
                "port": self.server.state.viewer_port,
                "networkAddresses": viewer_urls("{session-token}", self.server.state.viewer_port),
                "readOnly": True,
            },
            "publicViewer": (
                self.server.state.public_caption_publisher.status()
                if self.server.state.public_caption_publisher
                else {"configured": False, "mode": "disabled"}
            ),
            "sessionStorage": storage,
            "liveProgress": live_health,
        })

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            audio_match = re.fullmatch(r"/api/sessions/([^/]+)/audio", parsed.path)
            session_match = re.fullmatch(r"/api/sessions/([^/]+)/(events|finalize|resume)", parsed.path)
            if audio_match:
                values = parse_qs(parsed.query).get("sequence", [])
                if len(values) != 1:
                    raise PackValidationError("audio sequence query parameter is required")
                try:
                    sequence = int(values[0])
                except ValueError as error:
                    raise PackValidationError("audio sequence must be an integer") from error
                result = self.server.state.sessions.append_audio(
                    audio_match.group(1), sequence, self._raw_body()
                )
                self._send(HTTPStatus.OK, result)
                return

            payload = self._body()
            if parsed.path == "/api/runtime/restart":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self._send(HTTPStatus.FORBIDDEN, {"error": "local_only"})
                    return
                self._send(HTTPStatus.ACCEPTED, {"status": "restarting"})
                threading.Timer(0.1, self.server.state.runtime_restart).start()
            elif parsed.path == "/api/sessions/start":
                self._send(HTTPStatus.CREATED, self.server.state.create_session(payload))
            elif session_match and session_match.group(2) == "resume":
                self._send(HTTPStatus.OK, self.server.state.resume_session(session_match.group(1), payload))
            elif session_match and session_match.group(2) == "events":
                self._send(
                    HTTPStatus.OK,
                    self.server.state.sessions.append_event(
                        session_match.group(1), payload, assign_sequence=True
                    ),
                )
            elif session_match and session_match.group(2) == "finalize":
                self._send(
                    HTTPStatus.OK,
                    self.server.state.finalize_session(session_match.group(1), payload),
                )
            elif parsed.path == "/api/context/retrieve":
                self._retrieve(payload)
            elif parsed.path == "/api/translate":
                self._translate(payload)
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (PackValidationError, SessionStoreError) as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": str(error)})
        except OSError as error:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": "session_storage_failed",
                "message": str(error),
                "recordingShouldContinue": True,
            })

    def _retrieve(self, payload: dict[str, Any]) -> None:
        source_text = str(payload.get("sourceTextEn") or "").strip()
        if not source_text:
            raise PackValidationError("sourceTextEn is required")
        try:
            limit = int(payload.get("limit", 5))
        except (TypeError, ValueError) as error:
            raise PackValidationError("limit must be an integer from 1 to 8") from error
        if not 1 <= limit <= 8:
            raise PackValidationError("limit must be an integer from 1 to 8")
        cursor_sequence = self._cursor_sequence(payload)
        context_policy = self._context_policy(payload)
        pack = self.server.state.pack
        hits = (
            retrieve(pack, source_text, limit=limit, cursor_sequence=cursor_sequence)
            if pack and context_policy != "none" else []
        )
        self._send(HTTPStatus.OK, {
            "sourceTextEn": source_text,
            "packVersion": pack.get("packVersion") if pack else None,
            "contextPolicy": context_policy,
            "hits": hits,
            "promptContext": prompt_context(hits, policy=context_policy),
            "alignment": alignment_summary(hits, cursor_sequence),
            "fallback": "no_context" if not hits else None,
        })

    def _translate(self, payload: dict[str, Any]) -> None:
        source_text = str(payload.get("sourceTextEn") or "").strip()
        if not source_text:
            raise PackValidationError("sourceTextEn is required")
        cursor_sequence = self._cursor_sequence(payload)
        context_policy = self._context_policy(payload)
        if payload.get("useContext") is False:
            context_policy = "none"
        try:
            result = self.server.state.translate(source_text, cursor_sequence, context_policy)
        except OllamaError as error:
            pack = self.server.state.pack
            hits = (
                retrieve(pack, source_text, limit=5, cursor_sequence=cursor_sequence)
                if pack and context_policy != "none" else []
            )
            alignment = alignment_summary(hits, cursor_sequence)
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "translation_unavailable",
                "message": str(error),
                "recordingShouldContinue": True,
                "fallback": "show_english_only",
                "requestedContextPolicy": context_policy,
                "contextPolicy": context_policy if hits else "none",
                "contextHitIds": [hit["entryId"] for hit in hits],
                "alignment": alignment,
            })
            return
        self._send(HTTPStatus.OK, {
            **result,
        })

    @staticmethod
    def _cursor_sequence(payload: dict[str, Any]) -> int | None:
        value = payload.get("cursorSequence")
        if value is None:
            return None
        try:
            cursor_sequence = int(value)
        except (TypeError, ValueError) as error:
            raise PackValidationError("cursorSequence must be a positive integer") from error
        if cursor_sequence < 1:
            raise PackValidationError("cursorSequence must be a positive integer")
        return cursor_sequence

    def _context_policy(self, payload: dict[str, Any]) -> str:
        return self.server.state.resolve_context_policy(payload.get("contextPolicy"))


def create_server(host: str, port: int, state: GatewayState) -> GatewayServer:
    server = GatewayServer((host, port), Handler)
    server.state = state
    return server


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run the local live caption gateway.")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8766)
    command.add_argument("--pack", default=os.environ.get("LOCAL_LIVE_WEEKLY_PACK", ""))
    command.add_argument(
        "--ollama-model",
        default=os.environ.get("LOCAL_LIVE_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
    )
    command.add_argument("--ollama-url", default=os.environ.get("LOCAL_LIVE_OLLAMA_URL", "http://127.0.0.1:11434"))
    command.add_argument(
        "--session-root",
        default=os.environ.get("LOCAL_LIVE_SESSION_ROOT", "artifacts/sessions"),
    )
    command.add_argument(
        "--asr-model",
        default=os.environ.get("LOCAL_LIVE_ASR_MODEL", "artifacts/models/ggml-base.en.bin"),
    )
    command.add_argument(
        "--whisper-binary",
        default=os.environ.get("LOCAL_LIVE_WHISPER_BINARY", "whisper-cli"),
    )
    command.add_argument(
        "--asr-provider",
        choices=("whisper-cli", "qwen-mlx-websocket"),
        default=os.environ.get("LOCAL_LIVE_ASR_PROVIDER", "whisper-cli"),
    )
    command.add_argument(
        "--mlx-audio-url",
        default=os.environ.get(
            "LOCAL_LIVE_MLX_AUDIO_URL",
            "ws://127.0.0.1:18766/v1/audio/transcriptions/realtime",
        ),
    )
    command.add_argument(
        "--mlx-audio-model",
        default=os.environ.get("LOCAL_LIVE_QWEN_ASR_MODEL", ""),
    )
    command.add_argument(
        "--ws-port",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_WS_PORT", "8767")),
    )
    command.add_argument(
        "--viewer-port",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_VIEWER_PORT", "8780")),
    )
    command.add_argument(
        "--context-policy",
        choices=tuple(sorted(CONTEXT_POLICIES)),
        default=os.environ.get("LOCAL_LIVE_CONTEXT_POLICY", "none"),
    )
    command.add_argument(
        "--caption-presentation-policy",
        choices=tuple(sorted(CAPTION_PRESENTATION_POLICIES)),
        default=os.environ.get(
            "LOCAL_LIVE_CAPTION_PRESENTATION_POLICY",
            "readable_chunks",
        ),
    )
    command.add_argument(
        "--vad-threshold-rms",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_VAD_THRESHOLD_RMS", "150")),
    )
    command.add_argument(
        "--translation-unit-policy", choices=TRANSLATION_UNIT_POLICIES,
        default=os.environ.get("LOCAL_LIVE_TRANSLATION_UNIT_POLICY", "legacy"),
    )
    command.add_argument(
        "--source-fragment-policy", choices=("content_words", "off"),
        default=os.environ.get("LOCAL_LIVE_SOURCE_FRAGMENT_POLICY", "content_words"),
    )
    command.add_argument(
        "--frontend-origin", type=validate_frontend_origin,
        default=os.environ.get("LOCAL_LIVE_FRONTEND_ORIGIN", "http://127.0.0.1:4173"),
    )
    command.add_argument(
        "--vad-silence-ms",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_VAD_SILENCE_MS", "500")),
    )
    command.add_argument(
        "--vad-max-segment-ms",
        type=int,
        default=int(os.environ.get("LOCAL_LIVE_VAD_MAX_SEGMENT_MS", "3000")),
    )
    return command


def main() -> None:
    arguments = parser().parse_args()
    if arguments.pack and not Path(arguments.pack).is_file():
        raise SystemExit(f"weekly pack not found: {arguments.pack}")
    state = GatewayState(
        pack_path=arguments.pack,
        ollama_model=arguments.ollama_model,
        ollama_url=arguments.ollama_url,
        session_root=arguments.session_root,
        asr_model=arguments.asr_model,
        whisper_binary=arguments.whisper_binary,
        vad_threshold_rms=arguments.vad_threshold_rms,
        vad_silence_ms=arguments.vad_silence_ms,
        vad_max_segment_ms=arguments.vad_max_segment_ms,
        ws_port=arguments.ws_port,
        asr_provider=arguments.asr_provider,
        mlx_audio_url=arguments.mlx_audio_url,
        mlx_audio_model=arguments.mlx_audio_model,
        viewer_port=arguments.viewer_port,
        default_context_policy=arguments.context_policy,
        caption_presentation_policy=arguments.caption_presentation_policy,
        translation_unit_policy=arguments.translation_unit_policy,
        source_fragment_policy=arguments.source_fragment_policy,
        frontend_origin=arguments.frontend_origin,
    )
    server = create_server(arguments.host, arguments.port, state)
    try:
        from .live_server import LiveSocketService
    except ImportError as error:
        raise SystemExit("WebSocket dependency missing; run pip install -r requirements.txt") from error
    live_socket = LiveSocketService(state, arguments.host, arguments.ws_port)
    viewer = ViewerService(state.caption_hub, "0.0.0.0", arguments.viewer_port)
    storage_health = state.sessions.health(probe_write=True)
    recovered_sessions = state.sessions.recover_incomplete() if storage_health.get("available") else []
    try:
        state.ollama_warmup = state.ollama.warmup()
    except OllamaError as error:
        state.ollama_warmup = {"ready": False, "error": str(error)}
    try:
        state.asr_warmup = state.asr.warmup()
    except AsrError as error:
        state.asr_warmup = {"ready": False, "error": str(error)}
    ollama_version = None
    model_digest = None
    try:
        ollama_version = state.ollama._json("/api/version", timeout=1.5).get("version")
        tags = state.ollama._json("/api/tags", timeout=1.5).get("models", [])
        model_digest = next((model.get("digest") for model in tags if model.get("name") == state.ollama.model), None)
    except OllamaError:
        pass
    startup_asr_status = state.asr.status()
    state.capture_runtime_identity(
        provider_versions={"ollama": ollama_version}, translation_model_digest=model_digest,
        asr_status=startup_asr_status,
    )
    live_socket.start()
    viewer.start()
    print(json.dumps({
        "gateway": f"http://{arguments.host}:{arguments.port}",
        "liveWebSocket": f"ws://{arguments.host}:{arguments.ws_port}/api/live",
        "viewer": viewer_urls("{session-token}", viewer.port),
        "packVersion": state.pack.get("packVersion") if state.pack else None,
        "ollamaModel": arguments.ollama_model or None,
        "asr": startup_asr_status,
        "captionPresentationPolicy": state.caption_presentation_policy,
        "sessionRoot": str(state.sessions.root),
        "sessionStorage": storage_health,
        "recoveredIncompleteSessions": [session["sessionId"] for session in recovered_sessions],
    }, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        live_socket.stop()
        viewer.stop()
        if state.public_caption_publisher:
            state.public_caption_publisher.stop()
        server.server_close()


if __name__ == "__main__":
    main()
