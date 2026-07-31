#!/usr/bin/env python3
"""Hybrid OpenAI pipeline for weekly offline sermon subtitle files."""

import argparse
import concurrent.futures
import hashlib
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import review_prompts  # noqa: E402


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

GPT_TRANSCRIBE_MODELS = {"gpt-transcribe", "gpt-live-transcribe"}
DEFAULT_TRANSCRIPTION_LANGUAGES = ["en"]
MAX_SINGLE_TRANSCRIPTION_BYTES = 24 * 1024 * 1024
READING_SEGMENT_TARGET_CHARS = 420


def run(cmd):
    subprocess.run(cmd, check=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def json_sha256(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def is_gpt_transcribe_model(model):
    return model in GPT_TRANSCRIBE_MODELS


def normalized_transcription_keywords(values):
    keywords = []
    for value in values or []:
        raw_keyword = str(value)
        if any(character in raw_keyword for character in "<>\r\n"):
            continue
        keyword = clean_text(raw_keyword)
        if not keyword:
            continue
        if keyword not in keywords:
            keywords.append(keyword)
    return keywords


def transcription_request_fields(
    model,
    *,
    response_format,
    prompt,
    keywords=None,
    languages=None,
):
    expected_languages = [clean_text(str(item)) for item in (languages or []) if clean_text(str(item))]
    fields = {
        "model": model,
        "response_format": response_format,
        "prompt": prompt,
    }
    if is_gpt_transcribe_model(model):
        if expected_languages:
            fields["languages[]"] = expected_languages
        normalized_keywords = normalized_transcription_keywords(keywords)
        if normalized_keywords:
            fields["keywords[]"] = normalized_keywords
    elif expected_languages:
        fields["language"] = expected_languages[0]
    return fields


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def transcription_cache_identity(
    *,
    model,
    response_format,
    prompt,
    keywords,
    languages,
    audio_path,
    start=None,
    end=None,
):
    return {
        "schemaVersion": 1,
        "model": model,
        "responseFormat": response_format,
        "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "keywordsSha256": hashlib.sha256(
            json.dumps(normalized_transcription_keywords(keywords), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "languages": list(languages or []),
        "audioSha256": file_sha256(audio_path),
        "startSeconds": start,
        "endSeconds": end,
    }


def read_transcription_cache(result_path, metadata_path, identity):
    if not result_path.exists() or not metadata_path.exists():
        return None
    try:
        if read_json(metadata_path) != identity:
            return None
        return read_json(result_path)
    except (OSError, json.JSONDecodeError):
        return None


def write_transcription_cache(result_path, metadata_path, result, identity):
    write_json(result_path, result)
    write_json(metadata_path, identity)


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
        expected_duration = None if end is None else max(0.0, end - start)
        try:
            existing_duration = ffprobe_duration(clip_path)
        except Exception:
            existing_duration = None
        if existing_duration is not None and (
            expected_duration is None or abs(existing_duration - expected_duration) <= 1.0
        ):
            return
    duration_args = []
    if end is not None:
        duration_args = ["-t", f"{max(0.0, end - start):.3f}"]
    run(
        [
            "ffmpeg",
            "-nostdin",
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
            "-ar",
            "44100",
            "-ac",
            "1",
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
            "-nostdin",
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
            "-ar",
            "44100",
            "-ac",
            "1",
            "-b:a",
            "64k",
            str(dest),
        ]
    )


def transcribe_openai_audio(
    api_key,
    model,
    prompt,
    audio_path,
    *,
    keywords=None,
    languages=None,
    response_format="json",
):
    return multipart_request(
        TRANSCRIBE_URL,
        api_key,
        transcription_request_fields(
            model,
            response_format=response_format,
            prompt=prompt,
            keywords=keywords,
            languages=languages or DEFAULT_TRANSCRIPTION_LANGUAGES,
        ),
        "file",
        audio_path,
    )


def reencode_transcription_fallback(source, dest):
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )


def reference_transcription_prompt(glossary):
    return (
        "English Christian sermon recorded at Mariners Church. Preserve the speaker's complete meaning, "
        "Bible book and character names, scripture references, place names, ministry names, and personal names. "
        "The recording may include an introduction, prayer, illustrations, quotations, and a closing response."
    )


def reference_transcription_keywords(glossary):
    return normalized_transcription_keywords(glossary_terms(glossary))


def transcribe_reference_chunks(api_key, clip_path, outdir, chunk_seconds, model, glossary):
    output = outdir / "asr_reference_chunks.json"
    duration = ffprobe_duration(clip_path)
    chunks_dir = outdir / "chunks_reference"
    chunks = []
    prompt = reference_transcription_prompt(glossary)
    keywords = reference_transcription_keywords(glossary)
    languages = DEFAULT_TRANSCRIPTION_LANGUAGES
    chunk_count = int((duration + chunk_seconds - 0.001) // chunk_seconds)
    for index in range(chunk_count):
        start = index * chunk_seconds
        length = min(chunk_seconds, duration - start)
        if length <= 0:
            continue
        audio = chunks_dir / f"chunk_{index:04d}.m4a"
        result_path = chunks_dir / f"chunk_{index:04d}.json"
        metadata_path = chunks_dir / f"chunk_{index:04d}.request.json"
        cut_chunk(clip_path, audio, start, length)
        identity = transcription_cache_identity(
            model=model,
            response_format="json",
            prompt=prompt,
            keywords=keywords,
            languages=languages,
            audio_path=audio,
            start=round(start, 3),
            end=round(start + length, 3),
        )
        result = read_transcription_cache(result_path, metadata_path, identity)
        if result is None:
            try:
                result = transcribe_openai_audio(
                    api_key,
                    model,
                    prompt,
                    audio,
                    keywords=keywords,
                    languages=languages,
                )
            except RuntimeError as exc:
                if "Audio file might be corrupted or unsupported" not in str(exc):
                    raise
                fallback_audio = audio.with_suffix(".wav")
                reencode_transcription_fallback(audio, fallback_audio)
                identity = transcription_cache_identity(
                    model=model,
                    response_format="json",
                    prompt=prompt,
                    keywords=keywords,
                    languages=languages,
                    audio_path=fallback_audio,
                    start=round(start, 3),
                    end=round(start + length, 3),
                )
                result = transcribe_openai_audio(
                    api_key,
                    model,
                    prompt,
                    fallback_audio,
                    keywords=keywords,
                    languages=languages,
                )
            write_transcription_cache(result_path, metadata_path, result, identity)
        chunks.append(
            {
                "id": index,
                "start": round(start, 3),
                "end": round(start + length, 3),
                "duration": round(length, 3),
                "text": clean_text(result.get("text", "")),
                "usage": result.get("usage"),
                "detectedLanguages": result.get("languages", []),
            }
        )
        print(f"{model} reference chunk {index + 1}/{chunk_count}", flush=True)
    write_json(output, chunks)
    return chunks


def transcribe_reference(api_key, clip_path, outdir, chunk_seconds, model, glossary):
    if clip_path.stat().st_size > MAX_SINGLE_TRANSCRIPTION_BYTES:
        return transcribe_reference_chunks(
            api_key,
            clip_path,
            outdir,
            chunk_seconds,
            model,
            glossary,
        )

    duration = ffprobe_duration(clip_path)
    prompt = reference_transcription_prompt(glossary)
    keywords = reference_transcription_keywords(glossary)
    languages = DEFAULT_TRANSCRIPTION_LANGUAGES
    result_path = outdir / "asr_reference.json"
    metadata_path = outdir / "asr_reference.request.json"
    identity = transcription_cache_identity(
        model=model,
        response_format="json",
        prompt=prompt,
        keywords=keywords,
        languages=languages,
        audio_path=clip_path,
        start=0.0,
        end=round(duration, 3),
    )
    result = read_transcription_cache(result_path, metadata_path, identity)
    if result is None:
        try:
            result = transcribe_openai_audio(
                api_key,
                model,
                prompt,
                clip_path,
                keywords=keywords,
                languages=languages,
            )
        except RuntimeError as exc:
            if "Audio file might be corrupted or unsupported" not in str(exc):
                raise
            return transcribe_reference_chunks(
                api_key,
                clip_path,
                outdir,
                chunk_seconds,
                model,
                glossary,
            )
        write_transcription_cache(result_path, metadata_path, result, identity)
    chunks = [
        {
            "id": 0,
            "start": 0.0,
            "end": round(duration, 3),
            "duration": round(duration, 3),
            "text": clean_text(result.get("text", "")),
            "usage": result.get("usage"),
            "detectedLanguages": result.get("languages", []),
        }
    ]
    write_json(outdir / "asr_reference_chunks.json", chunks)
    return chunks


def transcribe_gpt4o_chunks(api_key, clip_path, outdir, chunk_seconds, model, glossary):
    """Compatibility wrapper for older callers."""
    return transcribe_reference_chunks(api_key, clip_path, outdir, chunk_seconds, model, glossary)


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


def split_reading_paragraphs(text, target_chars=READING_SEGMENT_TARGET_CHARS):
    sentences = [
        clean_text(item)
        for item in re.split(r"(?<=[.!?])\s+", clean_text(text))
        if clean_text(item)
    ]
    expanded_sentences = []
    for sentence in sentences:
        remaining = sentence
        while len(remaining) > target_chars:
            cut = remaining.rfind(" ", 0, target_chars + 1)
            if cut <= 0:
                cut = target_chars
            expanded_sentences.append(clean_text(remaining[:cut]))
            remaining = clean_text(remaining[cut:])
        if remaining:
            expanded_sentences.append(remaining)

    paragraphs = []
    current = []
    for sentence in expanded_sentences:
        candidate = clean_text(" ".join([*current, sentence]))
        if current and len(candidate) > target_chars:
            paragraphs.append(clean_text(" ".join(current)))
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        paragraphs.append(clean_text(" ".join(current)))
    return paragraphs


def reference_chunks_to_reading_segments(chunks, target_chars=READING_SEGMENT_TARGET_CHARS):
    segments = []
    for chunk in chunks:
        paragraphs = split_reading_paragraphs(chunk.get("text", ""), target_chars=target_chars)
        total_chars = sum(max(1, len(item)) for item in paragraphs)
        cursor = float(chunk["start"])
        chunk_end = float(chunk["end"])
        for paragraph_index, paragraph in enumerate(paragraphs):
            fraction = max(1, len(paragraph)) / max(1, total_chars)
            end = chunk_end if paragraph_index == len(paragraphs) - 1 else cursor + (
                (chunk_end - float(chunk["start"])) * fraction
            )
            segments.append(
                {
                    "id": len(segments),
                    "start": round(cursor, 3),
                    "end": round(max(cursor + 0.001, end), 3),
                    "text": paragraph,
                    "source": "gpt-transcribe-reading-layout",
                    "timingQuality": "synthetic_not_for_subtitles",
                }
            )
            cursor = end
    return segments


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


def correct_english(
    api_key,
    segments,
    gpt4o_chunks,
    outdir,
    model,
    glossary,
    window_seconds,
    reasoning_effort=None,
):
    output = outdir / "segments_timed_en_corrected.json"
    version_file = outdir / "english_correction_prompt.json"
    version = {
        "promptVersion": review_prompts.ENGLISH_CORRECTION_PROMPT_VERSION,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "inputSha256": json_sha256(
            {
                "segments": segments,
                "referenceChunks": gpt4o_chunks,
                "glossary": glossary,
            }
        ),
    }
    if output.exists() and version_file.exists() and read_json(version_file) == version:
        return read_json(output)

    corrected = []
    windows_dir = outdir / "correction_windows"
    cache_identity = hashlib.sha256(
        f"{review_prompts.ENGLISH_CORRECTION_PROMPT_VERSION}|{model}|{reasoning_effort}".encode("utf-8")
    ).hexdigest()[:12]
    glossary_text = glossary_lines(glossary)
    start_index = 0
    while start_index < len(segments):
        window_start = segments[start_index]["start"]
        window_end = window_start + window_seconds
        end_index = start_index
        while end_index < len(segments) and segments[end_index]["start"] < window_end:
            end_index += 1
        batch = segments[start_index:end_index]
        window_input_hash = json_sha256(
            {
                "batch": batch,
                "reference": chunk_text_for_window(
                    gpt4o_chunks,
                    batch[0]["start"],
                    batch[-1]["end"],
                ),
                "glossary": glossary,
            }
        )[:12]
        cache = windows_dir / (
            f"window_{batch[0]['id']:04d}_{batch[-1]['id']:04d}."
            f"{cache_identity}.{window_input_hash}.json"
        )
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
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": review_prompts.ENGLISH_CORRECTION_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": (
                            "<glossary>\n"
                            + glossary_text
                            + "\n</glossary>\n<reference_transcript>\n"
                            + reference
                            + "\n</reference_transcript>\n<timed_segments>\n"
                            + json.dumps(
                                [{"id": s["id"], "text": s["text"]} for s in batch],
                                ensure_ascii=False,
                            )
                            + "\n</timed_segments>"
                        ),
                    },
                ],
            }
            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort
            result = chat_json(api_key, payload)
            parsed = json.loads(result["choices"][0]["message"]["content"])
            parsed["_model"] = result.get("model", model)
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
            corrected.append(
                {
                    **seg,
                    "text": text,
                    "correction_model": parsed.get("_model", model),
                    "correction_prompt_version": review_prompts.ENGLISH_CORRECTION_PROMPT_VERSION,
                }
            )
        print(f"corrected {len(corrected)}/{len(segments)}", flush=True)
        start_index = end_index
    write_json(output, corrected)
    write_json(version_file, version)
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
        joiner = ""
        if not (
            re.search(r"[\u3400-\u9fff\uf900-\ufaff]$", lines[-1])
            and re.match(r"^[\u3400-\u9fff\uf900-\ufaff]", remaining)
        ):
            joiner = " "
        lines[-1] = clean_text(lines[-1] + joiner + remaining)
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


def translate_chinese(
    api_key,
    segments,
    outdir,
    model,
    glossary,
    reasoning_effort=None,
    workers=1,
):
    output = outdir / "segments_timed_zh.json"
    version_file = outdir / "chinese_translation_prompt.json"
    version = {
        "promptVersion": review_prompts.CHINESE_TRANSLATION_PROMPT_VERSION,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "inputSha256": json_sha256({"segments": segments, "glossary": glossary}),
    }
    if output.exists() and version_file.exists() and read_json(version_file) == version:
        return read_json(output)
    glossary_text = glossary_lines(glossary)
    system = review_prompts.CHINESE_TRANSLATION_SYSTEM_PROMPT
    cache_identity = hashlib.sha256(
        f"{review_prompts.CHINESE_TRANSLATION_PROMPT_VERSION}|{model}|{reasoning_effort}".encode("utf-8")
    ).hexdigest()[:12]
    def translate_one(item):
        idx, seg = item
        segment_input_hash = json_sha256(
            {
                "segment": seg,
                "previous": segments[idx - 1]["text"] if idx > 0 else "",
                "next": segments[idx + 1]["text"] if idx + 1 < len(segments) else "",
                "glossary": glossary,
            }
        )[:12]
        cache = outdir / "translation_segments" / (
            f"seg_{seg['id']:04d}.{cache_identity}.{segment_input_hash}.json"
        )
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
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            "<glossary>\n"
                            + glossary_text
                            + "\n</glossary>\n<context>\n"
                            + json.dumps(context, ensure_ascii=False)
                            + "\n</context>"
                        ),
                    },
                ],
            }
            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort
            result = chat_json(api_key, payload)
            parsed = json.loads(result["choices"][0]["message"]["content"])
            parsed["_model"] = result.get("model", model)
            write_json(cache, parsed)
        if parsed.get("id") != seg["id"]:
            raise RuntimeError(f"Chinese translation id mismatch for segment {seg['id']}")
        zh = normalize_zh_terms(clean_text(parsed.get("zh", "")), glossary)
        if not zh:
            raise RuntimeError(f"Empty Chinese translation for segment {seg['id']}")
        return {
            **seg,
            "zh": zh,
            "translation_model": parsed.get("_model", model),
            "translation_prompt_version": review_prompts.CHINESE_TRANSLATION_PROMPT_VERSION,
        }

    translated = []
    items = list(enumerate(segments))
    if workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            results = executor.map(translate_one, items)
            for idx, translated_segment in enumerate(results):
                translated.append(translated_segment)
                if (idx + 1) % 25 == 0 or idx + 1 == len(segments):
                    print(f"translated zh {idx + 1}/{len(segments)}", flush=True)
    else:
        for idx, item in enumerate(items):
            translated.append(translate_one(item))
            if (idx + 1) % 25 == 0 or idx + 1 == len(segments):
                print(f"translated zh {idx + 1}/{len(segments)}", flush=True)
    write_json(output, translated)
    write_json(version_file, version)
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
    parser.add_argument(
        "--reference-model",
        "--gpt4o-model",
        dest="reference_model",
        default="gpt-transcribe",
    )
    parser.add_argument("--timing-model", default="whisper-1")
    parser.add_argument("--output-mode", choices=("reading", "subtitles"), default="reading")
    parser.add_argument("--en-correction-model", default="gpt-5.6")
    parser.add_argument("--zh-model", default="gpt-5.6")
    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        default="high",
        help="Reasoning effort for English correction and Chinese translation models.",
    )
    parser.add_argument(
        "--translation-workers",
        type=int,
        default=1,
        help="Concurrent per-segment translation requests. Use conservatively to respect rate limits.",
    )
    parser.add_argument("--chunk-seconds", type=float, default=45.0)
    parser.add_argument("--reading-chunk-seconds", type=float, default=1200.0)
    parser.add_argument(
        "--reading-segment-target-chars",
        type=int,
        default=READING_SEGMENT_TARGET_CHARS,
        help="Target English characters per paired reading segment.",
    )
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
    if end is not None and abs(clip_duration - (end - start)) > 2.0:
        raise RuntimeError(
            f"Source clip duration mismatch: expected {end - start:.3f}s, got {clip_duration:.3f}s"
        )

    reference_chunk_seconds = args.reading_chunk_seconds if args.output_mode == "reading" else args.chunk_seconds
    reference_chunks = transcribe_reference(
        api_key,
        clip_path,
        outdir,
        reference_chunk_seconds,
        args.reference_model,
        glossary,
    )
    if args.output_mode == "reading":
        raw_segments = reference_chunks_to_reading_segments(
            reference_chunks,
            target_chars=max(120, args.reading_segment_target_chars),
        )
    else:
        whisper_raw = transcribe_whisper(api_key, clip_path, outdir, args.timing_model, glossary)
        raw_segments = normalize_whisper_segments(whisper_raw)
    if not raw_segments:
        raise RuntimeError(f"{args.reference_model} returned no usable sermon transcript")
    write_json(outdir / "segments_timed_en_raw.json", raw_segments)

    if args.output_mode == "reading":
        corrected = raw_segments
    else:
        corrected = correct_english(
            api_key,
            raw_segments,
            reference_chunks,
            outdir,
            args.en_correction_model,
            glossary,
            args.correction_window_seconds,
            reasoning_effort=args.reasoning_effort,
        )
    shaped_en = corrected if args.output_mode == "reading" else shape_durations(corrected)
    write_json(outdir / "segments_timed_en_corrected.json", shaped_en)

    translated = translate_chinese(
        api_key,
        shaped_en,
        outdir,
        args.zh_model,
        glossary,
        reasoning_effort=args.reasoning_effort,
        workers=max(1, args.translation_workers),
    )
    shaped_zh = translated if args.output_mode == "reading" else shape_durations(translated)
    write_json(outdir / "segments_timed_zh.json", shaped_zh)

    if args.output_mode == "subtitles":
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
            "referenceAsr": args.reference_model,
            "timingAsr": args.timing_model if args.output_mode == "subtitles" else None,
            "englishCorrection": args.en_correction_model if args.output_mode == "subtitles" else None,
            "chineseTranslation": args.zh_model,
            "reasoningEffort": args.reasoning_effort,
            "translationWorkers": max(1, args.translation_workers),
            "promptVersions": {
                "englishCorrection": review_prompts.ENGLISH_CORRECTION_PROMPT_VERSION,
                "chineseTranslation": review_prompts.CHINESE_TRANSLATION_PROMPT_VERSION,
            },
        },
        "outputMode": args.output_mode,
        "timingPrecision": "whisper_segments" if args.output_mode == "subtitles" else "synthetic_reading_layout_only",
        "readingSegmentTargetCharacters": (
            max(120, args.reading_segment_target_chars) if args.output_mode == "reading" else None
        ),
        "segmentCount": len(shaped_zh),
        "qaHardFailures": qa["hardFailures"],
        "outputs": (
            [
                "sermon_en_relative.srt",
                "sermon_zh_relative.srt",
                "full_video_en_from_sermon.srt",
                "full_video_zh_from_sermon.srt",
                "qa_report.json",
            ]
            if args.output_mode == "subtitles"
            else [
                "asr_reference.json",
                "asr_reference_chunks.json",
                "segments_timed_en_corrected.json",
                "segments_timed_zh.json",
                "qa_report.json",
            ]
        ),
        "argv": sys.argv[1:],
    }
    write_json(outdir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
