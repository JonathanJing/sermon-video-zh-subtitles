#!/usr/bin/env python3
"""Build a minimal, explicit Firebase upload directory from verified local artifacts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from poc import ROOT, sha256, write_json
from server import load_library

HERE = Path(__file__).resolve().parent
DEFAULT_COMPARISON = ROOT / "artifacts/sermon-dubbing/2026-09-05-authorized-voice-poc/listening-comparison"
DEFAULT_OUT = ROOT / "artifacts/sermon-dubbing/2026-09-05-weekly-app-v3"
WEEKS = [
    {"date": "2026-08-30", "sourceId": "-BeFX5G2oAw", "title": "当我愤怒时", "scripture": "诗篇 137 篇", "number": "137", "speaker": "Eric Geiger · 埃里克", "speakerSource": "https://www.marinerschurch.org/message/when-i-am-angered/"},
    {"date": "2026-08-23", "sourceId": "ZDQwL3K-A44", "title": "当我遭遇背叛", "scripture": "诗篇 55 篇", "number": "55", "speaker": "Eric Geiger · 埃里克", "speakerSource": "https://www.marinerschurch.org/message/when-i-am-angered/"},
]


def public_track(track, pack, public):
    source = pack / track["file"]
    digest = sha256(source)
    if digest != track["sha256"]:
        raise ValueError("Audio differs from the verified comparison")
    name = f"{digest[:16]}-{source.name}"
    shutil.copyfile(source, public / "media" / name)
    return {"id": track["id"], "label": track["label"], "voiceLabel": track["voiceLabel"],
        "audioUrl": f"/media/{name}", "file": name, "sha256": digest,
        "durationSeconds": track["durationSeconds"], "cues": track["cues"],
        "subtitleTiming": track.get("subtitleTiming", "measured_synthesis_groups"), "scope": track.get("scope", "excerpt")}


def validate_catalog(catalog):
    if catalog.get("schemaVersion") != "sermon-weekly-catalog-v1" or not catalog.get("weeks"):
        raise ValueError("Invalid weekly catalog")
    ids = [w["id"] for w in catalog["weeks"]]
    if len(ids) != len(set(ids)) or catalog["defaultWeekId"] not in ids:
        raise ValueError("Invalid or repeated week ID")
    groups = catalog["weeks"] + [{"title": s["name"], "speaker": s["name"], "outline": [True], "tracks": [s["reference"], s["chinese"]]} for s in catalog.get("voiceBank", {}).get("speakers", [])]
    for week in groups:
        if not week.get("title") or not week.get("speaker") or not week.get("outline"):
            raise ValueError("Missing weekly content")
        for track in week["tracks"]:
            if track["audioUrl"] != f'/media/{track["file"]}' or Path(track["file"]).name != track["file"]:
                raise ValueError("Unsafe public media path")
            if not track["file"].endswith(".mp3") or track["durationSeconds"] <= 0 or not track["cues"]:
                raise ValueError("Missing playable media/cues")
            previous = 0
            for cue in track["cues"]:
                if not (0 <= previous <= cue["start"] < cue["end"] <= track["durationSeconds"] + .001) or not cue["text"].strip():
                    raise ValueError("Invalid subtitle timeline")
                previous = cue["end"]


def synchronized_candidate(work, job):
    """Verify a playback candidate without granting human / Sunday approval."""
    from run_weekly_dubbing import require, same_seconds, validate_candidate
    from weekly_dubbing import read
    evidence = validate_candidate(work)
    timing_path = work / "synchronization/report.json"
    assembly_path = work / "synchronization/assembly.json"
    try:
        timing, assembled = read(timing_path), read(assembly_path)
        render = read(work / "render/report.json")
        require(timing.get("status") == "natural_timing_fits" and timing.get("failures") == [], "Timing still has unresolved failures")
        require(assembled.get("status") == "synchronized_candidate" and assembled.get("fullDecode") == "pass", "Synchronized candidate has no complete decode receipt")
        require(assembled.get("jobSha256") == evidence["jobSha256"] == sha256(work / "job.json"), "Synchronized assembly belongs to a changed job")
        require(assembled.get("timingReportSha256") == evidence["timingReportSha256"] == sha256(timing_path), "Synchronized assembly belongs to changed timing")
        require(assembled.get("sourceNaturalMp3Sha256") == evidence["mp3Sha256"] == sha256(work / "audio/zh-natural.mp3"), "Synchronized source MP3 changed")
        require(assembled.get("sourceNaturalWavSha256") == render["sha256"] == sha256(work / "render/chinese.raw.wav"), "Synchronized source WAV changed")
        require(assembled.get("sha256") == sha256(work / "synchronization/zh-synced.mp3"), "Synchronized MP3 changed")
        require(same_seconds(assembled.get("durationSeconds"), job["sourceDurationSeconds"], .2), "Synchronized duration differs from the source video")
        # Translate the verified render cues using verified playback positions.
        # Budget / anchor / placement review validation stays in the shared runner.
        expected_cues = [{**cue, "start": cue["start"] - row["chineseStart"] + row["videoStart"],
            "end": cue["end"] - row["chineseStart"] + row["videoStart"]}
            for row in timing["blocks"] for cue in render["cues"] if cue["blockId"] == row["blockId"]]
        require(assembled.get("cues") == expected_cues, "Synchronized subtitles differ from the verified playback positions")
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError(f"Synchronized candidate evidence is incomplete: {exc}") from exc
    return assembled, {**evidence, "syncAssemblySha256": sha256(assembly_path), "syncMp3Sha256": assembled["sha256"],
        "sourceNaturalWavSha256": assembled["sourceNaturalWavSha256"]}


def weekly_job(work, public, preview, sync_preview=False):
    from weekly_dubbing import read, validate_frozen, validate_review
    if sync_preview and not preview:
        raise ValueError("--sync-preview requires --review-preview")
    job = read(work / "job.json")
    validate_frozen(job)
    if not preview:
        validate_review(work)
    synced, candidate_evidence = synchronized_candidate(work, job) if sync_preview else (None, None)
    library = load_library(work / "audio")
    if library["date"] != job["week"]:
        raise ValueError("Weekly audio is for another date")
    assembly = read(work / "assembly-report.json")
    if assembly["jobSha256"] != sha256(work / "job.json") or len(library["tracks"]) != 1 or library["tracks"][0]["sha256"] != assembly["sha256"] or [c["text"] for c in library["tracks"][0]["cues"]] != [u["text"] for u in job["units"]]:
        raise ValueError("Weekly audio/text is not bound to the prepared Saturday job")
    notes = read(Path(job["inputs"]["outline"]["path"]))
    tracks = []
    if not preview or sync_preview:
        synced = synced if sync_preview else read(work / "synchronization/assembly.json")
        synced_track = {**library["tracks"][0], "file": "zh-synced.mp3", "sha256": synced["sha256"], "durationSeconds": job["sourceDurationSeconds"], "cues": synced["cues"],
            "scope": "full_candidate" if sync_preview else "full_reviewed", "label": "同步试播 · 待现场验收" if sync_preview else "整篇中文",
            "subtitleTiming": "source_video_aligned_candidate" if sync_preview else "human_reviewed_source_video"}
        tracks = [public_track(synced_track, work / "synchronization", public)]
    else:
        tracks = [public_track(t, work / "audio", public) for t in library["tracks"]]
    screening = work / "audio/asr-screening.json"
    machine_issues = sum(len(r["reviewCandidates"]) for r in read(screening)["results"]) if screening.exists() else None
    stages = [
        {"label": "证道范围确认", "status": "pass", "detail": "沿用周六人工确认的同一份视频与证道范围"},
        {"label": "中文审校与双 PDF", "status": "pass", "detail": "复用阅读稿、两轮文字审校与证道同行大纲"},
        {"label": "讲员音色生成", "status": "pass", "detail": f'{job["speaker"]} · {len(job["units"])} 段中文已生成'},
        {"label": "配音检查", "status": "review" if machine_issues is not None else "pending", "detail": f"机器标出 {machine_issues} 处待试听比对" if machine_issues is not None else "等待漏读、重复与发音检查"},
        {"label": "视频同步与人工试听", "status": "review" if sync_preview else "pending" if preview else "pass", "detail": "同步候选已装配；模型审核不能代替现场试听，仍待核对中文流畅度、原声相似度与同视频播放" if sync_preview else "逐段核对原视频，检查中文流畅度、原声相似度与同步"},
        {"label": "周日版本发布", "status": "pending" if preview else "pass", "detail": "本次为审核试听稿" if preview else "审核通过的本周中文配音"}]
    week = {"id": job["week"], "date": job["week"], "sourceId": job["sourceId"], "sourceUrl": job["sourceUrl"], "title": job["title"], "speaker": job["speaker"],
        "scripture": job["scripture"], "number": "".join(c for c in job["scripture"] if c.isdigit()), "series": "每周证道", "centralMessage": notes["centralMessageZh"], "summary": notes["summaryZh"],
        "outline": [{"title": p["title"], "points": p["points"], "sourceSliceIndexes": p.get("sourceSliceIndexes", [])} for p in notes["outlineZh"]],
        "scriptureRefs": notes.get("scriptureRefs", []), "questions": [p["question"] for p in notes.get("reflectionQuestionsZh", [])], "contentReview": "沿用周六审校阅读稿与 AI 整理大纲",
        "tracks": tracks, "audioStatus": "full_candidate" if preview else "full_reviewed", "audioNotice": "整篇中文已生成，正在审核。时间轴对应中文音频；现场视频同步尚未验收。" if preview else "本周中文配音已审核，可使用时间轴与微调跟上现场。",
        "videoSynchronization": "not_validated" if preview else "human_reviewed", "productionStages": stages}
    if sync_preview:
        week.update(videoSynchronization="candidate_aligned", humanApproval=False, candidateEvidence=candidate_evidence,
            audioNotice=f'同步试播候选：00:00 对应当前源视频的证道起点（第 {job["sourceStartSeconds"]:g} 秒）。模型审核不等于人工验收；中文流畅度、原声相似度与同视频播放仍待现场试听。')
    return week


def build(comparison, out, expansion=None, weekly_jobs=(), voice_bank=None, review_preview=False, sync_preview=False, include_history=False):
    weekly_jobs = tuple(weekly_jobs)
    if sync_preview and (not review_preview or not weekly_jobs):
        raise ValueError("--sync-preview requires --review-preview and at least one --weekly-job")
    use_history = include_history or not weekly_jobs
    library = load_library(comparison) if use_history else None
    public = out / "public"
    if public.exists():
        raise ValueError("Use a new output directory to preserve the previous release")
    (public / "media").mkdir(parents=True)
    for name in ["index.html", "style.css", "app.mjs", "timing.mjs", "catalog.mjs", "theme.js"]:
        shutil.copyfile(HERE / "web" / name, public / name)
    weeks, sources = [], []
    for entry in (WEEKS if use_history else ()):
        pipeline = ROOT / f'artifacts/post-live-runs/{entry["date"]}/sermon_{entry["sourceId"]}/pipeline'
        notes_path = pipeline / "sermon-interpretation/insights/openai-notes.json"
        notes = json.loads(notes_path.read_text())
        if notes.get("status") != "ready" or notes.get("sermonDate") != entry["date"]:
            raise ValueError("Weekly outline source is not ready or is for a different week")
        tracks = [public_track(t, comparison, public) for t in library["tracks"] if t["id"] != "flow"] if entry["date"] == library["date"] else []
        if tracks:
            tracks[0]["label"] = "已试听版"
            if expansion:
                extra = load_library(expansion)
                if extra["date"] != library["date"] or len(extra["tracks"]) != 1:
                    raise ValueError("Expansion comparison must be for the same week")
                t = extra["tracks"][0]
                if "".join(c["text"] for c in t["cues"]) != "".join(c["text"] for c in tracks[0]["cues"]):
                    raise ValueError("Expanded voice must use exactly the same Chinese")
                exported = public_track(t, expansion, public)
                feedback_path = expansion.parent / "expanded-listening-feedback.json"
                if feedback_path.exists():
                    feedback = json.loads(feedback_path.read_text())
                    if feedback.get("status") == "user_accepted_sample" and feedback.get("sampleSha256") == t["sha256"] and feedback.get("checkpointSha256") == t.get("trainedCheckpointSha256"):
                        exported["voiceLabel"] = exported["voiceLabel"].replace("（待试听）", "")
                        exported["voiceSampleReview"] = "user_accepted_sample"
                tracks.insert(1, exported)
        week = {**entry, "id": entry["date"], "series": "当生活令人费解", "titleEvidence": "descriptive_title_from_existing_sermon_notes",
            "sourceUrl": f'https://www.youtube.com/watch?v={entry["sourceId"]}',
            "summary": notes["summaryZh"], "centralMessage": notes["centralMessageZh"],
            "outline": [{"title": p["title"], "points": p["points"], "sourceSliceIndexes": p["sourceSliceIndexes"]} for p in notes["outlineZh"]],
            "scriptureRefs": notes["scriptureRefs"], "questions": [p["question"] for p in notes["reflectionQuestionsZh"]],
            "contentReview": "AI 整理，供跟读参考", "tracks": tracks,
            "audioStatus": "excerpt_ready" if tracks else "pending",
            "audioNotice": "当前提供中文片段试听；时间轴对应中文样片，整篇配音与视频时间校准尚未完成。" if tracks else "本周大纲已就绪，中文配音待生成。",
            "videoSynchronization": "not_validated", "outlineSourceSha256": sha256(notes_path)}
        weeks.append(week)
        sources.append({"week": week["id"], "path": str(notes_path.relative_to(ROOT)), "sha256": sha256(notes_path)})
    for work in weekly_jobs:
        week = weekly_job(work, public, review_preview, sync_preview)
        weeks = [w for w in weeks if w["id"] != week["id"]] + [week]
        sources.append({"week": week["id"], "path": str(work / "job.json"), "sha256": sha256(work / "job.json")})
    weeks.sort(key=lambda w: w["date"], reverse=True)
    catalog = {"schemaVersion": "sermon-weekly-catalog-v1", "defaultWeekId": weeks[0]["id"] if weekly_jobs else library["date"], "weeks": weeks}
    if voice_bank:
        bank = json.loads(voice_bank.read_text())
        if bank.get("schemaVersion") != "sermon-speaker-auditions-v1":
            raise ValueError("Invalid speaker auditions")
        catalog["voiceBank"] = {"notice": bank["notice"], "probeText": bank["probeText"], "speakers": []}
        for speaker in bank["speakers"]:
            entry = {k: speaker[k] for k in ["id", "name", "sourceCount", "clipCount", "trainingSeconds", "humanListeningStatus", "referenceSourceUrl"]}
            for key in ["reference", "chinese"]:
                entry[key] = public_track(speaker[key], Path(speaker["pack"]), public)
            catalog["voiceBank"]["speakers"].append(entry)
    validate_catalog(catalog)
    write_json(public / "weekly.json", catalog)
    files = [{"path": str(p.relative_to(public)), "sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(public.rglob("*")) if p.is_file()]
    report = {"schemaVersion": "sermon-weekly-build-v1", "builtAt": datetime.now(timezone.utc).isoformat(), "weeks": len(weeks),
        "playableWeeks": sum(bool(w["tracks"]) for w in weeks), "files": files, "sources": sources,
        "reviewPreview": review_preview, "syncPreview": sync_preview, "includeHistory": use_history,
        "originalAudioPublished": bool(voice_bank), "originalAudioScope": "short_authorized_voice_references_only" if voice_bank else "none",
        "trainingDataPublished": False, "totalBytes": sum(f["bytes"] for f in files)}
    write_json(out / "build-report.json", report)
    print(json.dumps({k: report[k] for k in ["weeks", "playableWeeks", "totalBytes"]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON, help="Historical sample library; used without --weekly-job or with --include-history")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--expansion", type=Path)
    parser.add_argument("--weekly-job", type=Path, action="append", default=[], help="Build these weekly jobs; historical content is omitted unless --include-history is set")
    parser.add_argument("--include-history", action="store_true", help="Keep historical outlines, comparison and expansion tracks alongside weekly jobs; replace matching weeks")
    parser.add_argument("--voice-bank", type=Path)
    parser.add_argument("--review-preview", action="store_true", help="Publish clearly marked listening candidates, not Sunday-ready audio")
    parser.add_argument("--sync-preview", action="store_true", help="Use verified synchronized candidates; requires --review-preview and --weekly-job")
    args = parser.parse_args()
    if args.sync_preview and (not args.review_preview or not args.weekly_job):
        parser.error("--sync-preview requires --review-preview and at least one --weekly-job")
    build(args.comparison.resolve(), args.out.resolve(), args.expansion.resolve() if args.expansion else None,
        [p.resolve() for p in args.weekly_job], args.voice_bank.resolve() if args.voice_bank else None, args.review_preview, args.sync_preview, args.include_history)
