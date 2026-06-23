from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from .config import AppConfig, current_sunday
from .storage import ArtifactReader


SUNDAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PUBLIC_ARTIFACT_EXTENSIONS = {
    ".js": "application/javascript; charset=utf-8",
    ".vtt": "text/vtt; charset=utf-8",
    ".srt": "application/x-subrip; charset=utf-8",
}


@dataclass(frozen=True)
class PublicArtifact:
    key: str
    local_path: str
    gcs_uri: str
    content_type: str


class SundaySliceService:
    def __init__(self, config: AppConfig, reader: ArtifactReader):
        self.config = config
        self.reader = reader

    def get_public_slice(self, sunday: str) -> dict[str, Any]:
        manifest_uri = self.manifest_uri_for(sunday)
        manifest = self._read_json(manifest_uri)
        artifacts = self._public_artifacts(manifest)
        report = self._read_report(manifest)
        playback = self._read_playback_simulation(manifest)
        resolved_sunday = self._resolve_sunday(sunday)
        route_sunday = "current" if sunday == "current" else resolved_sunday
        return {
            "schemaVersion": 1,
            "sunday": resolved_sunday,
            "status": manifest.get("status", "ready"),
            "sermonTitle": self._sermon_title(report),
            "translationStatus": self._translation_status(manifest, report),
            "totalSegments": self._report_number(report, "totalSegments") or self._total_segments(playback),
            "translatedSegments": self._report_number(report, "translatedSegments") or self._translated_segments(playback),
            "readyTime": manifest.get("readyTime") or manifest.get("promotedAt"),
            "lastUpdated": manifest.get("updatedAt") or manifest.get("promotedAt"),
            "artifactCount": len(artifacts),
            "artifacts": [
                {
                    "key": artifact.key,
                    "contentType": artifact.content_type,
                    "apiPath": f"/api/sundays/{route_sunday}/artifacts/{artifact.key}",
                    "localPath": artifact.local_path,
                }
                for artifact in artifacts
            ],
        }

    def read_public_artifact(self, sunday: str, key: str) -> tuple[bytes, str]:
        manifest = self._read_json(self.manifest_uri_for(sunday))
        for artifact in self._public_artifacts(manifest):
            if artifact.key == key:
                return self.reader.read_bytes(artifact.gcs_uri), artifact.content_type
        raise KeyError(key)

    def manifest_uri_for(self, sunday: str) -> str:
        resolved = self._resolve_sunday(sunday)
        if sunday == "current" and self.config.current_manifest_uri:
            return self.config.current_manifest_uri
        if self.config.sunday_manifest_uri_template:
            return self.config.sunday_manifest_uri_template.format(sunday=resolved)
        if not self.config.artifact_bucket:
            raise ValueError("SERMON_ARTIFACT_BUCKET is required for Sunday manifests")
        prefix = self.config.artifact_prefix.strip("/")
        object_name = f"{prefix}/{resolved}/cloud-manifest.json" if prefix else f"{resolved}/cloud-manifest.json"
        return f"gs://{self.config.artifact_bucket}/{object_name}"

    def _resolve_sunday(self, sunday: str) -> str:
        if sunday == "current":
            return current_sunday(timezone=self.config.timezone).isoformat()
        if not SUNDAY_RE.fullmatch(sunday):
            raise ValueError("Sunday must be current or YYYY-MM-DD")
        parsed = date.fromisoformat(sunday)
        if parsed.weekday() != 6:
            raise ValueError("Sunday slice date must be a Sunday")
        return sunday

    def _read_json(self, uri: str) -> dict[str, Any]:
        return json.loads(self.reader.read_text(uri))

    def _public_artifacts(self, manifest: dict[str, Any]) -> list[PublicArtifact]:
        if manifest.get("apiKeyMaterialIncluded") is True:
            raise ValueError("manifest says API key material is included")
        artifacts = []
        for item in manifest.get("outputs", []):
            local_path = item.get("localPath", "")
            gcs_uri = item.get("gcsUri", "")
            suffix = PurePosixPath(local_path).suffix.lower()
            if suffix not in PUBLIC_ARTIFACT_EXTENSIONS:
                continue
            if "/secrets/" in local_path or "/secrets/" in gcs_uri:
                continue
            key = self._artifact_key(local_path)
            artifacts.append(
                PublicArtifact(
                    key=key,
                    local_path=local_path,
                    gcs_uri=gcs_uri,
                    content_type=PUBLIC_ARTIFACT_EXTENSIONS[suffix],
                )
            )
        return sorted(artifacts, key=lambda item: item.key)

    def _artifact_key(self, local_path: str) -> str:
        path = PurePosixPath(local_path)
        suffix = path.suffix.lower()
        if path.name == "playback-simulation.generated.js":
            return "playback-js"
        stem = path.stem.replace(".", "-")
        if suffix == ".vtt":
            return f"{stem}-vtt"
        if suffix == ".srt":
            return f"{stem}-srt"
        return path.name.replace(".", "-")

    def _read_report(self, manifest: dict[str, Any]) -> dict[str, Any] | None:
        for item in manifest.get("outputs", []):
            if item.get("localPath") == "artifacts/report.json" and item.get("gcsUri"):
                try:
                    return self._read_json(item["gcsUri"])
                except Exception:
                    return None
        return None

    def _read_playback_simulation(self, manifest: dict[str, Any]) -> dict[str, Any] | None:
        for item in manifest.get("outputs", []):
            if item.get("localPath") == "web/playback-simulation.generated.js" and item.get("gcsUri"):
                try:
                    text = self.reader.read_text(item["gcsUri"])
                except Exception:
                    return None
                prefix = "window.SERMON_PLAYBACK_SIMULATION = "
                if not text.startswith(prefix):
                    return None
                try:
                    return json.loads(text[len(prefix) :].rstrip(";\n"))
                except json.JSONDecodeError:
                    return None
        return None

    def _sermon_title(self, report: dict[str, Any] | None) -> str | None:
        if not report:
            return None
        candidate = report.get("sermon_candidate") or report.get("live") or {}
        return candidate.get("title")

    def _translation_status(self, manifest: dict[str, Any], report: dict[str, Any] | None) -> str:
        if manifest.get("translationStatus"):
            return str(manifest["translationStatus"])
        if not report:
            return "unknown"
        if report.get("translation_status"):
            return str(report["translation_status"])
        return "source-captions-ready"

    def _report_number(self, report: dict[str, Any] | None, key: str) -> int | None:
        if not report:
            return None
        value = report.get(key)
        return value if isinstance(value, int) else None

    def _total_segments(self, playback: dict[str, Any] | None) -> int | None:
        if not playback:
            return None
        segments = playback.get("segments")
        return len(segments) if isinstance(segments, list) else None

    def _translated_segments(self, playback: dict[str, Any] | None) -> int | None:
        if not playback:
            return None
        segments = playback.get("segments")
        if not isinstance(segments, list):
            return None
        count = 0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            zh = str(segment.get("zh") or "").strip()
            if segment.get("translationStatus") == "ready" or (zh and not zh.startswith("AI 中文待生成")):
                count += 1
        return count
