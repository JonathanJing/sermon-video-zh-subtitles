from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


GCS_RE = re.compile(r"^gs://(?P<bucket>[^/]+)/(?P<object>.+)$")
SECRET_RE = re.compile(
    r"^projects/(?P<project>[^/\s]+)/secrets/(?P<secret>[^/\s]+)(?:/versions/(?P<version>[^/\s]+))?$"
)


@dataclass(frozen=True)
class GcsUri:
    bucket: str
    object_name: str
    uri: str


def parse_gcs_uri(uri: str) -> GcsUri:
    match = GCS_RE.fullmatch(uri)
    if not match:
        raise ValueError(f"invalid GCS URI: {uri}")
    return GcsUri(match.group("bucket"), match.group("object"), uri)


def read_gcs_text(uri: str) -> str:
    return read_gcs_bytes(uri).decode("utf-8")


def read_gcs_bytes(uri: str) -> bytes:
    parsed = parse_gcs_uri(uri)
    try:
        from google.cloud import storage  # type: ignore

        client = storage.Client()
        return client.bucket(parsed.bucket).blob(parsed.object_name).download_as_bytes()
    except ImportError:
        completed = subprocess.run(
            ["gcloud", "storage", "cat", uri],
            check=True,
            capture_output=True,
        )
        return completed.stdout


def upload_file_to_gcs(local_path: str | Path, uri: str) -> None:
    parsed = parse_gcs_uri(uri)
    path = Path(local_path)
    try:
        from google.cloud import storage  # type: ignore

        client = storage.Client()
        client.bucket(parsed.bucket).blob(parsed.object_name).upload_from_filename(str(path))
    except ImportError:
        subprocess.run(["gcloud", "storage", "cp", str(path), uri], check=True)


def write_gcs_text(uri: str, text: str, content_type: str = "application/json; charset=utf-8") -> None:
    parsed = parse_gcs_uri(uri)
    try:
        from google.cloud import storage  # type: ignore

        client = storage.Client()
        client.bucket(parsed.bucket).blob(parsed.object_name).upload_from_string(
            text,
            content_type=content_type,
        )
    except ImportError:
        import tempfile

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        try:
            subprocess.run(["gcloud", "storage", "cp", str(temp_path), uri], check=True)
        finally:
            temp_path.unlink(missing_ok=True)


def access_secret(resource_name: str) -> str:
    match = SECRET_RE.fullmatch(resource_name)
    if not match:
        raise RuntimeError("Invalid Secret Manager resource name.")
    version = match.group("version") or "latest"
    full_name = (
        f"projects/{match.group('project')}/secrets/{match.group('secret')}/versions/{version}"
    )
    try:
        from google.cloud import secretmanager  # type: ignore

        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": full_name})
        value = response.payload.data.decode("utf-8").strip()
    except ImportError:
        proc = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                version,
                "--secret",
                match.group("secret"),
                "--project",
                match.group("project"),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        value = proc.stdout.strip()
    if not value:
        raise RuntimeError(f"Secret {resource_name} returned an empty value.")
    return value
