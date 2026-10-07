#!/usr/bin/env python3
"""Back-transcribe every formal Layer 3 unit without granting human approval.

The renderer's original manifest remains immutable. This command writes a
separate ASR receipt and a screened manifest only after binding every unit to
the exact approved speech job and audio bytes. Uncertain ASR output stays in a
review queue; it cannot be promoted to a machine pass by a coverage count.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
import tempfile
from typing import Callable

try:
    from scripts import prepare_target_language_speech_job as speech
    from scripts import sermon_sentence_interpretation as identity
    from scripts import dev_audio_test_profile as dev_profile
    from scripts import dev_audio_test_receipts as dev_receipts
except ImportError:
    import prepare_target_language_speech_job as speech
    import sermon_sentence_interpretation as identity
    import dev_audio_test_profile as dev_profile
    import dev_audio_test_receipts as dev_receipts


# v2 records the ASR runtime settings behind every score (v1 receipts stay readable).
SCHEMA = "sermon-target-language-audio-screening-v2"
# How a recognized text is scored against the expected text; part of the recorded runtime.
SCORING = ("token-sequence-ratio-v3; short units (<4 tokens) must match exactly; "
           "no negation, number or protected name may differ; numbers and names keep their order")
MODEL = "Qwen/Qwen3-ASR-0.6B"
BATCH_SIZES = (1, 2, 4, 8)


def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    try:
        # Publish a new immutable cache receipt, never replace a concurrent one.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tokens(value: str, locale: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", value).casefold()
    if locale in {"zh-Hans", "ko"}:
        return [char for char in folded if char.isalnum()]
    return re.findall(r"[^\W_]+", folded, flags=re.UNICODE)


# A dub that drops or changes one of these reverses or alters its claim while
# the token ratio stays high ("not" in 13 words still scores 0.96), so an ASR
# difference that touches one never passes on the ratio alone.
NEGATIONS = {"en": ("no", "not", "never", "neither", "nor", "without", "cannot"),
             "zh-Hans": ("不", "没", "沒", "别", "未", "非", "无", "勿", "否"),
             "ko": ("아니", "않", "안", "못", "없"),
             "es": ("no", "ni", "nunca", "jamás", "jamas", "tampoco", "nadie", "nada", "ningún", "ningun",
                    "ninguno", "ninguna", "sin")}
ZH_NUMERALS = "〇零一二两三四五六七八九十百千万亿"
ES_NUMBERS = frozenset((
    "cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
    "trece", "catorce", "quince", "dieciséis", "dieciseis", "diecisiete", "dieciocho", "diecinueve", "veinte",
    "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa", "cien", "ciento",
    "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos", "ochocientos",
    "novecientos", "mil", "millón", "millon", "millones"))


def key_word(tokens: list[str], locale: str) -> bool:
    """Whether these tokens hold a negation or a number (Korean spelled numbers are not covered)."""
    joined = "".join(tokens)
    if any(char.isdigit() for char in joined):
        return True
    if locale in {"zh-Hans", "ko"}:
        return (any(marker in joined for marker in NEGATIONS.get(locale, ()))
                or locale == "zh-Hans" and any(char in ZH_NUMERALS for char in joined))
    return any(token in NEGATIONS.get(locale, ()) or token in ES_NUMBERS
               or locale == "es" and token.startswith("veinti") for token in tokens)


def korean_native_numbers(text: str) -> list[str]:
    """The native-number forms in ``text``, in reading order."""
    from scripts.language_review_plugins import auto_qc_text_common as rules
    found = sorted((match.start(), -len(form), form) for number in range(1, 100)
                   for form in rules.korean_native(number)
                   for match in re.finditer(rules._ko_pattern(form), text))
    forms, end = [], -1
    for start, negative_length, form in found:
        if start >= end:  # The longest form wins where two overlap.
            forms.append(form)
            end = start - negative_length
    return forms


def protected_text_agrees(expected: str, recognized: str, locale: str) -> bool:
    """Check whole numeral forms and names that cannot be identified from a partial diff."""
    from scripts.language_review_plugins import auto_qc_text_common as rules
    left, right = (unicodedata.normalize("NFC", rules._fold(text)) for text in (expected, recognized))
    if locale == "en" and len(re.findall(r"\b[a-z]+n['’]t\b", left)) != len(re.findall(r"\b[a-z]+n['’]t\b", right)):
        return False
    if locale in {"zh-Hans", "ko", "es"}:
        def citations(text):
            if locale == "ko":
                # Keep raw Sino numeral groups: accent folding decomposes Hangul.
                return [match.groups() for match in rules._KO_CITATION.finditer(text)]
            return [(book, chapter, verse) for book, chapter, verse, _ in rules.book_citations(text, locale)]
        if citations(expected) != citations(recognized):
            return False
    if locale == "en" and rules.english_numbers(expected) != rules.english_numbers(recognized):
        return False
    if locale == "ko":
        counters = "|".join(rules._KO_COUNTERS)
        pattern = r"(?<![가-힣])[영공일이삼사오육칠팔구십백천만억]+(?=\s*(?:" + counters + r")|\s|$)"
        if re.findall(pattern, left) != re.findall(pattern, right):
            return False
        # In order: 두 아들과 세 딸 heard as 세 아들과 두 딸 keeps every count.
        if korean_native_numbers(left) != korean_native_numbers(right):
            return False
    if locale == "es":
        # Un and una are usually articles, so a changed form (un/una) is ASR
        # noise; losing or gaining one can still drop the quantity "one".
        ones = r"(?<!\w)(?:uno|una|un)(?!\w)"
        if len(re.findall(ones, left)) != len(re.findall(ones, right)):
            return False
    books = (rules._EN_BOOK_CODES if locale == "en" else rules._ES_BOOK_CODES if locale == "es"
             else rules._KO_BOOK_CODES if locale == "ko" else rules._ZH_BOOK_CODES)
    names = {key[-1] if isinstance(key, tuple) else key for key in books}
    names.update({"en": ("Jesus", "God"), "es": ("Jesús", "Dios"),
                  "ko": ("예수", "하나님"), "zh-Hans": ("耶稣", "神")}.get(locale, ()))
    if locale in {"en", "es"}:
        # The approved script supplies names; ASR capitalization is irrelevant.
        names.update(term for term in re.findall(r"\b[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+", expected)
                     if term.casefold() not in {"the", "he", "she", "we", "you", "they", "it", "this", "that",
                                                "some", "let", "in", "on", "for", "during", "when", "if",
                                                "el", "la", "los", "las", "un", "una", "él", "ella", "hoy", "en"})
    pattern = "|".join(re.escape(unicodedata.normalize("NFC", rules._fold(name)))
                       for name in sorted(names, key=len, reverse=True))
    if locale in {"en", "es"}:
        pattern = r"(?<!\w)(?:" + pattern + r")(?!\w)"
    # Order matters too: exchanging two names preserves counts but changes who did what.
    return re.findall(pattern, left) == re.findall(pattern, right)


def score(expected: str, recognized: str, locale: str, min_similarity: float) -> tuple[float, list[dict], bool]:
    """``(similarity, differences, passed)`` for one unit, as recorded in the receipt."""
    expected_tokens, actual_tokens = tokens(expected, locale), tokens(recognized, locale)
    matcher = difflib.SequenceMatcher(None, expected_tokens, actual_tokens, autojunk=False)
    similarity = round(matcher.ratio(), 6)
    differences = [{"kind": kind,
                    "expected": expected_tokens[left_start:left_end],
                    "recognized": actual_tokens[right_start:right_end]}
                   for kind, left_start, left_end, right_start, right_end
                   in matcher.get_opcodes() if kind != "equal"]
    # Short units are more vulnerable to a high score hiding one material
    # missing word, so require exact normalized ASR for them.
    passed = (similarity >= min_similarity and (len(expected_tokens) >= 4 or not differences)
              and not any(key_word(row["expected"], locale) or key_word(row["recognized"], locale)
                          for row in differences)
              and protected_text_agrees(expected, recognized, locale))
    return similarity, differences, passed


def screen(job: dict, manifest: dict, artifact_root: Path,
           transcribe: Callable[[Path, str], str] | None, *, model: str,
           model_revision: str, min_similarity: float = 0.88,
           batch_size: int = 1, transcribe_batch: Callable | None = None,
           unit_cache: Path | None = None,
           inference_identity: dict | None = None) -> tuple[dict, dict]:
    require(0 < min_similarity <= 1, "Invalid ASR similarity threshold")
    require(type(batch_size) is int and batch_size in BATCH_SIZES,
            "ASR batch size must be 1, 2, 4 or 8")
    require(callable(transcribe_batch) or (batch_size == 1 and callable(transcribe)),
            "ASR batching requires a batch transcriber")
    job_hash, manifest_hash = identity.json_sha256(job), identity.json_sha256(manifest)
    original_job, original_manifest = job, manifest
    job, manifest = copy.deepcopy(job), copy.deepcopy(manifest)
    require(job.get("schemaVersion") in speech.SPEECH_JOB_SCHEMAS
            and job.get("status") == "prepared_for_target_language_speech"
            and job.get("synthesisEligible") is True,
            "Formal synthesis-eligible speech job required")
    locale = job["targetLocale"]
    require(manifest.get("schemaVersion") == "sermon-target-language-render-manifest-v1"
            and manifest.get("targetLocale") == locale
            and manifest.get("targetLanguageSpeechJobJsonSha256") == identity.json_sha256(job)
            and manifest.get("englishSourcePackageJsonSha256")
            == job["inputs"]["englishSourcePackage"]["jsonSha256"]
            and manifest.get("targetLanguageCandidateJsonSha256")
            == job["inputs"]["targetLanguageCandidate"]["jsonSha256"],
            "Render manifest differs from formal speech job")
    require(manifest.get("machineScreening", {}).get("status") == "not_run"
            and "machineScreeningReceipt" not in manifest,
            "Screen only an unmodified renderer manifest")
    rows = manifest.get("units")
    require(isinstance(rows, list) and rows and len(rows) == len(job["units"]),
            "Render manifest does not cover all job units")
    track = manifest.get("track", {})
    track_path = (artifact_root / track.get("path", "")).resolve()
    require(track_path.is_relative_to(artifact_root.resolve())
            and track_path.is_file() and file_sha(track_path) == track.get("sha256"),
            "Rendered track hash mismatch")
    requests, recognized_units = [], {}
    for index, (unit, row) in enumerate(zip(job["units"], rows)):
        group_id = unit["translationGroupId"]
        expected_hash = hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()
        audio = row.get("audio", {})
        expected_path = (artifact_root / unit["outputRelativePath"]).resolve()
        require(row.get("textGroupId") == group_id
                and row.get("targetTextSha256") == expected_hash
                and audio.get("path") == unit["outputRelativePath"]
                and expected_path.is_relative_to(artifact_root.resolve())
                and expected_path.is_file() and file_sha(expected_path) == audio.get("sha256"),
                f"ASR unit identity or audio hash mismatch: {index}")
        requests.append({"path": expected_path, "identity": {
            "unitIndex": index, "textGroupId": group_id, "targetLocale": locale,
            "targetTextSha256": expected_hash, "audioSha256": audio["sha256"],
            "speechJobJsonSha256": job_hash, "model": model, "modelRevision": model_revision,
            "batchSize": batch_size, "maxNewTokens": 2048,
            "dtype": "bfloat16", "executionDevice": "cuda:0",
            "implementationSha256": file_sha(Path(__file__)),
            "runtime": copy.deepcopy(inference_identity or {}),
            "protocol": "formal-back-asr-batch-v1"}})
    require(len({row["identity"]["textGroupId"] for row in requests}) == len(requests),
            "ASR units contain duplicate groups")
    if unit_cache is not None:
        require(unit_cache.resolve().is_relative_to(artifact_root.resolve()),
                "ASR unit cache must live inside the artifact root")
        for request in requests:
            index = request["identity"]["unitIndex"]
            path = unit_cache / f"unit-{index:04d}.json"
            if path.exists():
                saved = load(path)
                require(saved.get("identity") == request["identity"]
                        and isinstance(saved.get("recognized"), str)
                        and saved.get("recognizedSha256") == hashlib.sha256(saved["recognized"].encode()).hexdigest(),
                        "ASR cached unit identity or result hash differs")
                recognized_units[index] = saved["recognized"]
    for start in range(0, len(requests), batch_size):
        batch = [row for row in requests[start:start + batch_size]
                 if row["identity"]["unitIndex"] not in recognized_units]
        if not batch:
            continue
        require(all(file_sha(row["path"]) == row["identity"]["audioSha256"] for row in batch),
                "ASR batch audio changed before transcription")
        if transcribe_batch is not None:
            values = transcribe_batch(copy.deepcopy(batch))
            require(isinstance(values, list) and len(values) == len(batch),
                    "ASR batch output cardinality differs")
            require(all(isinstance(value, dict) and value.get("identity") == request["identity"]
                        and isinstance(value.get("recognized"), str)
                        for value, request in zip(values, batch)),
                    "ASR batch output identity/order differs")
        else:
            text = transcribe(batch[0]["path"], locale)
            require(isinstance(text, str), "ASR transcription must be text")
            values = [{"identity": batch[0]["identity"], "recognized": text}]
        require(all(file_sha(row["path"]) == row["identity"]["audioSha256"] for row in batch)
                and identity.json_sha256(original_job) == job_hash
                and identity.json_sha256(original_manifest) == manifest_hash,
                "Frozen ASR batch inputs changed during transcription")
        for value in values:
            index = value["identity"]["unitIndex"]
            recognized_units[index] = value["recognized"]
            if unit_cache is not None:
                path = unit_cache / f"unit-{index:04d}.json"
                require(not path.exists(), "ASR unit cache cannot overwrite a receipt")
                write_atomic(path, {**value, "recognizedSha256": hashlib.sha256(value["recognized"].encode()).hexdigest()})
    require(len(recognized_units) == len(requests)
            and identity.json_sha256(original_job) == job_hash
            and identity.json_sha256(original_manifest) == manifest_hash
            and file_sha(track_path) == track["sha256"]
            and all(file_sha(row["path"]) == row["identity"]["audioSha256"] for row in requests),
            "ASR unit coverage or final audio hashes differ")
    results = []
    for index, (unit, row) in enumerate(zip(job["units"], rows)):
        group_id = unit["translationGroupId"]
        expected_hash = hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()
        audio = row["audio"]
        recognized = recognized_units[index].strip()
        require(tokens(unit["text"], locale), f"Empty expected text: {group_id}")
        similarity, differences, passed = score(unit["text"], recognized, locale, min_similarity)
        results.append({
            "textGroupId": group_id,
            "targetTextSha256": expected_hash,
            "audioSha256": audio["sha256"],
            "recognized": recognized,
            "similarity": similarity,
            "differences": differences,
            "status": "pass" if passed else "requires_review",
        })
    status = "pass" if all(row["status"] == "pass" for row in results) else "requires_review"
    # The normalized runtime behind every score, so a machine waiver can require the
    # same primary ASR its calibration measured (the request identities stay unchanged).
    asr_settings = {"protocol": "formal-back-asr-batch-v1", "model": model, "modelRevision": model_revision,
                    "language": locale, "batchSize": batch_size, "maxNewTokens": 2048, "dtype": "bfloat16",
                    "executionDevice": "cuda:0", "runtime": copy.deepcopy(inference_identity or {}),
                    "implementationSha256": file_sha(Path(__file__)), "minSimilarity": min_similarity,
                    "scoring": SCORING}
    receipt = {
        "schemaVersion": SCHEMA,
        "targetLocale": locale,
        "targetLanguageSpeechJobJsonSha256": identity.json_sha256(job),
        "trackSha256": track["sha256"],
        "status": status,
        "model": model,
        "modelRevision": model_revision,
        "minSimilarity": min_similarity,
        "coverage": 1.0,
        "reviewedGroupIds": [row["textGroupId"] for row in results],
        "unitAudioSha256s": [row["audioSha256"] for row in results],
        "results": results,
        "humanListeningStatus": "pending",
        "asrSettings": asr_settings,
        "asrSettingsSha256": identity.json_sha256(asr_settings),
    }
    if batch_size != 1:
        receipt["transcriptionBatchSize"] = batch_size
    screened = copy.deepcopy(manifest)
    screened["machineScreening"] = {"status": status, "model": model, "coverage": 1.0}
    return receipt, screened


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--render-manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--min-similarity", type=float, default=0.88)
    parser.add_argument("--batch-size", type=int, choices=BATCH_SIZES, default=None,
                        help="Production default1; Dev profile default4; explicit8 selects a comparison")
    dev_profile.add_arguments(parser)
    parser.add_argument("--unit-cache", type=Path,
                        help="Immutable per-unit ASR cache within the artifact root")
    parser.add_argument("--out-receipt", type=Path, required=True)
    parser.add_argument("--out-manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    dev_settings = dev_profile.resolve("back-asr", enabled=args.dev_test,
        profile_path=args.dev_test_profile, batch_size=args.batch_size)
    args.batch_size = dev_settings["batchSize"]
    dev_receipt_path = args.out_receipt.with_suffix(".dev-test.json")
    if dev_settings["profile"] is not None:
        dev_receipts.check_destination(dev_receipt_path, dev_settings)
    require(not args.out_receipt.exists() and not args.out_manifest.exists(),
            "ASR receipt and screened manifest are immutable")
    require(args.out_receipt.resolve().is_relative_to(args.artifact_root.resolve()),
            "ASR receipt must live inside the renderer artifact root")
    weights = args.model_path.resolve() / "model.safetensors"
    require(weights.is_file()
            and args.model_revision == f"model.safetensors:sha256:{file_sha(weights)}",
            "ASR model revision differs from deployed weights")
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel
    import importlib.metadata

    try:
        asr_version = importlib.metadata.version("qwen-asr")
    except importlib.metadata.PackageNotFoundError:
        asr_version = "unavailable"
    inference_identity = {
        "torchVersion": getattr(torch, "__version__", "unavailable"),
        "qwenAsrVersion": asr_version,
        "modelMetadataSha256s": {str(path.relative_to(args.model_path.resolve())): file_sha(path)
            for path in sorted(args.model_path.resolve().rglob("*.json"))},
    }

    model = None
    languages = {"zh-Hans": "Chinese", "ko": "Korean", "es": "Spanish"}

    def resident_model():
        nonlocal model
        if model is None:
            model = Qwen3ASRModel.from_pretrained(
                str(args.model_path.resolve()), dtype=torch.bfloat16,
                device_map="cuda:0", max_inference_batch_size=args.batch_size, max_new_tokens=2048)
        return model

    def transcribe(path: Path, locale: str) -> str:
        audio, sample_rate = sf.read(path, dtype="float32")
        values = resident_model().transcribe(audio=(audio, sample_rate), language=languages[locale])
        require(len(values) == 1 and isinstance(values[0].text, str), "ASR scalar output cardinality differs")
        return values[0].text

    def transcribe_batch(requests: list[dict]) -> list[dict]:
        audio = [sf.read(row["path"], dtype="float32") for row in requests]
        values = resident_model().transcribe(
            audio=audio, language=[languages[row["identity"]["targetLocale"]] for row in requests])
        require(len(values) == len(requests) and all(isinstance(value.text, str) for value in values),
                "ASR batch output cardinality differs")
        return [{"identity": row["identity"], "recognized": value.text}
                for row, value in zip(requests, values)]

    receipt, screened = screen(load(args.job), load(args.render_manifest),
                               args.artifact_root.resolve(), transcribe,
                               model=MODEL, model_revision=args.model_revision,
                               min_similarity=args.min_similarity, batch_size=args.batch_size,
                               transcribe_batch=transcribe_batch if args.batch_size != 1 else None,
                               unit_cache=args.unit_cache, inference_identity=inference_identity)
    args.out_receipt.parent.mkdir(parents=True, exist_ok=True)
    args.out_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    # The manifest's evidence path is relative to the renderer artifact root.
    relative = args.out_receipt.resolve().relative_to(args.artifact_root.resolve())
    screened["machineScreeningReceipt"] = {
        "path": str(relative), "sha256": file_sha(args.out_receipt),
        "jsonSha256": identity.json_sha256(receipt),
    }
    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out_manifest.write_text(json.dumps(screened, ensure_ascii=False, indent=2) + "\n")
    if dev_settings["profile"] is not None:
        dev_receipts.write(dev_settings, args.out_receipt, dev_receipt_path)
    print(json.dumps({"status": receipt["status"], "groups": len(receipt["results"]),
                      "reviewQueue": [row["textGroupId"] for row in receipt["results"]
                                      if row["status"] != "pass"],
                      **({"devTestConsumptionReceipt": str(dev_receipt_path.resolve())}
                         if dev_settings["profile"] is not None else {})}, ensure_ascii=False))


if __name__ == "__main__":
    main()
