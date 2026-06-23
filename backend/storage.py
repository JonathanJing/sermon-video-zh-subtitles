from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class GcsUri:
    bucket: str
    object_name: str

    @property
    def uri(self) -> str:
        return f"gs://{self.bucket}/{self.object_name}"


def parse_gcs_uri(value: str) -> GcsUri:
    if not value.startswith("gs://"):
        raise ValueError(f"expected gs:// URI, got {value!r}")
    rest = value[5:]
    bucket, sep, object_name = rest.partition("/")
    if not bucket or not sep or not object_name:
        raise ValueError(f"expected gs://bucket/object URI, got {value!r}")
    if any(part in {".", ".."} for part in object_name.split("/")):
        raise ValueError(f"unsafe GCS object path in {value!r}")
    return GcsUri(bucket=bucket, object_name=object_name)


class ArtifactReader:
    def read_text(self, uri: str) -> str:
        raise NotImplementedError

    def read_bytes(self, uri: str) -> bytes:
        return self.read_text(uri).encode("utf-8")


class LocalArtifactReader(ArtifactReader):
    def __init__(self, root: Path):
        self.root = root.resolve()

    def read_text(self, uri: str) -> str:
        return self._resolve(uri).read_text(encoding="utf-8")

    def read_bytes(self, uri: str) -> bytes:
        return self._resolve(uri).read_bytes()

    def _resolve(self, uri: str) -> Path:
        path = Path(uri)
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()
        if self.root not in {resolved, *resolved.parents}:
            raise ValueError(f"path escapes artifact root: {uri}")
        return resolved


class GcsArtifactReader(ArtifactReader):
    def __init__(self, storage_client=None):
        self.storage_client = storage_client

    def read_text(self, uri: str) -> str:
        return self.read_bytes(uri).decode("utf-8")

    def read_bytes(self, uri: str) -> bytes:
        parsed = parse_gcs_uri(uri)
        client = self.storage_client or self._default_client()
        if client is not None:
            bucket = client.bucket(parsed.bucket)
            return bucket.blob(parsed.object_name).download_as_bytes()
        return self._read_with_authenticated_http(parsed)

    def _default_client(self):
        try:
            from google.cloud import storage  # type: ignore
        except ImportError:
            return None
        return storage.Client()

    def _read_with_authenticated_http(self, parsed: GcsUri) -> bytes:
        token = self._metadata_token()
        object_path = quote(parsed.object_name, safe="")
        url = (
            "https://storage.googleapis.com/storage/v1/b/"
            f"{quote(parsed.bucket, safe='')}/o/{object_path}?alt=media"
        )
        request = Request(url, headers={"Authorization": f"Bearer {token}"})
        with urlopen(request, timeout=20) as response:
            return response.read()

    def _metadata_token(self) -> str:
        request = Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urlopen(request, timeout=5) as response:
            data = response.read().decode("utf-8")
        import json

        return json.loads(data)["access_token"]

