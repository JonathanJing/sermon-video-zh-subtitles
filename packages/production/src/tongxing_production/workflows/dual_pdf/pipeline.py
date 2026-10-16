#!/usr/bin/env python3
"""Hybrid OpenAI pipeline for weekly offline sermon subtitle files."""

import argparse
import concurrent.futures
from contextvars import copy_context
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from ...source import backend as _source
from ...source import review_prompts
# Fixed pre-dispatch guard codes (see PreDispatchRejection), shared with accounting.
from ...contracts.reasons import PRE_DISPATCH_REASONS  # noqa: F401
from ...compute import spark_admission  # noqa: F401


# The run's accounting session lives in the checkout until observability moves
# (infrastructure I3); these names resolve through the source layer's port at call time.
def accounting_session(directory, workflow, metadata=None, **options):
    return _source.current().accounting.session(directory, workflow, metadata, **options)


def stage(name, **options):
    return _source.current().accounting.stage(name, **options)


def record_workload(name, values):
    return _source.current().accounting.record_workload(name, values)


# The remote-call group lives in tongxing_production.compute.legacy_openai (workflows/compute C4);
# the dual_pdf code below and every existing caller keep using these names.
from ...compute.legacy_openai import (  # noqa: E402,F401
    CHAT_URL, KNOWN_REQUEST_REJECTIONS, LEGACY_TEXT_CACHE_SCHEMA, TRANSCRIBE_URL, PreDispatchRejection,
    TransportRejection, _chat_json, _http_error_diagnostic, bounded_legacy_chat_payload, chat_json,
    json_request, legacy_text_cache_contract, legacy_text_execution_identity, multipart_request, request_json)

# Layer 1 English facts and the file helpers they share live in
# tongxing_production.source.post_live_english (W3b); the dual_pdf code below keeps these names.
from ...source.post_live_english import (  # noqa: E402,F401
    DEFAULT_TRANSCRIPTION_LANGUAGES, DEFAULT_ZH_TERM_MAP, GPT_TRANSCRIBE_MODELS, MAX_SINGLE_TRANSCRIPTION_BYTES, cached_media_matches,
    chunk_text_for_window, clean_text, correct_english, cut_chunk, ffprobe_duration,
    file_sha256, glossary_lines, glossary_prompt, glossary_terms, is_gpt_transcribe_model,
    json_sha256, media_cache_metadata_path, mfa_options, normalized_transcription_keywords, precompute_source_fingerprint,
    read_json, read_transcription_cache, reencode_transcription_fallback, reference_transcription_keywords, reference_transcription_prompt,
    run, same_ids, source_file_identity, transcribe_gpt4o_chunks, transcribe_openai_audio,
    transcribe_reference, transcribe_reference_chunks, transcribe_whisper, transcription_cache_identity, transcription_request_fields,
    write_json, write_transcription_cache, zh_term_map)

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


READING_SEGMENT_TARGET_CHARS = 420


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


def load_glossary(path):
    payload = {"terms": DEFAULT_GLOSSARY, "zh_term_map": DEFAULT_ZH_TERM_MAP.copy(),
               "seriesTerminology": _source.current().terminology.context()}
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
    identity = {
        "schemaVersion": 1,
        "operation": "clip_and_normalize",
        "source": source_file_identity(source, include_sha256=True),
        "startSeconds": round(float(start), 3),
        "endSeconds": round(float(end), 3) if end is not None else None,
        "audioFilter": "loudnorm=I=-16:TP=-1.5:LRA=11",
        "codec": "aac",
        "sampleRate": 44100,
        "channels": 1,
        "bitrate": "64k",
    }
    if cached_media_matches(clip_path, identity):
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
    if clip_path.exists():
        write_json(media_cache_metadata_path(clip_path), identity)


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
    reasoning_effort = reasoning_effort or "high"
    aggregate_execution=legacy_text_execution_identity(api_key,{
        'model':model,'reasoning_effort':reasoning_effort,'response_format':{'type':'json_object'},
        'messages':[{'role':'user','content':'aggregate execution binding'}]})['executionBinding']
    record_workload("pipeline.translate", {"inputSegments": len(segments), "inputCharacters": sum(len(x.get("text", "")) for x in segments), "workers": workers})
    output = outdir / "segments_timed_zh.json"
    version_file = outdir / "chinese_translation_prompt.json"
    version = {
        "promptVersion": review_prompts.CHINESE_TRANSLATION_PROMPT_VERSION,
        "cacheContract": legacy_text_cache_contract(),
        "executionIdentity":aggregate_execution,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "inputSha256": json_sha256({"segments": segments, "glossary": glossary}),
    }
    if output.exists() and version_file.exists() and read_json(version_file) == version:
        with stage("translation.cache", cache_hit=True):
            return read_json(output)
    glossary_text = glossary_lines(glossary)
    system = (review_prompts.CHINESE_TRANSLATION_SYSTEM_PROMPT + "\n"
              + _source.current().terminology.prompt_instruction())
    cache_identity = hashlib.sha256(
        json.dumps({"promptVersion": review_prompts.CHINESE_TRANSLATION_PROMPT_VERSION, "model": model,
                    "reasoningEffort": reasoning_effort, "cacheContract": legacy_text_cache_contract(),"executionIdentity":aggregate_execution}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    def translate_one(item):
        idx, seg = item
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
        payload["reasoning_effort"] = reasoning_effort or "high"
        payload = bounded_legacy_chat_payload(payload)
        execution=legacy_text_execution_identity(api_key,payload)
        segment_input_hash = json_sha256(
            {
                "segment": seg,
                "boundedPayload": payload,
                "executionIdentity":execution,
                "previous": segments[idx - 1]["text"] if idx > 0 else "",
                "next": segments[idx + 1]["text"] if idx + 1 < len(segments) else "",
                "glossary": glossary,
            }
        )[:12]
        cache = outdir / "translation_segments" / (
            f"seg_{seg['id']:04d}.{cache_identity}.{segment_input_hash}.json"
        )
        if cache.exists():
            with stage("translation.segment_cache", cache_hit=True):
                parsed = read_json(cache)
        else:
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
            futures = [executor.submit(copy_context().run, translate_one, item) for item in items]
            results = (future.result() for future in futures)
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
    parser.add_argument(
        "--english-source-only", action="store_true",
        help="Stop after frozen English transcription and word alignment; do not translate.",
    )
    parser.add_argument(
        "--english-transcript-only", action="store_true",
        help="Freeze English ASR before alignment when the MFA runtime is unavailable; do not translate.",
    )
    parser.add_argument("--en-correction-model", default="gpt-6.1-sol")
    parser.add_argument("--zh-model", default="gpt-6.1-sol")
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
    parser.add_argument("--fingerprint-precompute", action="store_true",
                        default=os.environ.get("SERMON_FINGERPRINT_PRECOMPUTE") == "1")
    parser.add_argument("--asr-workers", type=int, choices=range(1, 9), default=2,
                        help="Concurrent independent ASR chunks; full-file requests remain single calls.")
    parser.add_argument("--chunk-seconds", type=float, default=45.0)
    parser.add_argument("--reading-chunk-seconds", type=float, default=1200.0)
    parser.add_argument("--reading-aligner", choices=("mfa", "legacy"), default="mfa",
                        help="MFA word/phone timing for reading production; legacy is explicit historical recovery only.")
    from ...source.mfa_spark import add_arguments
    add_arguments(parser)
    from ...source.mfa_backend import add_arguments as add_backend_arguments
    add_backend_arguments(parser)
    parser.add_argument("--mfa-executable", default=os.environ.get("MFA_EXECUTABLE", "mfa"))
    parser.add_argument("--mfa-dictionary", type=Path, default=os.environ.get("MFA_DICTIONARY"))
    parser.add_argument("--mfa-acoustic-model", type=Path, default=os.environ.get("MFA_ACOUSTIC_MODEL"))
    parser.add_argument("--mfa-g2p-model", type=Path, default=os.environ.get("MFA_G2P_MODEL"))
    parser.add_argument("--mfa-spoken-forms", type=Path, default=os.environ.get("MFA_SPOKEN_FORMS"))
    parser.add_argument("--source-text-review", type=Path, help="Hash-bound, separately reviewed English source corrections; original ASR stays unchanged.")
    parser.add_argument("--source-text-review-package", type=Path,
                        help="Directory with the source.json and anchor.json a machine audio adjudication review's receipt adjudicated; required for that authority.")
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
    if args.source_text_review and args.output_mode != "reading":
        raise SystemExit("--source-text-review currently requires --output-mode reading")
    if args.english_source_only and (args.output_mode != "reading" or args.reading_aligner != "mfa"):
        raise SystemExit("--english-source-only requires --output-mode reading --reading-aligner mfa")
    if args.english_transcript_only and (args.output_mode != "reading" or args.english_source_only):
        raise SystemExit("--english-transcript-only requires reading mode and excludes --english-source-only")
    if args.english_transcript_only and args.source_text_review:
        raise SystemExit("--source-text-review requires word alignment; rerun with --english-source-only")

    load_env(Path(".env"))
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set")

    source_duration = ffprobe_duration(args.input)
    start = parse_timecode(args.start_time)
    end = parse_timecode(args.end_time) if args.end_time else source_duration
    outdir = make_outdir(args.artifacts_root, args.slug, args.outdir)
    with accounting_session(outdir / "accounting", "sermon_pipeline"):
        return produce_pipeline(args, api_key, source_duration, start, end, outdir)


def reading_segments(args, chunks, clip_path, outdir):
    if getattr(args, "reading_aligner", "mfa") == "legacy":
        return reference_chunks_to_reading_segments(
            chunks, target_chars=max(120, args.reading_segment_target_chars))
    return align_reading_chunks(args, chunks, clip_path, outdir / "mfa")


def align_reading_chunks(args, chunks, clip_path, outdir):
    from ...source.mfa_backend import align_reference_chunks, options
    result = align_reference_chunks(chunks, clip_path, outdir, **options(args))
    receipt = outdir / "backend.json"
    if receipt.is_file():
        args._mfa_runtime = json.loads(receipt.read_text())
    return result


def transcribe_with_fingerprint(args, api_key, clip_path, outdir, chunk_seconds, glossary, start, end):
    def transcribe():
        with stage("pipeline.transcribe", billing="api"):
            return transcribe_reference(api_key, clip_path, outdir, chunk_seconds, args.reference_model,
                                        glossary, workers=getattr(args, "asr_workers", 2))
    if not getattr(args, "fingerprint_precompute", False):
        return transcribe(), None
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        fingerprint = executor.submit(copy_context().run, precompute_source_fingerprint,
                                      args.input, start, end, outdir)
        chunks = transcribe()
        return chunks, fingerprint.result()


def produce_pipeline(args, api_key, source_duration, start, end, outdir):
    glossary = load_glossary(args.glossary)
    if (args.output_mode == "reading" and getattr(args, "reading_aligner", "mfa") == "mfa"
            and not args.english_transcript_only):
        from ...source.mfa_backend import preflight, options
        args._mfa_runtime = preflight(**options(args))
    source_identity = None
    if args.english_source_only or args.english_transcript_only:
        source_identity = {
            "sha256": file_sha256(args.input),
            "sizeBytes": args.input.stat().st_size,
        }

    clip_path = outdir / "source_clip.m4a"
    with stage("pipeline.clip", billing="local"):
        clip_and_normalize(args.input, clip_path, start, end)
        clip_duration = ffprobe_duration(clip_path)
        if end is not None and abs(clip_duration - (end - start)) > 2.0:
            raise RuntimeError(
                f"Source clip duration mismatch: expected {end - start:.3f}s, got {clip_duration:.3f}s"
            )

    reference_chunk_seconds = args.reading_chunk_seconds if args.output_mode == "reading" else args.chunk_seconds
    reference_chunks, fingerprint_receipt = transcribe_with_fingerprint(
        args, api_key, clip_path, outdir, reference_chunk_seconds, glossary, start,
        end if end is not None else source_duration,
    )
    if args.english_transcript_only:
        if (file_sha256(args.input) != source_identity["sha256"]
                or args.input.stat().st_size != source_identity["sizeBytes"]):
            raise RuntimeError("Source media changed during English transcription")
        if not reference_chunks:
            raise RuntimeError("English transcription returned no chunks")
        summary = {
            "status": "english_transcript_candidate",
            "source": str(args.input),
            "sourceDurationSeconds": source_duration,
            "sourceClip": str(clip_path),
            "clipDurationSeconds": clip_duration,
            "sermonStartSeconds": start,
            "sermonEndSeconds": end,
            "models": {"referenceAsr": args.reference_model},
            "pipelineInputIdentity": {"sourceAudio": source_identity},
            "asrChunkCount": len(reference_chunks),
            "asrChunkJsonSha256": json_sha256(reference_chunks),
            "alignmentStatus": "pending_mfa",
            "humanReview": "pending",
            "outputs": ["asr_reference.json", "asr_reference_chunks.json"],
            "argv": sys.argv[1:],
        }
        write_json(outdir / "transcript-only-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    with stage("pipeline.segment", billing="local"):
        if args.output_mode == "reading":
            raw_segments = reading_segments(args, reference_chunks, clip_path, outdir)
        else:
            whisper_raw = transcribe_whisper(api_key, clip_path, outdir, args.timing_model, glossary)
            raw_segments = normalize_whisper_segments(whisper_raw)
    if not raw_segments:
        raise RuntimeError(f"{args.reference_model} returned no usable sermon transcript")
    write_json(outdir / "segments_timed_en_raw.json", raw_segments)

    with stage("pipeline.source_review", billing="local" if args.english_source_only else
               "api"):
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
        source_review = None
        if args.source_text_review:
            from ...source.text_review import apply_review
            asr_path = outdir / "asr_reference.json"
            if not asr_path.exists():
                asr_path = outdir / "asr_reference_chunks.json"
            package_dir = getattr(args, "source_text_review_package", None)
            adjudicated_package = None
            if package_dir:
                # The adjudicated package and the parent media bind a machine receipt to what is being corrected.
                adjudicated_package = {
                    name: json.loads((Path(package_dir) / f"{name}.json").read_text(encoding="utf-8"))
                    for name in ("source", "anchor")}
                adjudicated_package["mediaSha256"] = file_sha256(args.input)
            corrected, source_review = apply_review(corrected, args.source_text_review, clip_path, asr_path,
                                                    adjudicated_package=adjudicated_package)
            write_json(outdir / "source-text-review-provenance.json", source_review)
            if getattr(args, "reading_aligner", "mfa") == "mfa":
                # Text edits invalidate old word/phone times; realign the reviewed words.
                corrected = align_reading_chunks(
                    args, corrected, clip_path, outdir / "mfa-reviewed")
        shaped_en = corrected if args.output_mode == "reading" else shape_durations(corrected)
        write_json(outdir / "segments_timed_en_corrected.json", shaped_en)

    if args.english_source_only:
        if (file_sha256(args.input) != source_identity["sha256"]
                or args.input.stat().st_size != source_identity["sizeBytes"]):
            raise RuntimeError("Source media changed during English transcription or alignment")
        summary = {
            "status": "english_source_candidate",
            "source": str(args.input),
            "sourceDurationSeconds": source_duration,
            "sourceClip": str(clip_path),
            "clipDurationSeconds": clip_duration,
            "sermonStartSeconds": start,
            "sermonEndSeconds": end,
            "models": {"referenceAsr": args.reference_model},
            "outputMode": args.output_mode,
            "readingAligner": args.reading_aligner,
            "readingAlignmentBackend": getattr(args, "_mfa_runtime", {}).get("backend"),
            "readingAlignmentRuntime": getattr(args, "_mfa_runtime", None),
            "timingPrecision": "mfa_word_aligned",
            "pipelineInputIdentity": {"sourceAudio": source_identity, "readingAligner": args.reading_aligner},
            "segmentCount": len(shaped_en),
            "outputs": ["asr_reference.json", "asr_reference_chunks.json", "segments_timed_en_corrected.json"],
            "argv": sys.argv[1:],
        }
        if source_review:
            summary["sourceTextReview"] = source_review
        write_json(outdir / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    with stage("pipeline.translate", billing="api"):
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
        "readingAligner": getattr(args, "reading_aligner", "mfa") if args.output_mode == "reading" else None,
        "sourceFingerprintPrecompute": fingerprint_receipt,
        "readingAlignmentBackend": getattr(args, "_mfa_runtime", {}).get("backend"),
        "readingAlignmentRuntime": getattr(args, "_mfa_runtime", None),
        "timingPrecision": ("whisper_segments" if args.output_mode == "subtitles" else
                            "mfa_word_aligned" if getattr(args, "reading_aligner", "mfa") == "mfa" else
                            "synthetic_reading_layout_only"),
        "seriesTerminology": glossary["seriesTerminology"],
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
    if source_review:
        summary["sourceTextReview"] = source_review
    write_json(outdir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
