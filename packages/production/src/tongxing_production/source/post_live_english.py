"""Layer 1 English facts the post-live pipeline produces: OpenAI reference transcription
and its cache, English correction, MFA options and the source fingerprint precompute.

Moved out of the dual_pdf pipeline (workflows/compute W3b, design section 6 item 2)
because their outputs, such as ``segments_timed_en_corrected.json``, are Layer 1 inputs.
The small file helpers they share with the dual_pdf code moved with them; the dual_pdf
pipeline imports them back under the same names.
"""
import concurrent.futures
from contextvars import copy_context
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from . import backend as _source
from . import review_prompts
from ..compute import spark_admission  # noqa: F401
from ..compute.legacy_openai import (
    TRANSCRIBE_URL, bounded_legacy_chat_payload, chat_json, legacy_text_cache_contract,
    legacy_text_execution_identity, multipart_request)


# The run's accounting session lives in the checkout until observability moves
# (infrastructure I3); it resolves through this layer's port at call time.
def stage(name, **options):
    return _source.current().accounting.stage(name, **options)


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


def clean_text(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


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
    if isinstance(glossary, dict) and glossary.get("seriesTerminology"):
        lines.append("Contextual series naming rules and data (not a global replacement map):")
        lines.append(json.dumps(glossary["seriesTerminology"], ensure_ascii=False))
    return "\n".join(lines)


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
        result = read_json(result_path)
        with stage("transcription.cache", cache_hit=True):
            return result
    except (OSError, json.JSONDecodeError):
        return None


def write_transcription_cache(result_path, metadata_path, result, identity):
    write_json(result_path, result)
    write_json(metadata_path, identity)


def media_cache_metadata_path(path):
    return path.with_suffix(path.suffix + ".cache.json")


def source_file_identity(path, *, include_sha256=False):
    stat = path.stat()
    identity = {
        "sizeBytes": stat.st_size,
        "modifiedTimeNs": stat.st_mtime_ns,
    }
    if include_sha256:
        identity["sha256"] = file_sha256(path)
    return identity


def cached_media_matches(path, identity):
    metadata_path = media_cache_metadata_path(path)
    if not path.exists() or not metadata_path.exists():
        return False
    try:
        return read_json(metadata_path) == identity
    except (OSError, json.JSONDecodeError):
        return False


def cut_chunk(source, dest, start, duration):
    identity = {
        "schemaVersion": 1,
        "operation": "cut_chunk",
        "source": source_file_identity(source),
        "startSeconds": round(float(start), 3),
        "durationSeconds": round(float(duration), 3),
        "codec": "aac",
        "sampleRate": 44100,
        "channels": 1,
        "bitrate": "64k",
    }
    if cached_media_matches(dest, identity):
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
    if dest.exists():
        write_json(media_cache_metadata_path(dest), identity)


def transcribe_openai_audio(
    api_key,
    model,
    prompt,
    audio_path,
    *,
    keywords=None,
    languages=None,
    response_format="json",
    session_verifier=None,
):
    return spark_admission.SessionBoundCaller(multipart_request, verifier=session_verifier,
        purpose="source-audio-api", requires_spark=False)(
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


def transcribe_reference_chunks(api_key, clip_path, outdir, chunk_seconds, model, glossary, workers=2):
    if not 1 <= workers <= 8:
        raise ValueError("ASR workers must be between 1 and 8")
    if chunk_seconds <= 0:
        raise ValueError("ASR chunk seconds must be positive")
    output = outdir / "asr_reference_chunks.json"
    duration = ffprobe_duration(clip_path)
    chunks_dir = outdir / "chunks_reference"
    chunks = []
    prompt = reference_transcription_prompt(glossary)
    keywords = reference_transcription_keywords(glossary)
    languages = DEFAULT_TRANSCRIPTION_LANGUAGES
    chunk_count = int((duration + chunk_seconds - 0.001) // chunk_seconds)
    def transcribe_one(index):
        start = index * chunk_seconds
        length = min(chunk_seconds, duration - start)
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
        chunk = {
                "id": index,
                "start": round(start, 3),
                "end": round(start + length, 3),
                "duration": round(length, 3),
                "text": clean_text(result.get("text", "")),
                "usage": result.get("usage"),
                "detectedLanguages": result.get("languages", []),
            }
        print(f"{model} reference chunk {index + 1}/{chunk_count}", flush=True)
        return chunk

    # Each worker owns one media/cache path; only the coordinator freezes the aggregate.
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(copy_context().run, transcribe_one, i) for i in range(chunk_count)]
        try:
            chunks = [future.result() for future in futures]
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    write_json(output, chunks)
    return chunks


def transcribe_reference(api_key, clip_path, outdir, chunk_seconds, model, glossary, workers=2):
    if clip_path.stat().st_size > MAX_SINGLE_TRANSCRIPTION_BYTES:
        return transcribe_reference_chunks(
            api_key,
            clip_path,
            outdir,
            chunk_seconds,
            model,
            glossary,
            workers=workers,
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
                workers=workers,
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


def chunk_text_for_window(chunks, start, end):
    parts = []
    for chunk in chunks:
        if chunk["end"] >= start - 20 and chunk["start"] <= end + 20 and chunk["text"]:
            parts.append(f"[{chunk['start']:.1f}-{chunk['end']:.1f}] {chunk['text']}")
    return "\n".join(parts)


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
    reasoning_effort = reasoning_effort or "high"
    aggregate_execution=legacy_text_execution_identity(api_key,{
        'model':model,'reasoning_effort':reasoning_effort,'response_format':{'type':'json_object'},
        'messages':[{'role':'user','content':'aggregate execution binding'}]})['executionBinding']
    output = outdir / "segments_timed_en_corrected.json"
    version_file = outdir / "english_correction_prompt.json"
    version = {
        "promptVersion": review_prompts.ENGLISH_CORRECTION_PROMPT_VERSION,
        "cacheContract": legacy_text_cache_contract(),
        "executionIdentity":aggregate_execution,
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
        with stage("english_correction.cache", cache_hit=True):
            return read_json(output)

    corrected = []
    windows_dir = outdir / "correction_windows"
    cache_identity = hashlib.sha256(
        json.dumps({"promptVersion": review_prompts.ENGLISH_CORRECTION_PROMPT_VERSION, "model": model,
                    "reasoningEffort": reasoning_effort, "cacheContract": legacy_text_cache_contract(),"executionIdentity":aggregate_execution}, sort_keys=True).encode("utf-8")
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
        payload["reasoning_effort"] = reasoning_effort or "high"
        payload = bounded_legacy_chat_payload(payload)
        execution=legacy_text_execution_identity(api_key,payload)
        window_input_hash = json_sha256(
            {
                "batch": batch,
                "boundedPayload": payload,
                "executionIdentity":execution,
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


def mfa_options(args):
    return {
        "mfa_executable": getattr(args, "mfa_executable", os.environ.get("MFA_EXECUTABLE", "mfa")),
        "dictionary_path": getattr(args, "mfa_dictionary", None) or os.environ.get("MFA_DICTIONARY"),
        "acoustic_model": getattr(args, "mfa_acoustic_model", None) or os.environ.get("MFA_ACOUSTIC_MODEL"),
        "g2p_model": getattr(args, "mfa_g2p_model", None) or os.environ.get("MFA_G2P_MODEL"),
        "spoken_forms_path": getattr(args, "mfa_spoken_forms", None) or os.environ.get("MFA_SPOKEN_FORMS"),
    }


def precompute_source_fingerprint(source, start, end, outdir):
    """Only source landmarks: final page/Chinese-track binding is a later stage."""
    subprocess_environment = _source.current().accounting.subprocess_environment
    node = shutil.which("node")
    if not node or not shutil.which("ffmpeg"):
        raise RuntimeError("Fingerprint precompute requires node and ffmpeg")
    script = _source.current().core.repo_root / "packages" / "fingerprint" / "bin" / "build_fingerprint_index.mjs"
    identity = {"sourceSha256": file_sha256(source), "sourceStartSeconds": start,
                "sourceEndSeconds": end, "scriptSha256": file_sha256(script),
                "algorithmSha256": file_sha256(script.parents[1] / "src" / "fingerprint-core.mjs")}
    root = outdir / "source-fingerprint" / json_sha256(identity)
    root.mkdir(parents=True, exist_ok=True)
    receipt_path = root / "receipt.json"
    with stage("pipeline.source_fingerprint"):
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            cached = Path(receipt["path"])
            if receipt.get("identity") == identity and cached.is_file() and file_sha256(cached) == receipt.get("sha256"):
                return receipt
        output = root / (uuid.uuid4().hex + ".json")
        result = subprocess.run([node, str(script), "--mode", "precompute", "--source", str(source),
                                 "--source-sha", identity["sourceSha256"], "--start", str(start), "--end", str(end),
                                 "--out", str(output)], check=True, capture_output=True, text=True,
                                env=subprocess_environment(), timeout=1800)
        receipt = {**json.loads(result.stdout), "identity": identity, "finalTrackBound": False}
        if receipt.get("sha256") != file_sha256(output):
            raise RuntimeError("Fingerprint precompute receipt hash mismatch")
        write_json(receipt_path, receipt)
        return receipt
