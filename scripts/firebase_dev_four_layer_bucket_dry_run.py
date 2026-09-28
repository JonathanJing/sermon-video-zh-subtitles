#!/usr/bin/env python3
"""Run a bounded Layer 1–4 simulation from a linked clip into a Dev candidate.

The clip and reviewed parent-week assets are test inputs. Every derived package
is marked simulation_only. This never writes the Production v3 catalog or
claims that approval of the parent recording approves the new clip identity.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

try:
    from scripts import assemble_multilingual_v3_update as weekly
except ImportError:
    import assemble_multilingual_v3_update as weekly


SOURCE_PAGE = "2026-09-27-weekend-sermon-drive-530"
LOCALES = ("zh-Hans", "ko", "es")
START = 213.44
END = 243.56
DURATION = END - START
UNIT_IDS = tuple(f"0-u{i:03}" for i in range(47, 53))
DEV_SITE = "ai-for-god-sermon-audio-dev"
DEV_BUCKET = "ai-for-god-sermon-media-dev"
DEV_ORIGIN = "https://ai-for-god-sermon-audio-dev.web.app"


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    return sha(path)


def begin() -> tuple[str, int]:
    return datetime.now(timezone.utc).isoformat(), time.monotonic_ns()


def finish(events: list[dict], name: str, started: tuple[str, int], **details: object) -> None:
    events.append({"name": name, "startedAt": started[0],
                   "finishedAt": datetime.now(timezone.utc).isoformat(),
                   "elapsedMs": round((time.monotonic_ns() - started[1]) / 1_000_000, 3),
                   **details})


def duration(path: Path) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                            check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def fetch_clip(url: str, target: Path, expected_sha: str) -> str:
    parsed = urlparse(url)
    if (parsed.scheme not in {"file", "http", "https"} or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("Dry-run source must be a credential-free file or HTTP link")
    with urlopen(url, timeout=60) as source, target.open("wb") as output:
        size = 0
        while block := source.read(1024 * 1024):
            size += len(block)
            if size > 50 * 1024 * 1024:
                raise ValueError("Simulated intake clip exceeds 50 MiB")
            output.write(block)
    actual = sha(target)
    if actual != expected_sha:
        raise ValueError("Simulated intake clip SHA differs")
    if abs(duration(target) - DURATION) > 0.2:
        raise ValueError("Simulated intake clip duration differs")
    return actual


def prove_clip_from_parent(parent: Path, clip: Path, expected_sha: str) -> None:
    """Reproduce the documented 9/27 cut, rather than trusting a same-length upload."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(START),
                    "-i", str(parent), "-t", str(DURATION), "-vf", "scale=1280:-2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
                    "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                    "-y", str(clip)], check=True)
    if sha(clip) != expected_sha:
        raise ValueError("Intake clip is not the specified cut of the parent video")


def clip_audio(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(START),
                    "-i", str(source), "-t", str(DURATION), "-vn", "-ac", "1",
                    "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "64k", "-y", str(target)],
                   check=True)
    if abs(duration(target) - DURATION) > 0.2:
        raise ValueError(f"Clipped audio duration differs: {source.name}")
    return sha(target)


def rebase(cue: dict) -> dict:
    result = deepcopy(cue)
    result["start"] = round(float(result["start"]) - START, 5)
    result["end"] = round(float(result["end"]) - START, 5)
    if result["start"] < -0.02 or result["end"] > DURATION + 0.05:
        raise ValueError("Selected cue crosses clip boundary")
    result["start"] = max(0.0, result["start"])
    return result


def page_html(locale: str, page_id: str, blocks: list[dict], video_url: str) -> str:
    titles = {"zh-Hans": "中文", "ko": "한국어", "es": "Español"}
    links = " · ".join(
        f'<a href="/pages/{page_id}/{code}/index.html">{label}</a>'
        for code, label in titles.items())
    rows = "\n".join(
        f'<li data-start="{block["start"]:.2f}"><strong>{html.escape(block["text"])}</strong>'
        f'<small lang="en">{html.escape(block["english"])}</small></li>'
        for block in blocks)
    return f'''<!doctype html>
<html lang="{locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>DEV 模拟 · 启示录 · 耶稣配得</title>
<link rel="stylesheet" href="/pages/{SOURCE_PAGE}/style.css"></head><body><main>
<p class="notice"><strong>DEV DRY RUN · simulation_only</strong><br>9/27 原视频 03:33.44–04:03.56 截片；
从模拟链接进入 Layer 1–4。文字与音轨来自已审整篇的对应区间，截片本身没有新的人工审核。
本页只测试发布结构与媒体读取，不是本周正式证道页面。</p>
<h1>启示录：耶稣带来的安慰与盼望 · 耶稣配得</h1><nav>{links}</nav>
<video controls playsinline preload="none" src="{html.escape(video_url)}"></video>
<p>三语配音截片：</p><audio controls preload="none" src="/media/{page_id}/{locale}.mp3"></audio>
<h2>文稿 · 英文对照</h2><ol>{rows}</ol>
<p><small>来源：Mariners Church 9/27 视频；本项目与该教会无隶属关系。音频与视频为独立试听控件。</small></p>
</main></body></html>\n'''


def clone(source: str, target: str) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def build(*, source_url: str, expected_clip_sha: str, parent_video: Path,
          parent_sha: str, anchor_manifest: Path, english_source_package: Path,
          reference_public: Path, baseline_preflight: Path,
          base_dev: Path, page_id: str, out: Path) -> dict:
    if out.exists() or out.is_symlink():
        raise ValueError("Output already exists")
    if not page_id.startswith("dryrun-20260927-") or not page_id.replace("-", "").isalnum():
        raise ValueError("Use a distinct 9/27 dry-run page ID")
    if sha(parent_video) != parent_sha or abs(duration(parent_video) - 1891.673333) > 0.1:
        raise ValueError("Parent video identity differs")
    config = read(base_dev / "firebase.json")
    if config.get("hosting", {}).get("site") != DEV_SITE:
        raise ValueError("Baseline is not the complete Firebase Dev site")
    if not (base_dev / "public/multilingual-v3.json").is_file():
        raise ValueError("Dev baseline lacks the App catalog")
    if not (base_dev / f"public/pages/{SOURCE_PAGE}/style.css").is_file():
        raise ValueError("Dev baseline lacks the published page stylesheet")
    preflight = read(baseline_preflight)
    base_files = weekly.regular_files(base_dev / "public")
    checked = {item["path"]: item["sha256"] for item in preflight.get("files", [])}
    age = (datetime.now(timezone.utc)
           - datetime.fromisoformat(preflight.get("checkedAt", "1970-01-01T00:00:00+00:00")))
    if (preflight.get("status") != "pass" or preflight.get("origin") != DEV_ORIGIN
            or preflight.get("fileCount") != len(base_files)
            or set(checked) != set(base_files)
            or age.total_seconds() < 0 or age.total_seconds() > 3600
            or any(checked[name] != sha(path) for name, path in base_files.items())):
        raise ValueError("Complete live Dev baseline preflight is missing or stale")
    if any((base_dev / "public" / path).exists() for path in (
            f"pages/{page_id}", f"content/{page_id}", f"dry-run/{page_id}")):
        raise ValueError("Dry-run page ID already exists")
    anchors = read(anchor_manifest)
    approved = read(english_source_package)
    window = approved.get("source", {}).get("approvedWindow", {})
    review = approved.get("review", {})
    if (approved.get("status") != "ready_for_translation"
            or review.get("humanApproval") is not True
            or window.get("humanApproval") is not True
            or window.get("startSeconds", 1e9) > START
            or window.get("endSeconds", -1) < END
            or approved.get("anchors", {}).get("artifact", {}).get("sha256") != sha(anchor_manifest)
            or not set(UNIT_IDS).issubset(set(review.get("reviewedSourceUnitIds", [])))):
        raise ValueError("Parent English source approval does not bind the selected units")
    original_catalog = read(reference_public / "multilingual-v3.json")
    original_page = next(p for p in original_catalog["pages"] if p["id"] == SOURCE_PAGE)
    weekly.validate_page(reference_public, original_page)
    if original_page["sourceMediaSha256"] != approved["source"]["media"]["sha256"]:
        raise ValueError("Approved English source differs from published parent page")
    if original_page["videoDelivery"]["sha256"] != parent_sha:
        raise ValueError("Parent video differs from published parent page")
    units = [unit for unit in anchors["sourceUnits"] if unit["sourceUnitId"] in UNIT_IDS]
    if [unit["sourceUnitId"] for unit in units] != list(UNIT_IDS):
        raise ValueError("Approved parent anchor range differs")
    if abs(units[0]["start"] - START) > 0.02 or abs(units[-1]["end"] - END) > 0.02:
        raise ValueError("Source window does not follow anchor boundaries")
    for unit in units:
        if unit["start"] < START - 0.02 or unit["end"] > END + 0.02:
            raise ValueError("Source unit outside clip")
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        events: list[dict] = []
        private = temp / "simulation"
        private.mkdir()
        clip = private / "intake-clip.mp4"
        began = begin()
        clip_sha = fetch_clip(source_url, clip, expected_clip_sha)
        began_proof = begin()
        prove_clip_from_parent(parent_video, private / "reproduced-cut.mp4", clip_sha)
        finish(events, "intake.parent_cut_proof", began_proof, clipSha256=clip_sha)
        source_audio = private / "source-audio.mp3"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(clip),
                        "-vn", "-ac", "1", "-ar", "24000", "-c:a", "libmp3lame",
                        "-b:a", "64k", "-y", str(source_audio)], check=True)
        source_audio_sha = sha(source_audio)
        intake = {"schemaVersion": "sermon-dev-simulated-intake-v1", "status": "simulation_only",
                  "sourceUrl": source_url, "clipSha256": clip_sha, "parentVideoSha256": parent_sha,
                  "parentEnglishSourcePackageSha256": sha(english_source_package),
                  "parentWindowSeconds": [START, END], "clipDurationSeconds": duration(clip)}
        intake_sha = write(private / "intake.json", intake)
        finish(events, "intake", began, bytes=clip.stat().st_size)
        began = begin()
        l1_units = []
        for unit in units:
            segment_began = begin()
            l1_units.append({"sourceUnitId": unit["sourceUnitId"], "english": unit["english"],
                             "start": round(unit["start"] - START, 5),
                             "end": round(unit["end"] - START, 5)})
            finish(events, "layer1.unit", segment_began, unitId=unit["sourceUnitId"])
        layer1 = {"schemaVersion": "sermon-dev-simulated-layer1-v1", "status": "simulation_only",
                  "inputIntakeSha256": intake_sha, "parentAnchorManifestSha256": sha(anchor_manifest),
                  "clipVideoSha256": clip_sha, "sourceAudioSha256": source_audio_sha,
                  "units": l1_units}
        l1_sha = write(private / "layer1.json", layer1)
        finish(events, "layer1", began, unitCount=len(l1_units))
        storage_url = (f"https://storage.googleapis.com/{DEV_BUCKET}/weekly/"
                       f"{page_id}/{clip_sha}.mp4")
        canonical = f"/pages/{page_id}/full-video-browser.mp4"
        delivery = {"schemaVersion": "sermon-video-delivery-v1", "canonicalUrl": canonical,
                    "storageUrl": storage_url, "sha256": clip_sha, "bytes": clip.stat().st_size}
        weekly.validate_video_delivery(page_id, delivery, clip_sha)
        stage = temp / "stage-public"
        stage.mkdir()
        english_by_id = {unit["sourceUnitId"]: unit["english"] for unit in l1_units}
        release_refs = {}
        alignment = {}
        l2_shas, l3_shas = {}, {}
        for locale in LOCALES:
            l2_began = begin()
            source_content = reference_public / f"content/{SOURCE_PAGE}/{locale}.json"
            source_captions = reference_public / f"captions/{SOURCE_PAGE}/{locale}.json"
            source_track = reference_public / f"media/{SOURCE_PAGE}/{locale}.mp3"
            content = read(source_content)
            selected = []
            for cue in content["cues"]:
                if any(unit in UNIT_IDS for unit in cue["sourceUnitIds"]):
                    segment_began = begin()
                    selected.append(rebase(cue))
                    finish(events, "layer2.unit", segment_began, locale=locale,
                           unitId=cue["sourceUnitIds"][0])
            if len(selected) != len(UNIT_IDS) or [c["sourceUnitIds"][0] for c in selected] != list(UNIT_IDS):
                raise ValueError(f"{locale}: text slice does not match English units")
            layer2 = {"schemaVersion": "sermon-dev-simulated-layer2-v1", "status": "simulation_only",
                      "targetLocale": locale, "inputLayer1Sha256": l1_sha,
                      "parentApprovedContentSha256": sha(source_content), "cues": selected,
                      "method": "slice_parent_reviewed_text_without_new_approval"}
            l2_shas[locale] = write(private / f"layer2/{locale}.json", layer2)
            finish(events, "layer2", l2_began, locale=locale, unitCount=len(selected))
            l3_began = begin()
            caption_cues = []
            selected_groups = {cue["textGroupId"] for cue in selected}
            for cue in read(source_captions)["cues"]:
                if cue["textGroupId"] in selected_groups:
                    segment_began = begin()
                    caption_cues.append(rebase(cue))
                    finish(events, "layer3.cue", segment_began, locale=locale,
                           textGroupId=cue["textGroupId"])
            if [cue["textGroupId"] for cue in caption_cues] != [cue["textGroupId"] for cue in selected]:
                raise ValueError(f"{locale}: dubbing subtitle slice incomplete")
            track_path = stage / f"media/{page_id}/{locale}.mp3"
            track_sha = clip_audio(source_track, track_path)
            layer3 = {"schemaVersion": "sermon-dev-simulated-layer3-v1", "status": "simulation_only",
                      "targetLocale": locale, "inputLayer2Sha256": l2_shas[locale],
                      "parentTrackSha256": sha(source_track), "clipTrackSha256": track_sha,
                      "durationSeconds": duration(track_path), "cues": caption_cues,
                      "method": "cut_parent_dub_without_new_listening_review"}
            l3_shas[locale] = write(private / f"layer3/{locale}.json", layer3)
            finish(events, "layer3", l3_began, locale=locale,
                   cueCount=len(caption_cues), audioBytes=track_path.stat().st_size)
            l4_began = begin()
            out_content = {"schemaVersion": "sermon-dev-simulated-content-v1",
                           "status": "simulation_only", "pageId": page_id,
                           "targetLocale": locale, "series": content["series"],
                           "title": content["title"], "speaker": content["speaker"],
                           "durationSeconds": DURATION, "sourceVideoUrl": canonical,
                           "browserVideoSha256": clip_sha, "cues": selected,
                           "inputLayer2Sha256": l2_shas[locale]}
            content_path = f"content/{page_id}/{locale}.json"
            captions_path = f"captions/{page_id}/{locale}.json"
            content_sha = write(stage / content_path, out_content)
            captions_sha = write(stage / captions_path,
                                 {"schemaVersion": "sermon-dev-simulated-captions-v1",
                                  "status": "simulation_only", "pageId": page_id,
                                  "targetLocale": locale, "cues": caption_cues,
                                  "inputLayer3Sha256": l3_shas[locale]})
            blocks = [{"start": cue["start"], "text": cue["text"],
                       "english": english_by_id[cue["sourceUnitIds"][0]]} for cue in selected]
            page_path = f"pages/{page_id}/{locale}/index.html"
            (stage / page_path).parent.mkdir(parents=True, exist_ok=True)
            (stage / page_path).write_text(page_html(locale, page_id, blocks, canonical),
                                          encoding="utf-8")
            page_sha = sha(stage / page_path)
            # The index is a time-rebased slice of the parent test data. It is
            # a structural sidecar, not a newly verified venue locator.
            old_binding = original_page["targets"][locale]["audioFingerprint"]
            parent_index = read(reference_public / old_binding["indexUrl"].lstrip("/"))
            offset = round(START * parent_index["sampleRate"] / parent_index["hopSize"])
            limit = round(END * parent_index["sampleRate"] / parent_index["hopSize"])
            postings = {key: [n - offset for n in times if offset <= n < limit]
                        for key, times in parent_index["postings"].items()}
            postings = {key: times for key, times in postings.items() if times}
            index = {key: parent_index[key] for key in (
                "schemaVersion", "algorithmVersion", "sampleRate", "hopSize", "fftSize")}
            index.update({"simulationOnly": True, "pageId": page_id,
                          "sourceSha256": source_audio_sha, "trackSha256": track_sha,
                          "sourceStartSeconds": 0, "sourceEndSeconds": DURATION,
                          "window": {"startSeconds": 0, "endSeconds": DURATION},
                          "durationSeconds": DURATION, "postings": postings,
                          "landmarkCount": sum(map(len, postings.values())),
                          "derivedFromParentIndexSha256": sha(reference_public / old_binding["indexUrl"].lstrip("/"))})
            scratch = private / f"{locale}-landmarks.json"
            index_sha = write(scratch, index)
            index_path = f"fingerprints/{index_sha[:16]}-landmarks.json"
            index_target = stage / index_path
            index_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(scratch, index_target)
            release = {"schemaVersion": "sermon-dev-simulated-release-v1",
                       "status": "simulation_only", "pageId": page_id,
                       "targetLocale": locale, "inputLayer1Sha256": l1_sha,
                       "inputLayer2Sha256": l2_shas[locale],
                       "inputLayer3Sha256": l3_shas[locale],
                       "assets": {"page": page_sha, "content": content_sha,
                                  "captions": captions_sha, "audio": track_sha,
                                  "fingerprint": index_sha}}
            release_path = f"releases-v2/{page_id}/{locale}.json"
            release_sha = write(stage / release_path, release)
            release_refs[locale] = {"path": "/" + release_path, "sha256": release_sha}
            alignment[locale] = [{"sourceUnitId": cue["sourceUnitIds"][0],
                                  "textStart": cue["start"],
                                  "dubStart": caption_cues[i]["start"]}
                                 for i, cue in enumerate(selected)]
            finish(events, "layer4.locale_assets", l4_began, locale=locale, assetCount=6)
        l4_began = begin()
        write(stage / f"english-reference/{page_id}.json",
              {"schemaVersion": "sermon-dev-simulated-english-reference-v1",
               "status": "simulation_only", "pageId": page_id,
               "inputLayer1Sha256": l1_sha, "units": l1_units})
        write(stage / f"alignment/{page_id}.json",
              {"schemaVersion": "sermon-dev-simulated-alignment-v1",
               "status": "simulation_only", "pageId": page_id,
               "targets": alignment})
        stage_files = weekly.regular_files(stage)
        if len(stage_files) != 20:
            raise ValueError(f"Bucket profile requires 20 staged Hosting assets, got {len(stage_files)}")
        stage_manifest = {"schemaVersion": "sermon-dev-simulated-stage-manifest-v1",
                          "status": "simulation_only", "profile": weekly.BUCKET_PROFILE,
                          "pageId": page_id, "videoDelivery": delivery,
                          "files": [{"path": "/" + name, "sha256": sha(path)}
                                    for name, path in sorted(stage_files.items())]}
        write(private / "stage-manifest.json", stage_manifest)
        # Run the same file-count and URL schema shape as the formal bucket profile,
        # while keeping the saved manifest explicitly simulated.
        shape = {k: v for k, v in stage_manifest.items() if k not in {"status"}}
        shape["schemaVersion"] = weekly.BUCKET_STAGE_SCHEMA
        weekly.validate_schema(shape, f"{weekly.BUCKET_STAGE_SCHEMA}.schema.json")
        preview_catalog = {"schemaVersion": "sermon-dev-simulated-catalog-v1",
                           "status": "simulation_only", "pageId": page_id,
                           "sourcePageId": SOURCE_PAGE, "videoDelivery": delivery,
                           "targetLocales": list(LOCALES), "releases": release_refs,
                           "inputLayer1Sha256": l1_sha, "layer2Sha256": l2_shas,
                           "layer3Sha256": l3_shas}
        preview_catalog_path = f"dry-run/{page_id}/catalog.json"
        preview_sha = write(stage / preview_catalog_path, preview_catalog)
        write(stage / "dry-run/latest.json", {
            "schemaVersion": "sermon-dev-simulated-app-index-v1", "status": "simulation_only",
            "pageId": page_id, "catalogUrl": "/" + preview_catalog_path,
            "catalogSha256": preview_sha,
        })
        candidate = temp / "hosting"
        shutil.copytree(base_dev / "public", candidate / "public", copy_function=clone)
        for name, path in weekly.regular_files(stage).items():
            target = candidate / "public" / name
            if target.exists():
                if name != "dry-run/latest.json" or read(target).get("status") != "simulation_only":
                    raise ValueError(f"Dev snapshot would overwrite {name}")
                target.unlink()  # copytree uses hardlinks; preserve the input snapshot
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        config = weekly.add_video_redirect(config, delivery)
        write(candidate / "firebase.json", config)
        expected = weekly.regular_files(base_dev / "public")
        actual = weekly.regular_files(candidate / "public")
        if set(actual) - set(expected) != set(weekly.regular_files(stage)) - {"dry-run/latest.json"}:
            raise ValueError("Dev candidate file set differs from staged dry run")
        if any(sha(actual[name]) != sha(path) for name, path in expected.items()
               if name != "dry-run/latest.json"):
            raise ValueError("Dev candidate changed an existing App file")
        if "published-weeks-base.mjs" not in expected or "dry-run-app-weeks.mjs" not in expected:
            raise ValueError("Dev App does not have the simulated-week adapter")
        finish(events, "layer4.catalog_and_candidate", l4_began,
               hostingAssetCount=20, previewCatalogCount=1, appIndexCount=1,
               bucketObjectCount=1)
        timing_sha = write(private / "timing-log.json", {
            "schemaVersion": "sermon-dev-four-layer-timing-log-v1", "status": "simulation_only",
            "pageId": page_id, "events": events})
        report = {"schemaVersion": "sermon-dev-four-layer-bucket-dry-run-v2",
                  "status": "validated_not_deployed", "simulationOnly": True,
                  "pageId": page_id, "origin": DEV_ORIGIN,
                  "clipSourceSha256": clip_sha, "parentVideoSha256": parent_sha,
                  "parentWindowSeconds": [START, END],
                  "intakeSha256": intake_sha, "layer1Sha256": l1_sha,
                  "layer2Sha256": l2_shas, "layer3Sha256": l3_shas,
                  "stageManifestSha256": sha(private / "stage-manifest.json"),
                  "timingLogSha256": timing_sha, "timedEventCount": len(events),
                  "hostingAssetCount": 20, "catalogUpdateFileCount": 1,
                  "weeklyHostingFileCount": 21, "bucketObjectCount": 1,
                  "weeklyFirebaseObjectCount": 22,
                  "devAppIndexUpdateFileCount": 1, "devHostingChangedFileCount": 22,
                  "devFirebaseChangedObjectCount": 23,
                  "appUrl": f"{DEV_ORIGIN}/?week={page_id}",
                  "baseDevCatalogSha256": sha(base_dev / "public/multilingual-v3.json"),
                  "baselinePreflightSha256": sha(baseline_preflight),
                  "baseDevAppSha256": sha(base_dev / "public/app.mjs"),
                  "baseDevPageStyleSha256": sha(base_dev / f"public/pages/{SOURCE_PAGE}/style.css"),
                  "videoDelivery": delivery,
                  "testPageUrls": {locale: f"{DEV_ORIGIN}/pages/{page_id}/{locale}/index.html"
                                   for locale in LOCALES},
                  "formalCatalogUpdated": False,
                  "modelCalls": 0, "humanApprovalsCreated": 0,
                  "createdAt": datetime.now(timezone.utc).isoformat()}
        write(temp / "dry-run-report.json", report)
        temp.rename(out)
        return report
    except BaseException:
        shutil.rmtree(temp)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--expected-clip-sha256", required=True)
    parser.add_argument("--parent-video", type=Path, required=True)
    parser.add_argument("--parent-sha256", required=True)
    parser.add_argument("--anchor-manifest", type=Path, required=True)
    parser.add_argument("--english-source-package", type=Path, required=True)
    parser.add_argument("--reference-public", type=Path, required=True)
    parser.add_argument("--base-dev", type=Path, required=True)
    parser.add_argument("--baseline-preflight", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build(source_url=args.source_url, expected_clip_sha=args.expected_clip_sha256,
                   parent_video=args.parent_video, parent_sha=args.parent_sha256,
                   anchor_manifest=args.anchor_manifest,
                   english_source_package=args.english_source_package,
                   reference_public=args.reference_public,
                   baseline_preflight=args.baseline_preflight,
                   base_dev=args.base_dev, page_id=args.page_id, out=args.out)
    print(json.dumps({k: result[k] for k in ("status", "pageId", "hostingAssetCount",
                                                "weeklyHostingFileCount", "bucketObjectCount")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
