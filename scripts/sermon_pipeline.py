#!/usr/bin/env python3
"""Hybrid OpenAI pipeline for weekly offline sermon subtitle files."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path


TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
CHAT_URL = "https://api.openai.com/v1/chat/completions"

DEFAULT_GLOSSARY = [
    "Mariners Church",
    "Jared",
    "Kirby Wood",
    "Eric",
    "Numbers",
    "Exodus",
    "Moses",
    "Aaron",
    "Miriam",
    "Korah",
    "Kadesh",
    "Meribah",
    "Canaan",
    "Caesarea Philippi",
    "Tim Keller",
    "Zlatan",
    "Lexi",
    "Jesus",
    "Holy Spirit",
]

DEFAULT_ZH_TERM_MAP = {
    "Numbers": "民数记",
    "Exodus": "出埃及记",
    "Moses": "摩西",
    "Aaron": "亚伦",
    "Miriam": "米利暗",
    "Korah": "可拉",
    "Kadesh": "加低斯",
    "Meribah": "米利巴",
    "Canaan": "迦南",
    "Pharaoh": "法老",
    "Nile River": "尼罗河",
    "Red Sea": "红海",
    "Caesarea Philippi": "该撒利亚腓立比",
    "Jesus": "耶稣",
    "Holy Spirit": "圣灵",
}


def run(cmd):
    subprocess.run(cmd, check=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_env(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def clean_text(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def parse_timecode(value):
    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"Unsupported timecode: {value}")


def srt_time(seconds):
    seconds = max(0, seconds)
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def vtt_time(seconds):
    return srt_time(seconds).replace(",", ".")


def ffprobe_duration(path):
    proc = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(proc.stdout)["format"]["duration"])


def request_json(req, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            if attempt == retries - 1 or exc.code < 500:
                raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("Request failed")


def multipart_request(url, api_key, fields, file_field, file_path, retries=3):
    boundary = "----codex-" + uuid.uuid4().hex
    body = bytearray()

    def add_field(name, value):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")

    for key, value in fields.items():
        if isinstance(value, list):
            for item in value:
                add_field(key, item)
        else:
            add_field(key, value)

    data = file_path.read_bytes()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n'
            "Content-Type: audio/mp4\r\n\r\n"
        ).encode()
    )
    body.extend(data)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    return request_json(req, retries=retries)


def json_request(url, api_key, payload, retries=3):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return request_json(req, retries=retries)


def load_glossary(path):
    payload = {"terms": DEFAULT_GLOSSARY, "zh_term_map": DEFAULT_ZH_TERM_MAP.copy()}
    if not path:
        return payload
    data = read_json(path)
    if isinstance(data, list):
        payload["terms"] = [str(item) for item in data]
        return payload
    if isinstance(data, dict):
        terms = data.get("terms", [])
        if isinstance(terms, list):
            payload["terms"] = [str(item) for item in terms]
        if isinstance(terms, dict):
            payload["terms"] = [f"{key}: {value}" for key, value in terms.items()]
        zh_term_map = data.get("zh_term_map") or data.get("zhTerms") or data.get("zh_terms")
        if isinstance(zh_term_map, dict):
            payload["zh_term_map"].update({str(key): str(value) for key, value in zh_term_map.items()})
        if payload["terms"]:
            return payload
    raise SystemExit(f"Unsupported glossary format: {path}")


def glossary_terms(glossary):
    return glossary.get("terms", []) if isinstance(glossary, dict) else glossary


def zh_term_map(glossary):
    return glossary.get("zh_term_map", {}) if isinstance(glossary, dict) else DEFAULT_ZH_TERM_MAP


def glossary_prompt(glossary):
    return ", ".join(glossary_terms(glossary))


def glossary_lines(glossary):
    lines = [f"- {term}" for term in glossary_terms(glossary)]
    mapping = zh_term_map(glossary)
    if mapping:
        lines.append("")
        lines.append("Preferred Simplified Chinese term map:")
        lines.extend(f"- {key} => {value}" for key, value in mapping.items())
    return "\n".join(lines)


def normalize_zh_terms(text, glossary):
    normalized = text
    for source, target in sorted(zh_term_map(glossary).items(), key=lambda item: len(item[0]), reverse=True):
        normalized = re.sub(rf"(?<![A-Za-z]){re.escape(source)}(?![A-Za-z])", target, normalized)
    return normalized


def make_outdir(root, slug, explicit):
    if explicit:
        path = explicit
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = root / slug / f"pipeline_{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clip_and_normalize(source, clip_path, start, end):
    if clip_path.exists():
        return
    duration_args = []
    if end is not None:
        duration_args = ["-t", f"{max(0.0, end - start):.3f}"]
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-ss",
            f"{start:.3f}",
            *duration_args,
            "-i",
            str(source),
            "-vn",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(clip_path),
        ]
    )


def cut_chunk(source, dest, start, duration):
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(dest),
        ]
    )


def transcribe_gpt4o_chunks(api_key, clip_path, outdir, chunk_seconds, model, glossary):
    output = outdir / "asr_gpt4o_chunks.json"
    if output.exists():
        return read_json(output)

    duration = ffprobe_duration(clip_path)
    chunks_dir = outdir / "chunks_gpt4o"
    chunks = []
    prompt = (
        "English Christian sermon transcript. Important terms: "
        + glossary_prompt(glossary)
        + ". Preserve Bible book names, place names, speaker names, and sports/person names."
    )
    chunk_count = int((duration + chunk_seconds - 0.001) // chunk_seconds)
    for index in range(chunk_count):
        start = index * chunk_seconds
        length = min(chunk_seconds, duration - start)
        if length <= 0:
            continue
        audio = chunks_dir / f"chunk_{index:04d}.m4a"
        result_path = chunks_dir / f"chunk_{index:04d}.json"
        cut_chunk(clip_path, audio, start, length)
        if result_path.exists():
            result = read_json(result_path)
        else:
            result = multipart_request(
                TRANSCRIBE_URL,
                api_key,
                {
                    "model": model,
                    "response_format": "json",
                    "language": "en",
                    "prompt": prompt,
                },
                "file",
                audio,
            )
            write_json(result_path, result)
        chunks.append(
            {
                "id": index,
                "start": round(start, 3),
                "end": round(start + length, 3),
                "duration": round(length, 3),
                "text": clean_text(result.get("text", "")),
                "usage": result.get("usage"),
            }
        )
        print(f"gpt-4o-transcribe chunk {index + 1}/{chunk_count}", flush=True)
    write_json(output, chunks)
    return chunks


def transcribe_whisper(api_key, clip_path, outdir, model, glossary):
    output = outdir / "asr_whisper_verbose.json"
    if output.exists():
        return read_json(output)
    result = multipart_request(
        TRANSCRIBE_URL,
        api_key,
        {
            "model": model,
            "response_format": "verbose_json",
            "language": "en",
            "prompt": "English Christian sermon transcript. Important terms: " + glossary_prompt(glossary) + ".",
        },
        "file",
        clip_path,
    )
    write_json(output, result)
    return result


def normalize_whisper_segments(raw):
    segments = []
    for idx, seg in enumerate(raw.get("segments", [])):
        text = clean_text(seg.get("text", ""))
        if text:
            segments.append(
                {
                    "id": idx,
                    "start": round(float(seg["start"]), 3),
                    "end": round(float(seg["end"]), 3),
                    "text": text,
                    "source": "whisper-1",
                }
            )
    return segments


def chunk_text_for_window(chunks, start, end):
    parts = []
    for chunk in chunks:
        if chunk["end"] >= start - 20 and chunk["start"] <= end + 20 and chunk["text"]:
            parts.append(f"[{chunk['start']:.1f}-{chunk['end']:.1f}] {chunk['text']}")
    return "\n".join(parts)


def chat_json(api_key, payload, retries=3):
    last_error = None
    for attempt in range(retries):
        try:
            return json_request(CHAT_URL, api_key, payload, retries=1)
        except Exception as exc:
            last_error = exc
            if "temperature" in str(exc) and "temperature" in payload:
                payload = {key: value for key, value in payload.items() if key != "temperature"}
            time.sleep(2**attempt)
    raise last_error


def same_ids(expected, returned):
    return [item.get("id") for item in returned] == [item["id"] for item in expected]


def correct_english(api_key, segments, gpt4o_chunks, outdir, model, glossary, window_seconds):
    output = outdir / "segments_timed_en_corrected.json"
    if output.exists():
        return read_json(output)

    corrected = []
    windows_dir = outdir / "correction_windows"
    glossary_text = glossary_lines(glossary)
    start_index = 0
    while start_index < len(segments):
        window_start = segments[start_index]["start"]
        window_end = window_start + window_seconds
        end_index = start_index
        while end_index < len(segments) and segments[end_index]["start"] < window_end:
            end_index += 1
        batch = segments[start_index:end_index]
        cache = windows_dir / f"window_{batch[0]['id']:04d}_{batch[-1]['id']:04d}.json"
        parsed = read_json(cache) if cache.exists() else None
        returned = parsed.get("segments", []) if parsed else []
        if parsed and not same_ids(batch, returned):
            cache.unlink()
            parsed = None
            returned = []
        if parsed is None:
            reference = chunk_text_for_window(gpt4o_chunks, batch[0]["start"], batch[-1]["end"])
            payload = {
                "model": model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You correct English ASR subtitle segments for a Christian sermon. "
                            "Return every input id exactly once, in the same order. Keep the same "
                            "count. Do not merge, split, omit, add, reorder, or translate segments. "
                            "Return only JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Glossary:\n"
                            + glossary_text
                            + "\n\nReference transcript from a stronger ASR model:\n"
                            + reference
                            + "\n\nTimed segments to correct. Return "
                            '{"segments":[{"id":number,"text":"corrected English"}]}.\n'
                            + json.dumps(
                                [{"id": s["id"], "text": s["text"]} for s in batch],
                                ensure_ascii=False,
                            )
                        ),
                    },
                ],
            }
            result = chat_json(api_key, payload)
            parsed = json.loads(result["choices"][0]["message"]["content"])
            write_json(cache, parsed)
        returned = parsed.get("segments", [])
        if not same_ids(batch, returned):
            missing = [seg["id"] for seg in batch if seg["id"] not in {item.get("id") for item in returned}]
            extra = [item.get("id") for item in returned if item.get("id") not in {seg["id"] for seg in batch}]
            warning_path = outdir / "correction_warnings.jsonl"
            warning_path.parent.mkdir(parents=True, exist_ok=True)
            with warning_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "window": [batch[0]["id"], batch[-1]["id"]],
                            "missingIdsFallbackToWhisper": missing,
                            "extraIdsIgnored": extra,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        by_id = {item["id"]: clean_text(item.get("text", "")) for item in returned}
        for seg in batch:
            text = by_id.get(seg["id"]) or seg["text"]
            corrected.append({**seg, "text": text, "correction_model": model})
        print(f"corrected {len(corrected)}/{len(segments)}", flush=True)
        start_index = end_index
    write_json(output, corrected)
    return corrected


def clamp_overlaps(segments):
    items = [{**seg} for seg in sorted(segments, key=lambda item: (item["start"], item["end"]))]
    for idx, seg in enumerate(items):
        seg["id"] = idx
    for idx in range(len(items) - 1):
        if items[idx]["end"] > items[idx + 1]["start"]:
            items[idx]["end"] = max(items[idx]["start"] + 0.1, items[idx + 1]["start"])
    return items


def shape_durations(segments, min_duration=1.0, max_duration=7.0):
    items = clamp_overlaps(segments)
    for idx, seg in enumerate(items):
        next_start = items[idx + 1]["start"] if idx + 1 < len(items) else None
        duration = seg["end"] - seg["start"]
        if duration > max_duration:
            seg["end"] = seg["start"] + max_duration
        elif duration < min_duration:
            desired = seg["start"] + min_duration
            if next_start is None or desired <= next_start:
                seg["end"] = desired
    return clamp_overlaps(items)


def split_long_line(text, max_chars):
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    separators = ["，", "。", "；", "、", ", ", "; ", ": ", " "]
    lines = []
    remaining = text
    while remaining and len(lines) < 2:
        if len(remaining) <= max_chars:
            lines.append(remaining)
            remaining = ""
            break
        cut = -1
        for sep in separators:
            pos = remaining.rfind(sep, 0, max_chars + 1)
            if pos > cut:
                cut = pos + len(sep)
        if cut <= 0:
            cut = max_chars
        lines.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining and lines:
        lines[-1] = clean_text(lines[-1] + " " + remaining)
    return "\n".join(lines[:2])


def render_subtitle_text(text, lang):
    return split_long_line(text, 20 if lang == "zh" else 42)


def write_srt(path, segments, key, offset=0.0, lang="en"):
    lines = []
    for idx, seg in enumerate(segments, 1):
        lines.extend(
            [
                str(idx),
                f"{srt_time(seg['start'] + offset)} --> {srt_time(seg['end'] + offset)}",
                render_subtitle_text(seg.get(key, ""), lang),
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_vtt(path, segments, key, offset=0.0, lang="en"):
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.extend(
            [
                f"{vtt_time(seg['start'] + offset)} --> {vtt_time(seg['end'] + offset)}",
                render_subtitle_text(seg.get(key, ""), lang),
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def translate_chinese(api_key, segments, outdir, model, glossary):
    output = outdir / "segments_timed_zh.json"
    if output.exists():
        return read_json(output)
    translated = []
    glossary_text = glossary_lines(glossary)
    system = (
        "You are a careful Simplified Chinese subtitle translator for a Christian sermon. "
        "Translate exactly the current English subtitle segment only. Keep the same id. "
        "Do not translate neighboring context. Preserve Bible terms and proper nouns. "
        "Return only JSON."
    )
    for idx, seg in enumerate(segments):
        cache = outdir / "translation_segments" / f"seg_{seg['id']:04d}.json"
        if cache.exists():
            parsed = read_json(cache)
        else:
            context = {
                "glossary": glossary_terms(glossary),
                "zh_term_map": zh_term_map(glossary),
                "previous_english": segments[idx - 1]["text"] if idx > 0 else "",
                "current_id": seg["id"],
                "current_english": seg["text"],
                "next_english": segments[idx + 1]["text"] if idx + 1 < len(segments) else "",
            }
            payload = {
                "model": model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            "Glossary:\n"
                            + glossary_text
                            + "\n\nTranslate only current_english. Return "
                            '{"id": current_id, "zh": "..."}.\n\n'
                            + json.dumps(context, ensure_ascii=False)
                        ),
                    },
                ],
            }
            result = chat_json(api_key, payload)
            parsed = json.loads(result["choices"][0]["message"]["content"])
            parsed["_model"] = result.get("model", model)
            write_json(cache, parsed)
        if parsed.get("id") != seg["id"]:
            raise RuntimeError(f"Chinese translation id mismatch for segment {seg['id']}")
        zh = normalize_zh_terms(clean_text(parsed.get("zh", "")), glossary)
        if not zh:
            raise RuntimeError(f"Empty Chinese translation for segment {seg['id']}")
        translated.append({**seg, "zh": zh, "translation_model": parsed.get("_model", model)})
        if (idx + 1) % 25 == 0 or idx + 1 == len(segments):
            print(f"translated zh {idx + 1}/{len(segments)}", flush=True)
    write_json(output, translated)
    return translated


def cps(text, duration):
    if duration <= 0:
        return float("inf")
    return len(clean_text(text).replace("\n", "")) / duration


def qa_report(en_segments, zh_segments, glossary):
    overlaps = []
    for previous, current in zip(zh_segments, zh_segments[1:]):
        if current["start"] < previous["end"] - 0.001:
            overlaps.append([previous["id"], current["id"]])

    def line_violations(items, key, lang):
        max_chars = 20 if lang == "zh" else 42
        violations = []
        for item in items:
            rendered = render_subtitle_text(item.get(key, ""), lang)
            lines = rendered.splitlines() or [""]
            if len(lines) > 2 or any(len(line) > max_chars for line in lines):
                violations.append(item["id"])
        return violations

    zh_cps = [
        {"id": item["id"], "cps": round(cps(item.get("zh", ""), item["end"] - item["start"]), 2)}
        for item in zh_segments
        if cps(item.get("zh", ""), item["end"] - item["start"]) > 20
    ]
    glossary_text = " ".join(item.get("text", "") + " " + item.get("zh", "") for item in zh_segments)
    missing_glossary = [
        term for term in glossary_terms(glossary) if re.search(r"[A-Za-z]", term) and term.split(":")[0] not in glossary_text
    ]
    latin_bible_terms = []
    for item in zh_segments:
        for source in zh_term_map(glossary):
            if re.search(rf"(?<![A-Za-z]){re.escape(source)}(?![A-Za-z])", item.get("zh", "")):
                latin_bible_terms.append({"id": item["id"], "term": source, "zh": item.get("zh", "")})
    suspicious_asr = []
    combined_en = " ".join(item.get("text", "") for item in en_segments)
    if re.search(r"road trip|continuous driving|6,000 miles", combined_en, re.I) and re.search(
        r"\b88\s+miles\b", combined_en, re.I
    ):
        suspicious_asr.append(
            {
                "pattern": "88 miles near road trip context",
                "note": "Likely ASR/correction error; expected '88 hours' in the Mariners sample.",
            }
        )
    if re.search(r"\b80\s+years\b", combined_en, re.I):
        suspicious_asr.append(
            {
                "pattern": "80 years",
                "note": "Check whether this should be '80 miles', '88 hours', or another unit.",
            }
        )
    report = {
        "segmentCount": len(zh_segments),
        "emptyEnglish": [item["id"] for item in en_segments if not item.get("text", "").strip()],
        "emptyChinese": [item["id"] for item in zh_segments if not item.get("zh", "").strip()],
        "overlaps": overlaps,
        "durationViolations": [
            item["id"] for item in zh_segments if item["end"] - item["start"] <= 0 or item["end"] - item["start"] > 7.5
        ],
        "englishLineLengthViolations": line_violations(en_segments, "text", "en"),
        "chineseLineLengthViolations": line_violations(zh_segments, "zh", "zh"),
        "chineseCpsWarnings": zh_cps,
        "glossaryTermsNotObserved": missing_glossary,
        "latinBibleTermWarnings": latin_bible_terms,
        "suspiciousAsrWarnings": suspicious_asr,
        "translationIdMismatchCount": len([1 for en, zh in zip(en_segments, zh_segments) if en["id"] != zh["id"]]),
    }
    report["hardFailures"] = {
        "emptyEnglish": len(report["emptyEnglish"]),
        "emptyChinese": len(report["emptyChinese"]),
        "overlaps": len(report["overlaps"]),
        "translationIdMismatchCount": report["translationIdMismatchCount"],
    }
    return report


def compare_reports(path_a, path_b):
    a = read_json(path_a)
    b = read_json(path_b)
    return {
        "candidateA": str(path_a),
        "candidateB": str(path_b),
        "segmentCount": [len(a), len(b)],
        "emptyChinese": [
            len([item for item in a if not item.get("zh", "").strip()]),
            len([item for item in b if not item.get("zh", "").strip()]),
        ],
        "durationEnd": [a[-1]["end"] if a else None, b[-1]["end"] if b else None],
    }


def main():
    parser = argparse.ArgumentParser(description="Hybrid OpenAI sermon subtitle pipeline")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--slug", default="sermon")
    parser.add_argument("--outdir", type=Path)
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--gpt4o-model", default="gpt-4o-transcribe")
    parser.add_argument("--timing-model", default="whisper-1")
    parser.add_argument("--en-correction-model", default="gpt-5.4-mini")
    parser.add_argument("--zh-model", default="gpt-5.5")
    parser.add_argument("--chunk-seconds", type=float, default=45.0)
    parser.add_argument("--correction-window-seconds", type=float, default=240.0)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--candidate-a", type=Path)
    parser.add_argument("--candidate-b", type=Path)
    args = parser.parse_args()

    if args.compare:
        if not args.candidate_a or not args.candidate_b:
            raise SystemExit("--compare requires --candidate-a and --candidate-b")
        print(json.dumps(compare_reports(args.candidate_a, args.candidate_b), ensure_ascii=False, indent=2))
        return

    if not args.input or args.start_time is None:
        raise SystemExit("--input and --start-time are required")

    load_env(Path(".env"))
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set")

    source_duration = ffprobe_duration(args.input)
    start = parse_timecode(args.start_time)
    end = parse_timecode(args.end_time) if args.end_time else source_duration
    outdir = make_outdir(args.artifacts_root, args.slug, args.outdir)
    glossary = load_glossary(args.glossary)

    clip_path = outdir / "source_clip.m4a"
    clip_and_normalize(args.input, clip_path, start, end)
    clip_duration = ffprobe_duration(clip_path)

    gpt4o_chunks = transcribe_gpt4o_chunks(api_key, clip_path, outdir, args.chunk_seconds, args.gpt4o_model, glossary)
    whisper_raw = transcribe_whisper(api_key, clip_path, outdir, args.timing_model, glossary)
    raw_segments = normalize_whisper_segments(whisper_raw)
    write_json(outdir / "segments_timed_en_raw.json", raw_segments)

    corrected = correct_english(
        api_key,
        raw_segments,
        gpt4o_chunks,
        outdir,
        args.en_correction_model,
        glossary,
        args.correction_window_seconds,
    )
    shaped_en = shape_durations(corrected)
    write_json(outdir / "segments_timed_en_corrected.json", shaped_en)

    translated = translate_chinese(api_key, shaped_en, outdir, args.zh_model, glossary)
    shaped_zh = shape_durations(translated)
    write_json(outdir / "segments_timed_zh.json", shaped_zh)

    write_srt(outdir / "sermon_en_relative.srt", shaped_en, "text", lang="en")
    write_vtt(outdir / "sermon_en_relative.vtt", shaped_en, "text", lang="en")
    write_srt(outdir / "sermon_zh_relative.srt", shaped_zh, "zh", lang="zh")
    write_vtt(outdir / "sermon_zh_relative.vtt", shaped_zh, "zh", lang="zh")
    write_srt(outdir / "full_video_en_from_sermon.srt", shaped_en, "text", offset=start, lang="en")
    write_vtt(outdir / "full_video_en_from_sermon.vtt", shaped_en, "text", offset=start, lang="en")
    write_srt(outdir / "full_video_zh_from_sermon.srt", shaped_zh, "zh", offset=start, lang="zh")
    write_vtt(outdir / "full_video_zh_from_sermon.vtt", shaped_zh, "zh", offset=start, lang="zh")

    qa = qa_report(shaped_en, shaped_zh, glossary)
    write_json(outdir / "qa_report.json", qa)
    summary = {
        "source": str(args.input),
        "sourceDurationSeconds": source_duration,
        "sourceClip": str(clip_path),
        "clipDurationSeconds": clip_duration,
        "sermonStartSeconds": start,
        "sermonStartTimecode": srt_time(start).replace(",", "."),
        "sermonEndSeconds": end,
        "sermonEndTimecode": srt_time(end).replace(",", "."),
        "models": {
            "referenceAsr": args.gpt4o_model,
            "timingAsr": args.timing_model,
            "englishCorrection": args.en_correction_model,
            "chineseTranslation": args.zh_model,
        },
        "segmentCount": len(shaped_zh),
        "qaHardFailures": qa["hardFailures"],
        "outputs": [
            "sermon_en_relative.srt",
            "sermon_zh_relative.srt",
            "full_video_en_from_sermon.srt",
            "full_video_zh_from_sermon.srt",
            "qa_report.json",
        ],
        "argv": sys.argv[1:],
    }
    write_json(outdir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
