"""Mandatory local, source-bound listening index for synchronized weekly pages."""
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile

from poc import probe, sha256

HERE = Path(__file__).resolve().parent
SCHEMA = "sermon-automatic-audio-alignment-v1"


def bind_weekly_fingerprint(job, week, public, *, synchronized, process_runner=None, media_probe=None):
    if not synchronized:
        week["automaticAudioAlignment"] = {"schemaVersion": SCHEMA, "status": "unavailable", "required": False,
            "reason": "unsynchronized_review_preview"}
        return
    process_runner = process_runner or subprocess.run
    media_probe = media_probe or probe
    inputs = job.get("inputs", {})
    route = job.get("sourceRoute", "live_archive")
    source = inputs.get("originalAudio")
    # Caption archives have a verified, complete sermon-only audio contract.
    if route == "archive_caption":
        contract = json.loads(Path(inputs["sourceContract"]["path"]).read_text())
        source = inputs.get("sourceAudio")
        if not source or contract.get("audio", {}).get("sha256") != source.get("sha256") or contract.get("sermonOnly") is not True:
            raise ValueError("Automatic listening alignment requires the verified complete archive audio")
    if route not in {"live_archive", "same_video", "archive_caption"} or not source:
        raise ValueError("Automatic listening alignment requires frozen originalAudio; prepare a new source-bound job")
    path = Path(source["path"])
    digest = source.get("sha256", "")
    if not re.fullmatch(r"[a-f0-9]{64}", digest) or not path.is_file() or sha256(path) != digest:
        raise ValueError("Automatic listening alignment original source is missing or changed")
    start, end, duration = (job.get(k) for k in ("sourceStartSeconds", "sourceEndSeconds", "sourceDurationSeconds"))
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end, duration))
            or not 0 <= start < end or abs(end - start - duration) > .001):
        raise ValueError("Automatic listening alignment requires an explicit absolute source window")
    if route == "live_archive":
        clip = json.loads(Path(inputs["clipReceipt"]["path"]).read_text()) if "clipReceipt" in inputs else {}
        if (clip.get("source", {}).get("sha256") != digest or clip.get("startSeconds") != start or clip.get("endSeconds") != end):
            raise ValueError("Automatic listening alignment source/window differs from the frozen clip receipt")
    measured = media_probe(path)
    if (not any(s.get("codec_type") == "audio" for s in measured.get("streams", []))
            or not math.isfinite(measured["durationSeconds"]) or end > measured["durationSeconds"] + .05):
        raise ValueError("Automatic listening alignment source does not contain the complete window")
    tracks = week["tracks"]
    if (len(tracks) != 1 or abs(tracks[0]["durationSeconds"] - duration) > .1
            or tracks[0].get("subtitleTiming") not in {"source_video_aligned_candidate", "human_reviewed_source_video"}):
        raise ValueError("Automatic listening alignment requires one source-clock synchronized track")
    track = tracks[0]
    if sha256(public / "media" / track["file"]) != track["sha256"]:
        raise ValueError("Automatic listening alignment Chinese track changed")
    identity = {"pageId": week["id"], "sourceSha256": digest, "trackSha256": track["sha256"],
        "sourceStartSeconds": start, "sourceEndSeconds": end, "algorithmVersion": "spectral-landmarks-v1"}
    with tempfile.TemporaryDirectory(prefix="weekly-fingerprint-") as tmp:
        index_path = Path(tmp) / "landmarks.json"
        process_runner(["node", str(HERE / "build_fingerprint_index.mjs"), "--source", str(path), "--source-sha", digest,
            "--track-sha", track["sha256"], "--page-id", week["id"], "--start", str(start), "--end", str(end), "--out", str(index_path)],
            check=True, capture_output=True, text=True, timeout=1800)
        index = json.loads(index_path.read_text())
        if (index.get("schemaVersion") != "sermon-landmark-index-v1" or any(index.get(k) != v for k, v in identity.items())
                or not index.get("postings") or not 0 < index.get("landmarkCount", 0) <= 1000000):
            raise ValueError("Automatic listening alignment produced an empty or mismatched index")
        index_hash = sha256(index_path)
        destination = public / "fingerprints" / f"{index_hash[:16]}-landmarks.json"
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(index_path.read_bytes())
    # A changed source cannot be accepted even if it changed during extraction.
    if sha256(path) != digest:
        raise ValueError("Automatic listening alignment original source changed during extraction")
    week.update(sourceSha256=digest, sourceStartSeconds=start, sourceEndSeconds=end, sourceDurationSeconds=duration)
    week["audioFingerprint"] = {"schemaVersion": "sermon-audio-fingerprint-binding-v1", **identity,
        "captureSeconds": 10, "indexSha256": index_hash, "indexUrl": f"/fingerprints/{destination.name}"}
    week["automaticAudioAlignment"] = {"schemaVersion": SCHEMA, "status": "ready", "required": True}
