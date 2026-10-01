#!/usr/bin/env python3
"""Stage the same verified v2 audition media and UI over Dev or Production; never deploy."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "voice-demos/speaker-clips-v2"
SCHEMA = "sermon-speaker-clip-demo-ui-overlay-v2"
WEB = ROOT / "experiments/sermon-dubbing-poc/web"
DEV = ROOT / "firebase/dev/public"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1048576), b""):
            result.update(block)
    return result.hexdigest()


def inventory(public):
    files = []
    for path in sorted(public.rglob("*")):
        require(not path.is_symlink(), "Hosting candidates must not contain symlinks")
        if path.is_file():
            files.append({"path": path.relative_to(public).as_posix(),
                          "sha256": digest(path), "bytes": path.stat().st_size})
    return files


def validate_clips(root):
    require(root.is_dir() and not root.is_symlink(), "Use a regular clip candidate directory")
    catalog_path = root / "catalog.json"
    require(catalog_path.is_file() and not catalog_path.is_symlink(), "Complete v2 catalog is required")
    # Reuse the exact client contract, so the server overlay cannot admit a catalog its reader rejects.
    check = """import {readFile} from 'node:fs/promises';
import {validateSpeakerClips} from './experiments/sermon-dubbing-poc/web/speaker-clip-demos.mjs';
await validateSpeakerClips(JSON.parse(await readFile(process.argv[1], 'utf8')));"""
    subprocess.run(["node", "--input-type=module", "-e", check, str(catalog_path.resolve())],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    listed = {}
    for speaker in catalog["speakers"]:
        for asset in [speaker["original"], speaker["video"], *speaker["samples"]]:
            relative = asset["path"].removeprefix("/" + PREFIX + "/")
            path = root / relative
            require(path.resolve().is_relative_to(root.resolve()) and path.is_file()
                    and not any(parent.is_symlink() for parent in [path, *path.parents]
                            if parent.is_relative_to(root)), "Unsafe clip media path")
            require(path.stat().st_size == asset["bytes"] and digest(path) == asset["sha256"],
                    "Clip media differs from its catalog hash/bytes")
            metadata = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                "-of", "json", str(path)], text=True))
            kinds = {stream["codec_type"] for stream in metadata["streams"]}
            require("audio" in kinds and (asset is not speaker["video"] or "video" in kinds)
                    and abs(float(metadata["format"]["duration"]) - asset["durationSeconds"]) <= .5,
                    "Clip media stream/duration differs from its catalog")
            listed[asset["path"].lstrip("/")] = path
    require(len(listed) == 30, "Six originals, six videos and 18 AI samples are required")
    return catalog, listed


def patch_entry(path, reader):
    html = path.read_text(encoding="utf-8")
    script = "voice-demo.mjs" if reader == "dev" else "voice-samples.mjs"
    marker = f'src="/{script}"'
    require(html.count(marker) <= 1 and html.count("</body>") == 1, "Duplicate or unsupported reader entry")
    if marker not in html:
        html = html.replace("</body>", f'  <script type="module" src="/{script}"></script>\n</body>')
    css = 'href="/voice-demo.css"'
    require(html.count(css) <= 1, "Duplicate demo stylesheet")
    if reader == "dev" and css not in html:
        require(html.count("</head>") == 1, "Unsupported Dev reader head")
        html = html.replace("</head>", '  <link rel="stylesheet" href="/voice-demo.css">\n</head>')
    path.write_text(html, encoding="utf-8")


def stage(base, clips, reader, out):
    require(reader in {"dev", "production"} and not out.exists() and not out.is_symlink(),
            "Use Dev/Production and a new candidate directory")
    require(not out.resolve().is_relative_to(base.resolve()), "Output must be outside the baseline snapshot")
    public_base = base / "public"
    require(public_base.is_dir() and (base / "firebase.json").is_file() and not (base / "firebase.json").is_symlink(), "Hosting snapshot is required")
    _, assets = validate_clips(clips)
    before = inventory(public_base)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(public_base, public)
        shutil.copyfile(base / "firebase.json", temporary / "firebase.json")
        for name, source in assets.items():
            target = public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        catalog_target = public / PREFIX / "catalog.json"
        shutil.copyfile(clips / "catalog.json", catalog_target)
        ui = ["speaker-clip-demos.mjs", "voice-demo.css", "voice-demo.mjs" if reader == "dev" else "voice-samples.mjs"]
        source_ui = DEV if reader == "dev" else WEB
        for name in ui:
            shutil.copyfile(source_ui / name, public / name)
        require((public / "icons.mjs").is_file() and (public / "icons.svg").is_file(), "Shared SVG icon files are required")
        entries = [public / "index.html"]
        if reader == "dev":
            entries += [public / name for name in ["multilingual-reader.html", "dev-poc.html"] if (public / name).is_file()]
        for entry in entries:
            require(('id="moreOptions"' if reader == "dev" else 'id="voice-grid"') in entry.read_text(encoding="utf-8"), "Wrong reader type")
            patch_entry(entry, reader)
        after = inventory(public)
        old = {item["path"]: item for item in before}
        current = {item["path"]: item for item in after}
        modified = sorted(name for name in old if old[name] != current.get(name))
        added = sorted(set(current) - set(old))
        allowed = set(assets) | {f"{PREFIX}/catalog.json", *ui, *(entry.name for entry in entries)}
        require(set(modified + added) <= allowed and set(old) <= set(current), "Unrelated Hosting files changed")
        report = {"schemaVersion": SCHEMA, "status": "validated_not_deployed", "reader": reader,
                  "catalogSha256": digest(catalog_target), "firebaseConfigSha256": digest(temporary / "firebase.json"),
                  "baseFiles": before, "files": after, "modifiedFiles": modified, "addedFiles": added,
                  "uiSha256": {name: digest(public / name) for name in ui}}
        (temporary / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verify(temporary)
        os.rename(temporary, out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def verify(candidate):
    report = json.loads((candidate / "build-report.json").read_text(encoding="utf-8"))
    require(report.get("schemaVersion") == SCHEMA and report.get("status") == "validated_not_deployed", "Invalid demo overlay report")
    public = candidate / "public"
    require(inventory(public) == report["files"] and digest(candidate / "firebase.json") == report["firebaseConfigSha256"], "Candidate files changed")
    require(digest(public / PREFIX / "catalog.json") == report["catalogSha256"], "Catalog changed")
    validate_clips(public / PREFIX)
    for name, expected in report["uiSha256"].items():
        require(digest(public / name) == expected, "Demo UI changed")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-candidate", required=True, type=Path)
    parser.add_argument("--clip-demo-root", required=True, type=Path)
    parser.add_argument("--reader", required=True, choices=["dev", "production"])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = stage(args.base_candidate, args.clip_demo_root, args.reader, args.out)
    print(json.dumps({"status": report["status"], "reader": report["reader"], "catalogSha256": report["catalogSha256"]}))


if __name__ == "__main__":
    main()
