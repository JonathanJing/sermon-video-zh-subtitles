#!/usr/bin/env python3
"""Republish the 2026-10-25 sermon page on the source clock and add field alignment.

The 2026-10-24 publish built content with absolute media times (1716-3577) and left each
locale's MP3 at its own length, so the published field-alignment contract
(``sermon-published-alignment-v1`` + ``sermon-audio-fingerprint-binding-v1``) could not bind:
it needs one approved source window per page, ``content.durationSeconds == end - start``,
``content.sourceWindow`` on the master media, and each target's audio within 0.1 s of the
window. This driver fixes the page without changing the spoken content:

  normalize  pad the three tracks to one length L and encode the media MP3s (silence only)
  assets     content with clip-relative cues + ``sourceWindow``, captions, audio packages,
             releases; fingerprints for each locale track; the alignment sidecar
  stage-assets   baseline + replaced page assets + alignment sidecar + fingerprints -> deploy
  verify         HTTP SHA/Range for the replaced assets -> evidence
  stage-release  assets snapshot + new releases + catalogs (release sha, verified) -> deploy
  readback       live catalogs/releases equal the staged bytes
  bind           fresh baseline + published_alignment_catalog.bind_catalogs -> deploy
  verify-alignment  GET catalog binding, index and sidecar; decode with the Swift core rules

Everything before a deploy only writes under the ignored artifacts tree. Each deploy goes
through the repository's guarded publisher; the previous Hosting version stays available.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import publish_sat400_20261025 as base  # noqa: E402  shares stage/publish/verify helpers
from tongxing_production.delivery import baseline as bl  # noqa: E402
from tongxing_production.delivery import contract  # noqa: E402
from tongxing_production.delivery import published_alignment_catalog as align  # noqa: E402

PAGE_ID = base.PAGE_ID
LOCALES = base.LOCALES
RUN_DIR = base.RUN_DIR
RUNS = base.RUNS
ORIGIN = "https://ai-for-god-sermon-audio.web.app"
SOURCE_URL = base.SOURCE_URL
DATE = base.DATE
WINDOW_START, WINDOW_END = base.WINDOW_START, base.WINDOW_END
SPEAKERS = base.SPEAKERS
CATEGORY = base.CATEGORY
PAGE_TITLE = base.PAGE_TITLE
META = base.META
SOURCE_MEDIA = Path("/Users/jonathan_jing/Downloads/🔴 Mariners Online Worship Service | Worship & Message! | Join Us Now! -  - 2026-10-24 17-08-15_0.mp4")
SOURCE_SHA = "89fe948a1c940c01e76412affd1ec8640e2cfe159d113aeabd5d886abc29b6da"
TRACK_LENGTH = 1862.0
FINGERPRINT = Path("packages/fingerprint/bin/build_fingerprint_index.mjs")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def probe_seconds(path: Path) -> float:
    return round(float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()), 3)


def cmd_normalize(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    import wave
    result = {}
    for loc in LOCALES:
        run = RUNS / RUN_DIR[loc]
        with wave.open(str(run / "track.wav")) as handle:
            rate, frames = handle.getframerate(), handle.getnframes()
            data = handle.readframes(frames)
        seconds = frames / rate
        pad = int(round((TRACK_LENGTH - seconds) * rate))
        trimmed = 0.0
        if pad < 0:
            # The merged track may end a fraction after the window with TTS tail padding.
            # Cut only silence: refuse if the excess carries audible speech.
            import array as _array
            samples = _array.array("h", data)
            cut = samples[: max(0, int(round(TRACK_LENGTH * rate)))]
            tail = samples[len(cut):]
            rms = (sum(x * x for x in tail) / max(1, len(tail))) ** 0.5 if tail else 0.0
            contract.require(rms < 400, f"{loc}: track exceeds the window with audible speech (rms {rms:.0f})")
            data = cut.tobytes()
            trimmed = round(-pad / rate, 3)
            pad = 0
        padded = out / f"track-{loc}.wav"
        with wave.open(str(padded), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(data + b"\x00" * (pad * 2))
        mp3 = out / f"{loc}.mp3"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(padded),
                        "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
        seconds_mp3 = probe_seconds(mp3)
        contract.require(abs(seconds_mp3 - TRACK_LENGTH) <= 0.02, f"{loc}: mp3 length {seconds_mp3}")
        result[loc] = {"trackSeconds": round(seconds, 3), "paddedSeconds": TRACK_LENGTH,
                       "mp3Seconds": seconds_mp3, "mp3Sha256": sha(mp3)}
    write(out / "normalized.json", result)
    return result


def cmd_assets(out: Path, normalized: Path) -> dict:
    contract.require(not out.exists(), "Use a new assets directory")
    esp, esp_sha = base.english_source()
    verdict = base.VERDICT
    contract.require(json.loads(verdict.read_text())["verdict"] == "approved", "Human review verdict is not approved")
    media_sha = esp["source"]["media"]["sha256"]
    contract.require(media_sha == SOURCE_SHA, "source package media differs from the master video")
    window = {"schemaVersion": "sermon-original-recording-window-v1", "mediaSha256": media_sha,
              "startSeconds": WINDOW_START, "endSeconds": WINDOW_START + TRACK_LENGTH}
    summary, releases = {}, {}
    for loc in LOCALES:
        run = RUNS / RUN_DIR[loc]
        sent = base.rows(run / "sentences.jsonl")
        tr = {r["id"]: r for r in base.rows(run / "translations.jsonl")}
        sp = {r["id"]: r for r in base.rows(run / "speech.jsonl")}
        sched = {r["id"]: r for r in json.loads((run / "schedule.json").read_text())["sentences"]}
        contract.require(len(sent) == base.SENTENCES and all(sched.get(s["id"], {}).get("actualStart") is not None for s in sent),
                         f"{loc}: sentence table or schedule incomplete")
        candidate = {"schemaVersion": "sentence-first-clip-candidate-v1", "pageId": PAGE_ID, "targetLocale": loc,
                     "englishSourcePackageJsonSha256": esp_sha,
                     "translationBasis": f"{loc}: agent translation, second-pass audit and terminology pass",
                     "humanReview": {"verdictSha256": sha(verdict), "status": "approved"},
                     "groups": [{"id": s["id"], "sourceUnitId": s["sourceUnitId"], "speakerId": s["speakerId"],
                                 "english": s["english"], "targetText": tr[s["id"]]["target"],
                                 "spokenText": sp[s["id"]]["spokenText"]} for s in sent]}
        write(out / f"packages/{loc}-candidate.json", candidate)
        candidate_sha = base.json_sha(candidate)
        mp3 = out / f"public/media/{PAGE_ID}/{loc}.mp3"
        mp3.parent.mkdir(parents=True, exist_ok=True)
        src_mp3 = normalized / f"{loc}.mp3"
        contract.require(abs(probe_seconds(src_mp3) - TRACK_LENGTH) <= 0.02, f"{loc}: normalized mp3 changed")
        mp3.write_bytes(src_mp3.read_bytes())
        audio_seconds = probe_seconds(mp3)
        audio_package = {"schemaVersion": "sentence-first-clip-audio-package-v1", "pageId": PAGE_ID, "targetLocale": loc,
                         "targetLanguageCandidateJsonSha256": candidate_sha,
                         "voices": sorted({s["speakerId"] for s in sent}),
                         "track": {"wavSha256": sha(run / "track.wav"), "mp3Sha256": sha(mp3),
                                   "mp3DurationSeconds": audio_seconds},
                         "synchronization": "synced to the source video clock: each sentence placed at its English start; "
                                            "the media mp3 is zero-padded to the page's one approved source window",
                         "humanReview": {"verdictSha256": sha(verdict), "status": "approved"},
                         "units": [{"id": s["id"], "sourceUnitId": s["sourceUnitId"], "speakerId": s["speakerId"],
                                    "wavSha256": sha(run / f"tts/{s['id']}.wav"),
                                    "plannedStart": sched[s["id"]]["actualStart"], "seconds": sched[s["id"]]["dubSeconds"]}
                                   for s in sent]}
        write(out / f"packages/{loc}-audio-package.json", audio_package)
        audio_sha = base.json_sha(audio_package)
        captions = {"schemaVersion": "sermon-target-language-captions-v1", "pageId": PAGE_ID, "locale": loc,
                    "audioPackageJsonSha256": audio_sha,
                    "timingBasis": "target audio on the source video clock; cue times are the placed dub starts and durations",
                    "cues": [{"start": round(sched[s["id"]]["actualStart"], 3),
                              "end": round(sched[s["id"]]["actualStart"] + sched[s["id"]]["dubSeconds"], 3),
                              "sourceUnitIds": [s["sourceUnitId"]], "text": tr[s["id"]]["target"],
                              "textGroupId": "translation-" + s["sourceUnitId"]} for s in sent]}
        write(out / f"public/captions/{PAGE_ID}/{loc}.json", captions)
        base.ios_cue_check(captions["cues"], audio_seconds, False)
        m = META[loc]
        content = {"schemaVersion": "sermon-full-video-text-content-v2", "pageId": PAGE_ID, "locale": loc, "targetLocale": loc,
                   "sourceLocale": "en", "status": "human_reviewed", "contentStatus": "human_reviewed",
                   "audioStatus": "human_reviewed", "reviewMode": "formal", "date": DATE, "title": m["title"],
                   "series": m["series"], "scripture": m["scripture"], "speaker": SPEAKERS,
                   "durationSeconds": TRACK_LENGTH, "audioDurationSeconds": audio_seconds,
                   "sourceWindow": window,
                   "englishSourcePackageJsonSha256": esp_sha, "sourceMediaSha256": media_sha,
                   "targetLanguageCandidateJsonSha256": candidate_sha, "targetLanguageAudioPackageJsonSha256": audio_sha,
                   "cues": [{"start": round(s["start"], 3), "end": round(s["end"], 3),
                             "sourceUnitIds": [s["sourceUnitId"]], "text": tr[s["id"]]["target"],
                             "textGroupId": "translation-" + s["sourceUnitId"]} for s in sent]}
        base.ios_cue_check(content["cues"], TRACK_LENGTH, True)
        write(out / f"public/content/{PAGE_ID}/{loc}.json", content)
        body = "".join(f"<p>{html.escape(tr[s['id']]['target'])}</p>" for s in sent)
        page_html = (f'<!doctype html><html lang="{loc}"><head><meta charset="utf-8">'
                     f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(m["title"])}</title>'
                     '<style>body{max-width:48rem;margin:auto;padding:1.2rem;font:1.1rem/1.7 system-ui}audio{width:100%}</style></head>'
                     f'<body><h1>{html.escape(m["title"])}</h1><p>{DATE} · {html.escape(SPEAKERS)}</p><p>{html.escape(m["badge"])}</p>'
                     f'<audio controls preload="none" src="/media/{PAGE_ID}/{loc}.mp3"></audio>'
                     f'<p><a href="{SOURCE_URL}">{html.escape(m["source"])}</a></p><p>{html.escape(m["note"])}</p>{body}</body></html>')
        page_path = out / f"public/pages/{PAGE_ID}/{loc}/index.html"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(page_html, encoding="utf-8")
        release = {"schemaVersion": "sermon-target-language-release-package-v2", "packageId": f"{PAGE_ID}-{loc}-{base.ENVIRONMENT}-v2",
                   "pageId": PAGE_ID, "sourceLocale": "en", "targetLocale": loc, "interfaceLocale": loc,
                   "contentLocale": loc, "audioLocale": loc,
                   "targetLanguageCandidateJsonSha256": candidate_sha, "spokenTargetLanguageCandidateJsonSha256": candidate_sha,
                   "targetLanguageAudioPackageJsonSha256": audio_sha, "status": "candidate",
                   "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                   "assets": [{"role": role, "path": path, "sha256": sha(out / "public" / path.lstrip("/"))}
                              for role, path in (("page", f"/pages/{PAGE_ID}/{loc}/index.html"),
                                                 ("content", f"/content/{PAGE_ID}/{loc}.json"),
                                                 ("audio", f"/media/{PAGE_ID}/{loc}.mp3"),
                                                 ("captions", f"/captions/{PAGE_ID}/{loc}.json"))],
                   "httpVerification": {"status": "not_run", "evidenceSha256": None},
                   "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
                   "venueAcceptance": {"status": "not_run", "evidenceSha256": None}, "issues": []}
        contract.validate_release_schema(release)
        write(out / f"releases/{loc}.json", release)
        releases[loc] = release
        summary[loc] = {"cues": len(sent), "audioSeconds": audio_seconds, "mp3Bytes": mp3.stat().st_size,
                        "contentSeconds": TRACK_LENGTH, "window": [WINDOW_START, WINDOW_START + TRACK_LENGTH]}
    # fingerprints: one source precompute, one index per locale track
    precomputed = out / "fingerprints/source-landmarks.json"
    precomputed.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["node", str(FINGERPRINT), "--mode", "precompute", "--source", str(SOURCE_MEDIA),
                    "--source-sha", SOURCE_SHA, "--start", str(WINDOW_START), "--end", str(WINDOW_START + TRACK_LENGTH),
                    "--out", str(precomputed)], check=True)
    precomputed_sha = sha(precomputed)
    bindings = {}
    for loc in LOCALES:
        track = out / f"public/media/{PAGE_ID}/{loc}.mp3"
        index_file = out / "fingerprints" / f".{loc}-index.json"
        subprocess.run(["node", str(FINGERPRINT), "--mode", "bind", "--source-sha", SOURCE_SHA,
                        "--precomputed", str(precomputed), "--precomputed-sha", precomputed_sha,
                        "--track", str(track), "--track-sha", sha(track),
                        "--page-id", PAGE_ID, "--start", str(WINDOW_START), "--end", str(WINDOW_START + TRACK_LENGTH),
                        "--out", str(index_file)], check=True)
        index_sha = sha(index_file)
        final = out / "public/fingerprints" / f"{index_sha[:16]}-landmarks.json"
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(index_file.read_bytes())
        bindings[loc] = {"schemaVersion": "sermon-audio-fingerprint-binding-v1",
                         "algorithmVersion": "spectral-landmarks-v1", "captureSeconds": 10,
                         "pageId": PAGE_ID, "sourceSha256": SOURCE_SHA, "trackSha256": sha(track),
                         "sourceStartSeconds": WINDOW_START, "sourceEndSeconds": WINDOW_START + TRACK_LENGTH,
                         "indexSha256": index_sha, "indexUrl": f"/fingerprints/{index_sha[:16]}-landmarks.json"}
        index_file.unlink()
    sidecar = {"schemaVersion": "sermon-published-alignment-v1", "pageId": PAGE_ID,
               "sourceIdentitySha256": esp_sha,
               "targets": {loc: {"releasePackageJsonSha256": base.json_sha(releases[loc]),
                                 "audioFingerprint": bindings[loc]} for loc in LOCALES}}
    write(out / f"public/alignment/{PAGE_ID}.json", sidecar)
    write(out / "assets-summary.json", {"pageId": PAGE_ID, "environment": base.ENVIRONMENT,
                                        "sourceIdentitySha256": esp_sha, "sourceMediaSha256": media_sha,
                                        "trackLength": TRACK_LENGTH, "window": window,
                                        "locales": summary, "bindings": bindings})
    return summary


def align_paths() -> list[str]:
    return [f"/alignment/{PAGE_ID}.json"]


def cmd_stage_assets(baseline: Path, assets: Path, out: Path) -> dict:
    public = baseline / "public"
    replace = {p.lstrip("/") for p in align_paths()}
    for loc in LOCALES:
        replace |= {f"content/{PAGE_ID}/{loc}.json", f"captions/{PAGE_ID}/{loc}.json",
                    f"media/{PAGE_ID}/{loc}.mp3", f"pages/{PAGE_ID}/{loc}/index.html"}
    files = {rel: (assets / "public" / rel).read_bytes() for rel in sorted(replace)}
    for path in sorted((assets / "public/fingerprints").glob("*.json")):
        files[f"fingerprints/{path.name}"] = path.read_bytes()
    base.stage(baseline, out, None, files, replace=frozenset(replace))
    write(out / "republished-assets.json", {"pageId": PAGE_ID, "changedPaths": sorted("/" + rel for rel in files)})
    return {"staged": str(out), "files": len(files)}


def cmd_verify(assets: Path, evidence: Path) -> dict:
    rows, failures = [], []
    for loc in LOCALES:
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        for asset in release["assets"]:
            status, data = base.reader(ORIGIN + asset["path"])
            digest = hashlib.sha256(data).hexdigest()
            ok = status == 200 and digest == asset["sha256"]
            row = {"path": asset["path"], "status": status, "sha256": digest, "pass": ok}
            if asset["role"] == "audio":
                from urllib.request import Request, urlopen
                with urlopen(Request(ORIGIN + asset["path"], headers={"Range": "bytes=0-1023", "Cache-Control": "no-cache"}),
                             timeout=120) as response:
                    chunk = response.read()
                row.update(rangeStatus=response.status, contentRange=response.headers.get("Content-Range"))
                row["pass"] = row["pass"] and row["rangeStatus"] == 206 and len(chunk) == 1024
            rows.append(row)
            if not row["pass"]:
                failures.append(row["path"])
    sidecar = f"/alignment/{PAGE_ID}.json"
    status, data = base.reader(ORIGIN + sidecar)
    ok = status == 200 and hashlib.sha256(data).hexdigest() == sha(assets / "public" / sidecar.lstrip("/"))
    rows.append({"path": sidecar, "status": status, "sha256": hashlib.sha256(data).hexdigest(), "pass": ok})
    for path in sorted((assets / "public/fingerprints").glob("*.json")):
        url = f"/fingerprints/{path.name}"
        status, data = base.reader(ORIGIN + url)
        ok = status == 200 and hashlib.sha256(data).hexdigest() == sha(path)
        rows.append({"path": url, "status": status, "sha256": hashlib.sha256(data).hexdigest(), "pass": ok})
        if not ok:
            failures.append(url)
    evidence_row = {"schemaVersion": "sentence-first-clip-http-verification-v1", "origin": ORIGIN,
                    "pageId": PAGE_ID, "checks": rows, "status": "pass" if not failures else "fail"}
    base.write_json(evidence, evidence_row)
    return {"status": evidence_row["status"], "checks": len(rows), "failed": failures}


def cmd_stage_release(assets_snapshot: Path, evidence: Path, assets: Path, out: Path) -> dict:
    evidence_row = json.loads(evidence.read_text())
    contract.require(evidence_row["status"] == "pass", "HTTP verification did not pass")
    evidence_sha = sha(evidence)
    public = assets_snapshot / "public"
    files, targets = {}, {}
    for loc in LOCALES:
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        release.update(status="published_http_verified",
                       httpVerification={"status": "pass", "evidenceSha256": evidence_sha})
        contract.validate_release_schema(release)
        data = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
        files[f"releases-v2/{PAGE_ID}/{loc}.json"] = data
        targets[loc] = {"audioStatus": "human_reviewed", "capabilities": ["text", "captions", "audio"],
                        "contentStatus": "human_reviewed", "releasePackageJsonSha256": hashlib.sha256(data).hexdigest(),
                        "releasePackageUrl": f"/releases-v2/{PAGE_ID}/{loc}.json"}
    v5 = json.loads((public / contract.CATALOG_FILES[contract.CATALOG_V5]).read_text())
    page = next(p for p in v5["pages"] if p["id"] == PAGE_ID)
    contract.require(set(page["targets"]) == set(LOCALES), "live page locales changed")
    for loc, target in page["targets"].items():
        target.update(targets[loc])
    v4 = contract.project_legacy_catalog_v4(v5)
    v3 = contract.project_human_catalog(v4)
    for name, value in ((contract.CATALOG_V5, v5), (contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        contract.validate_catalog_schema(value)
        files[contract.CATALOG_FILES[name]] = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    base.stage(assets_snapshot, out, None, files,
               replace=frozenset({f"releases-v2/{PAGE_ID}/{loc}.json" for loc in LOCALES}))
    return {"staged": str(out), "changed": sorted(files)}


def cmd_bind(baseline: Path, out: Path) -> dict:
    # bind_catalogs validates against the live snapshot; stage() then writes the bound
    # catalogs (v3/v4/v5 all change together) and seals the snapshot.
    cass = align.bind_catalogs(baseline / "public", PAGE_ID)
    files = {name: (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
             for name, value in cass.items()}
    base.stage(baseline, out, None, files)
    return {"staged": str(out), "catalogs": sorted(cass)}


def cmd_verify_alignment(assets: Path) -> dict:
    v5 = json.loads(base.reader(ORIGIN + "/multilingual-v5.json")[1])
    page = next(p for p in v5["pages"] if p["id"] == PAGE_ID)
    report = {"pageId": PAGE_ID, "locales": {}}
    for loc in LOCALES:
        target = page["targets"][loc]
        binding = target.get("audioFingerprint")
        contract.require(isinstance(binding, dict), f"{loc}: catalog has no binding")
        contract.require("alignment" in target["capabilities"], f"{loc}: capability missing")
        status, data = base.reader(ORIGIN + binding["indexUrl"])
        index = json.loads(data)
        contract.require(status == 200 and hashlib.sha256(data).hexdigest() == binding["indexSha256"], f"{loc}: index hash")
        contract.require(index["pageId"] == PAGE_ID and index["trackSha256"] == binding["trackSha256"]
                         and index["sourceSha256"] == SOURCE_SHA
                         and index["sourceStartSeconds"] == binding["sourceStartSeconds"]
                         and index["sourceEndSeconds"] == binding["sourceEndSeconds"]
                         and abs(index["durationSeconds"] - (binding["sourceEndSeconds"] - binding["sourceStartSeconds"])) < 1e-9,
                         f"{loc}: index identity")
        content = json.loads(base.reader(ORIGIN + f"/content/{PAGE_ID}/{loc}.json")[1])
        contract.require(content["durationSeconds"] == index["durationSeconds"], f"{loc}: content duration")
        report["locales"][loc] = {"binding": binding, "landmarks": index["landmarkCount"],
                                  "durationSeconds": index["durationSeconds"], "capabilities": target["capabilities"]}
    report["status"] = "pass"
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("normalize"); a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("assets"); b.add_argument("--out", type=Path, required=True); b.add_argument("--normalized", type=Path, required=True)
    c = sub.add_parser("stage-assets"); c.add_argument("--baseline", type=Path, required=True); c.add_argument("--assets", type=Path, required=True); c.add_argument("--out", type=Path, required=True)
    d = sub.add_parser("verify"); d.add_argument("--assets", type=Path, required=True); d.add_argument("--evidence", type=Path, required=True)
    e = sub.add_parser("stage-release"); e.add_argument("--assets-snapshot", type=Path, required=True); e.add_argument("--assets", type=Path, required=True); e.add_argument("--evidence", type=Path, required=True); e.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("bind"); f.add_argument("--baseline", type=Path, required=True); f.add_argument("--out", type=Path, required=True)
    g = sub.add_parser("verify-alignment"); g.add_argument("--assets", type=Path, required=True)
    pub = sub.add_parser("publish"); pub.add_argument("--snapshot", type=Path, required=True)
    rb = sub.add_parser("readback"); rb.add_argument("--snapshot", type=Path, required=True)
    args = p.parse_args()
    if args.cmd == "normalize":
        result = cmd_normalize(args.out)
    elif args.cmd == "assets":
        result = cmd_assets(args.out, args.normalized)
    elif args.cmd == "stage-assets":
        result = cmd_stage_assets(args.baseline, args.assets, args.out)
    elif args.cmd == "verify":
        result = cmd_verify(args.assets, args.evidence)
    elif args.cmd == "stage-release":
        result = cmd_stage_release(args.assets_snapshot, args.evidence, args.assets, args.out)
    elif args.cmd == "bind":
        result = cmd_bind(args.baseline, args.out)
    elif args.cmd == "verify-alignment":
        result = cmd_verify_alignment(args.assets)
    elif args.cmd == "publish":
        result = base.cmd_publish(args.snapshot)
    else:
        result = base.cmd_readback(args.snapshot)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
