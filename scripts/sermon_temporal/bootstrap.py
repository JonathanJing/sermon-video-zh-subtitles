"""Install pinned SDK/CLI only under artifacts/temporal/runtime; no global writes."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request

from scripts.sermon_execution_harness import atomic_json
from .local_io import TEMPORAL_ROOT

CLI_VERSION = "1.8.3"
SDK_VERSION = "1.32.0"


def install(runtime: Path):
    runtime = runtime.resolve()
    if not runtime.is_relative_to(TEMPORAL_ROOT.resolve()):
        raise ValueError("Runtime must remain inside artifacts/temporal")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv is required to create the isolated runtime; no global installation is performed")
    runtime.mkdir(parents=True, exist_ok=True)
    python = runtime / "venv" / "bin" / "python"
    if not python.exists():
        subprocess.run([uv, "venv", str(runtime / "venv"), "--python", "3.11"], check=True)
    subprocess.run([uv, "pip", "install", "--python", str(python), f"temporalio=={SDK_VERSION}"], check=True)
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    architecture = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
    if not system or not architecture:
        raise ValueError("Unsupported local CLI platform")
    name = f"temporal_cli_{CLI_VERSION}_{system}_{architecture}.tar.gz"
    base = f"https://github.com/temporalio/cli/releases/download/v{CLI_VERSION}/"
    checksums = urllib.request.urlopen(base + "checksums.txt", timeout=30).read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name)
    archive_bytes = urllib.request.urlopen(base + name, timeout=60).read()
    actual = hashlib.sha256(archive_bytes).hexdigest()
    if expected != actual:
        raise ValueError("Official CLI archive checksum did not match")
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        candidates = [member for member in archive.getmembers() if member.name == "temporal" and member.isfile()]
        if len(candidates) != 1:
            raise ValueError("Unexpected CLI archive layout")
        binary_bytes = archive.extractfile(candidates[0]).read()
    binary = runtime / "temporal"
    binary_hash = hashlib.sha256(binary_bytes).hexdigest()
    if binary.exists() and hashlib.sha256(binary.read_bytes()).hexdigest() != binary_hash:
        raise ValueError("Existing CLI differs; preserve it and its database before an explicit migration")
    if not binary.exists():
        binary.write_bytes(binary_bytes)
        binary.chmod(0o755)
    manifest = {"schemaVersion": 1, "temporalCliVersion": CLI_VERSION, "temporalPythonSdk": SDK_VERSION,
                "download": base + name, "archiveSha256": actual, "binarySha256": binary_hash,
                "platform": f"{system}_{architecture}", "python": str(python)}
    atomic_json(runtime / "runtime-manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=TEMPORAL_ROOT / "runtime")
    print(json.dumps(install(parser.parse_args().runtime), indent=2))


if __name__ == "__main__":
    main()
