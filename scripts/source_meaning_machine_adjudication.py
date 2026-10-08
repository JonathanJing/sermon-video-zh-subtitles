#!/usr/bin/env python3
"""Machine adjudication of a source-meaning doubt on a frozen English unit.

A Layer 2 reviewer sometimes cannot make sense of a frozen English unit ("You're
filled in the middle of a trial"): the doubt is about what the speaker said, and
no translation repair can settle it. This tool settles it from the bound audio
instead of a person:

1. cut the doubted unit with its neighbouring units from the bound media (the
   media hash, the approved window and the word times are the binding);
2. have independent listeners (``gpt-transcribe`` through the API, Qwen3-ASR on
   Spark) transcribe that clip without seeing the frozen text;
3. locate the unit inside each re-listen and compare it with the frozen words;
4. when every listener heard exactly the frozen words, the transcript is
   confirmed without a model call; otherwise ``gpt-6.1-sol`` chooses among the
   frozen text and what the listeners heard, never a wording nobody heard.

The receipt is machine evidence (``humanApproval`` false). A corrected unit also
yields a ``sermon-source-text-review-v1`` review on its ASR segment, which the
existing Layer 1 path applies and realigns; the new Layer 1 identity then
invalidates every locale downstream, as the contract requires. A confirmed or
undetermined unit keeps the frozen text, and its ``meaningNote`` goes into the
translator's and reviewer's instruction.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sermon_provider_limits as limits  # noqa: E402
from scripts import sermon_source_text_review as source_review  # noqa: E402
from scripts import target_language_policy as policies  # noqa: E402

SCHEMA = 'sermon-source-meaning-machine-adjudication-v1'
QUESTION_SCHEMA = 'sermon-source-meaning-adjudication-question-v1'
RESPONSE_SCHEMA = 'sermon-source-meaning-adjudication-response-v1'
PROMPT_VERSION = 'source-meaning-adjudication-v1'
VERSION = '2026-10-08-v1'
ROLE = 'machine_adjudicator'
MODEL, EFFORT = 'gpt-6.1-sol', 'medium'
DECISIONS = ('transcript_confirmed', 'transcript_corrected', 'undetermined')
CLIP_CONTEXT_UNITS = 1   # neighbouring units cut with the doubted unit, each side
TEXT_CONTEXT_UNITS = 5   # neighbouring units the adjudicator reads, each side
SAMPLE_RATE = 16000
MAX_NOTE_CHARS = 300
TIME_TOLERANCE = 0.05
LISTEN_PROMPT = ('Transcribe this English church sermon audio exactly as spoken. '
                 'Do not add, correct or complete words that are not audible.')
CONFIRMED_NOTE = ('Independent listeners heard exactly these words: translate them literally as the '
                  "speaker's own phrasing and do not add, infer or soften meaning.")
SYSTEM_PROMPT = """You adjudicate what an English sermon speaker actually said in one timed unit.
A translation reviewer doubted the frozen transcript of that unit. Independent listeners transcribed
the audio of the unit with its neighbours without seeing the transcript. Decide, from the frozen text,
what each listener heard for the unit and the surrounding units, which wording the speaker said.

Rules: choose only among the frozen text and the listeners' wordings for the unit; never compose a
wording nobody heard. A listener that heard the frozen words supports the transcript. When the evidence
does not settle the wording, answer undetermined. Do not rewrite, improve, translate or interpret beyond
one sentence for the translator. Answer with one JSON object:
{"schemaVersion": "sermon-source-meaning-adjudication-response-v1",
 "decision": "transcript_confirmed" or "transcript_corrected" or "undetermined",
 "heardBy": "frozen" or the name of the listener whose wording you chose,
 "correctedText": that listener's wording for the unit as a sentence, or null unless corrected,
 "meaningNote": one sentence telling the translator how to treat the unit,
 "reason": the evidence you weighed}"""


class SourceAdjudicationError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SourceAdjudicationError(code)


def implementation_sha256() -> str:
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------- words

_APOSTROPHES = str.maketrans({'’': "'", '‘': "'"})


def _words(text: str) -> list[str]:
    return [word for word in re.split(r'\s+', text.strip()) if word]


def _normal(word: str) -> str:
    return re.sub(r"[^a-z0-9']", '', word.lower().translate(_APOSTROPHES)).strip("'")


def tokens(text: str) -> list[str]:
    """Comparison tokens: case, punctuation and apostrophe style are presentation."""
    return [token for token in (_normal(word) for word in _words(text)) if token]


def best_window(frozen: list[str], heard: str) -> dict[str, Any]:
    """The stretch of a listener's transcript that best matches the frozen tokens."""
    rows = [(_normal(word), word) for word in _words(heard)]
    rows = [(token, word) for token, word in rows if token]
    if not frozen or not rows:
        return {'text': '', 'tokens': [], 'similarity': 0.0}
    best: tuple[float, int, int] | None = None
    for size in range(max(1, len(frozen) - 2), len(frozen) + 3):
        for start in range(0, max(1, len(rows) - size + 1)):
            candidate = [token for token, _ in rows[start:start + size]]
            ratio = difflib.SequenceMatcher(None, frozen, candidate, autojunk=False).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, start, size)
    ratio, start, size = best
    window = rows[start:start + size]
    return {'text': ' '.join(word for _, word in window), 'tokens': [token for token, _ in window],
            'similarity': round(ratio, 6)}


# ---------------------------------------------------------------- audio

def cut_clip(media: Path, start: float, end: float) -> bytes:
    """PCM16 mono 16 kHz WAV bytes of ``media`` between two media times."""
    _require(shutil.which('ffmpeg') is not None, 'ffmpeg_missing')
    _require(end > start, 'clip_window_empty')
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / 'clip.wav'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', format(start, '.3f'),
                        '-t', format(end - start, '.3f'), '-i', str(media), '-vn', '-ar', str(SAMPLE_RATE),
                        '-ac', '1', '-c:a', 'pcm_s16le', str(out)],
                       check=True, capture_output=True, timeout=600)
        return out.read_bytes()


# ---------------------------------------------------------------- listeners

class OpenAiTranscribeListener:
    """``gpt-transcribe`` through the selected OpenAI Project; it never sees the frozen text.

    Runs only under ``scripts/run_with_openai_environment.py``; the key is read from
    the environment the launcher sets. ``max_calls`` caps new paid requests."""

    name = model = 'gpt-transcribe'

    def __init__(self, *, cache: Path, max_calls: int):
        from scripts import machine_qc_audio_transports as transports
        from scripts import sermon_openai_runtime as runtime
        _require(runtime.selected_route() is not None, 'openai_environment_launcher_required')
        self.cache = transports.CallCache(cache, paid=True)
        self.max_calls, self.calls = max_calls, 0
        self.fields = [('model', self.model), ('response_format', 'json'), ('prompt', LISTEN_PROMPT),
                       ('languages[]', 'en')]

    def identity(self) -> dict[str, Any]:
        return {'backend': 'openai-api', 'endpoint': '/v1/audio/transcriptions', 'model': self.model,
                'language': 'en', 'promptSha256': _sha(LISTEN_PROMPT.encode('utf-8'))}

    def _send(self, wav: bytes) -> dict[str, Any]:
        from scripts import machine_qc_audio_transports as transports
        from scripts import sermon_pipeline
        from scripts.sermon_openai_runtime import project_headers
        body, content_type = transports._multipart(self.fields, wav)
        key = os.environ['OPENAI_API_KEY']
        request = urllib.request.Request(transports.TRANSCRIBE_URL, data=body, method='POST', headers={
            'Authorization': f'Bearer {key}', 'Content-Type': content_type, **project_headers(key)})
        request.accounting_model = self.model
        request.accounting_settings = {'requestPayloadSha256': _sha(body)}
        response = sermon_pipeline.request_json(request, retries=1)
        _require(isinstance(response, dict) and isinstance(response.get('text'), str), 'listener_returned_no_text')
        return {'text': response['text'], 'usage': response.get('usage')}

    def transcribe(self, wav: bytes) -> str:
        audio_sha = _sha(wav)
        key = policies.canonical_sha256({'listener': self.name, 'audioSha256': audio_sha, 'identity': self.identity()})
        done = self.cache.get(key)
        if done is None:
            _require(self.calls < self.max_calls, 'listener_call_cap_reached')
            self.calls += 1
            done = self.cache.run(key, {'audioSha256': audio_sha, 'listener': self.name}, lambda: self._send(wav))
        return done['text'].strip()


class QwenListener:
    """Local Qwen3-ASR, the Layer 3 screening model, as the second independent listener."""

    name = model = 'qwen3-asr'

    def __init__(self, model_path: Path, *, cache: Path):
        from scripts import machine_qc_audio_transports as transports
        self.model_path = Path(model_path).resolve()
        weights = self.model_path / 'model.safetensors'
        _require(weights.is_file(), 'qwen_weights_missing')
        self.model_revision = f'model.safetensors:sha256:{file_sha256(weights)}'
        self.cache = transports.CallCache(cache, paid=False)
        self._model = None

    def identity(self) -> dict[str, Any]:
        return {'backend': 'qwen-asr-local', 'model': self.model, 'modelRevision': self.model_revision,
                'language': 'English'}

    def _run(self, wav: bytes) -> str:
        if self._model is None:
            import torch
            from qwen_asr import Qwen3ASRModel
            self._model = Qwen3ASRModel.from_pretrained(str(self.model_path), dtype=torch.bfloat16,
                                                        device_map='cuda:0', max_inference_batch_size=1,
                                                        max_new_tokens=2048)
        import soundfile as sf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'clip.wav'
            path.write_bytes(wav)
            audio, rate = sf.read(path, dtype='float32')
        values = self._model.transcribe(audio=(audio, rate), language='English')
        _require(len(values) == 1 and isinstance(values[0].text, str), 'listener_output_cardinality')
        return values[0].text

    def transcribe(self, wav: bytes) -> str:
        audio_sha = _sha(wav)
        key = policies.canonical_sha256({'listener': self.name, 'audioSha256': audio_sha, 'identity': self.identity()})
        return self.cache.run(key, {'audioSha256': audio_sha, 'listener': self.name},
                              lambda: {'text': self._run(wav)})['text'].strip()


# ---------------------------------------------------------------- adjudicator

class SolAdjudicator:
    """One bounded JSON call per doubted unit, cached by request identity."""

    def __init__(self, *, api_key: str, cache: Path, model: str = MODEL, effort: str = EFFORT,
                 caller: Callable[..., dict[str, Any]] | None = None):
        _require(model in limits.SUPPORTED_MODELS and effort in limits.MODEL_REASONING_EFFORTS[model],
                 'unsupported_adjudicator_model')
        if caller is None:
            from scripts.production_spark_admission import SessionBoundCaller
            from scripts.sermon_pipeline import chat_json
            caller = SessionBoundCaller(chat_json, purpose='source-meaning-adjudication')
        self.api_key, self.cache, self.model, self.effort, self.caller = api_key, Path(cache), model, effort, caller

    def identity(self) -> dict[str, Any]:
        return {'model': self.model, 'reasoningEffort': self.effort, 'promptVersion': PROMPT_VERSION,
                'promptSha256': _sha(SYSTEM_PROMPT.encode('utf-8'))}

    def payload(self, question: dict[str, Any]) -> dict[str, Any]:
        payload = {'model': self.model, 'reasoning_effort': self.effort,
                   'response_format': {'type': 'json_object'},
                   'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                                {'role': 'user', 'content': json.dumps(question, ensure_ascii=False)}],
                   'max_completion_tokens': limits.DEFAULT_REQUEST_LIMITS['maxCompletionTokens'],
                   'service_tier': limits.DEFAULT_REQUEST_LIMITS['serviceTier']}
        # The strict transport refuses anything but a payload already carrying its worst-case cap.
        _require(limits.bounded_payload(payload, limits.DEFAULT_REQUEST_LIMITS) == payload,
                 'adjudicator_payload_unbounded')
        return payload

    def decide(self, unit_id: str, question: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        from scripts.english_source_judge_cache import cached_call
        return cached_call(out=self.cache, stage=f'source-meaning-{unit_id}', payload=self.payload(question),
                           api_key=self.api_key, requested_model=self.model, caller=self.caller)


def _checked_answer(result: Any, frozen: list[str], heard: list[dict[str, Any]]) -> dict[str, Any]:
    """The model may only pick a wording that was heard; everything else is refused."""
    _require(isinstance(result, dict) and result.get('schemaVersion') == RESPONSE_SCHEMA, 'answer_schema')
    decision, heard_by = result.get('decision'), result.get('heardBy')
    note, reason, corrected = result.get('meaningNote'), result.get('reason'), result.get('correctedText')
    _require(decision in DECISIONS, 'answer_decision')
    _require(isinstance(note, str) and note.strip() and len(note) <= MAX_NOTE_CHARS, 'answer_note')
    _require(isinstance(reason, str) and reason.strip(), 'answer_reason')
    by_name = {row['listener']: row for row in heard}
    _require(heard_by == 'frozen' or heard_by in by_name, 'answer_heard_by')
    if decision == 'transcript_corrected':
        _require(heard_by != 'frozen' and by_name[heard_by]['unitTokens'] != frozen, 'corrected_by_frozen_words')
        _require(isinstance(corrected, str) and corrected.strip(), 'corrected_text_missing')
        _require(tokens(corrected) == by_name[heard_by]['unitTokens'], 'corrected_text_not_heard')
    else:
        _require(corrected is None, 'corrected_text_without_correction')
    return {'decision': decision, 'heardBy': heard_by, 'correctedText': corrected.strip() if corrected else None,
            'meaningNote': note.strip(), 'reason': reason.strip()}


# ---------------------------------------------------------------- adjudication

def _units(anchor: dict[str, Any]) -> list[dict[str, Any]]:
    units = anchor.get('sourceUnits')
    _require(isinstance(units, list) and units and all(
        isinstance(u, dict) and isinstance(u.get('sourceUnitId'), str) and isinstance(u.get('english'), str)
        for u in units), 'anchor_units')
    return units


def _media_binding(source: dict[str, Any]) -> tuple[dict[str, Any], float]:
    media = source.get('source', {}).get('media')
    window = source.get('source', {}).get('approvedWindow')
    _require(isinstance(media, dict) and isinstance(media.get('sha256'), str)
             and type(media.get('sizeBytes')) is int, 'source_media_identity')
    _require(isinstance(window, dict) and isinstance(window.get('startSeconds'), (int, float)), 'source_window')
    return media, float(window['startSeconds'])


def adjudicate(source: dict[str, Any], anchor: dict[str, Any], *, unit_ids: list[str], media: Path | None,
               listeners: list[Any], adjudicator: SolAdjudicator | None, out_dir: Path,
               cut: Callable[[Path, float, float], bytes] = cut_clip,
               now: datetime | None = None) -> dict[str, Any]:
    """Adjudicate the doubted units; write clips and re-listens under ``out_dir``; return the receipt.

    Unit times in the anchor are relative to the approved window, so each clip
    is cut at ``window start + unit time`` of the bound media. ``media`` may be
    None only when ``cut`` does not read it (tests)."""
    _require(listeners, 'listeners_required')
    _require(len(unit_ids) == len(set(unit_ids)) and unit_ids, 'unit_ids')
    units = _units(anchor)
    by_id = {u['sourceUnitId']: i for i, u in enumerate(units)}
    _require(all(uid in by_id for uid in unit_ids), 'unit_unknown')
    media_info, offset = _media_binding(source)
    if media is not None:
        _require(Path(media).stat().st_size == media_info['sizeBytes']
                 and file_sha256(media) == media_info['sha256'], 'media_identity_mismatch')
    out_dir = Path(out_dir)
    (out_dir / 'clips').mkdir(parents=True, exist_ok=True)
    (out_dir / 'listeners').mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for uid in unit_ids:
        index = by_id[uid]
        unit = units[index]
        low, high = max(0, index - CLIP_CONTEXT_UNITS), min(len(units) - 1, index + CLIP_CONTEXT_UNITS)
        start, end = float(units[low]['start']), float(units[high]['end'])
        wav = cut(media, offset + start, offset + end)
        clip_sha = _sha(wav)
        (out_dir / 'clips' / f'{uid}.wav').write_bytes(wav)
        frozen = tokens(unit['english'])
        heard: list[dict[str, Any]] = []
        for listener in listeners:
            text = listener.transcribe(wav)
            window = best_window(frozen, text)
            row = {'listener': listener.name, 'model': listener.model, 'clipSha256': clip_sha, 'text': text,
                   'unitWindow': window['text'], 'unitTokens': window['tokens'],
                   'similarityToFrozen': window['similarity'], 'agreesWithFrozen': window['tokens'] == frozen}
            heard.append(row)
            (out_dir / 'listeners' / f'{uid}.{listener.name}.json').write_text(
                json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if all(row['agreesWithFrozen'] for row in heard):
            verdict = {'decision': 'transcript_confirmed', 'heardBy': 'frozen', 'correctedText': None,
                       'meaningNote': CONFIRMED_NOTE,
                       'reason': f'{len(heard)} independent listener(s) heard exactly the frozen words'}
            decided_by, request = 'listeners_agree_with_transcript', None
        else:
            _require(adjudicator is not None, 'adjudicator_required')
            context = [{'sourceUnitId': units[i]['sourceUnitId'], 'english': units[i]['english'],
                        'position': 'doubted' if i == index else 'before' if i < index else 'after'}
                       for i in range(max(0, index - TEXT_CONTEXT_UNITS),
                                      min(len(units), index + TEXT_CONTEXT_UNITS + 1))]
            question = {'schemaVersion': QUESTION_SCHEMA, 'sourceUnitId': uid, 'frozenText': unit['english'],
                        'context': context,
                        'clip': {'sourceUnitIds': [units[i]['sourceUnitId'] for i in range(low, high + 1)],
                                 'seconds': round(end - start, 3)},
                        'listeners': [{'name': row['listener'], 'model': row['model'], 'heardClip': row['text'],
                                       'heardForUnit': row['unitWindow'],
                                       'similarityToFrozen': row['similarityToFrozen'],
                                       'agreesWithFrozen': row['agreesWithFrozen']} for row in heard]}
            result, request = adjudicator.decide(uid, question)
            verdict = _checked_answer(result, frozen, heard)
            decided_by = 'model'
        rows.append({'sourceUnitId': uid, 'sourceSentenceId': unit.get('sourceSentenceId'),
                     'frozenText': unit['english'],
                     'clip': {'sourceUnitIds': [units[i]['sourceUnitId'] for i in range(low, high + 1)],
                              'windowStart': start, 'windowEnd': end, 'mediaStart': round(offset + start, 6),
                              'mediaEnd': round(offset + end, 6), 'sha256': clip_sha},
                     'heard': heard, **verdict, 'decidedBy': decided_by, 'request': request})

    stamp = (now or datetime.now(timezone.utc)).isoformat()
    sha = implementation_sha256()
    receipt = {
        'schemaVersion': SCHEMA, 'version': VERSION, 'implementationSha256': sha,
        'bindings': {'source.json': policies.canonical_sha256(source), 'anchor.json': policies.canonical_sha256(anchor)},
        'media': {'sha256': media_info['sha256'], 'sizeBytes': media_info['sizeBytes'],
                  'offsetSeconds': offset, 'unitTimesRelativeTo': 'approved_window'},
        'decidedBy': f'source_meaning_machine_adjudication {VERSION} {sha[:16]}', 'decidedByRole': ROLE,
        'humanApproval': False, 'reviewedAt': stamp,
        'listeners': [{'name': item.name, 'model': item.model, 'identity': item.identity()} for item in listeners],
        'adjudicator': None if adjudicator is None else adjudicator.identity(),
        'units': rows,
        'counts': {'units': len(rows), **{d: sum(r['decision'] == d for r in rows) for d in DECISIONS}},
        'notice': ('Machine evidence from the bound audio; not human approval. A corrected unit changes '
                   'Layer 1 through sermon-source-text-review-v1 and invalidates every locale downstream. '
                   'A confirmed or undetermined unit keeps the frozen text; its meaningNote goes to the '
                   "translator's and reviewer's instruction."),
    }
    return receipt


def receipt_sha256(receipt: dict[str, Any]) -> str:
    return policies.canonical_sha256(receipt)


# ---------------------------------------------------------------- Layer 1 review

def _segment_for(unit: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    """The ASR segment whose timed words contain the unit and whose text carries it verbatim."""
    chunk = str(unit.get('referenceChunkId', '')).strip()
    found = [seg for seg in segments
             if isinstance(seg, dict) and str(seg.get('referenceChunkId', '')).strip() == chunk
             and float(seg.get('start', 1e12)) <= float(unit['start']) + TIME_TOLERANCE
             and float(seg.get('end', -1)) >= float(unit['end']) - TIME_TOLERANCE
             and isinstance(seg.get('text'), str) and seg['text'].count(unit['english']) == 1]
    _require(len(found) == 1, 'segment_not_located')
    return found[0]


def source_text_review(receipt: dict[str, Any], anchor: dict[str, Any], segments: list[dict[str, Any]], *,
                       receipt_path: Path, source_audio: Path, asr_reference: Path) -> dict[str, Any] | None:
    """A ``sermon-source-text-review-v1`` review for the corrected units, or None when nothing changed.

    The review binds the window clip and ASR reference the Layer 1 pipeline
    will apply it against, and the receipt file as its evidence; relative
    evidence paths resolve against the review's own directory."""
    corrected = [row for row in receipt['units'] if row['decision'] == 'transcript_corrected']
    if not corrected:
        return None
    _require(receipt.get('adjudicator') is not None, 'adjudicator_identity_missing')
    by_id = {u['sourceUnitId']: u for u in _units(anchor)}
    receipt_path = Path(receipt_path).resolve()
    evidence_sha = file_sha256(receipt_path)
    patches: list[dict[str, Any]] = []
    for row in corrected:
        unit = by_id[row['sourceUnitId']]
        segment = _segment_for(unit, segments)
        _require(type(segment.get('id')) is int and segment['id'] not in {p['segmentId'] for p in patches},
                 'segment_id_repeated')
        patches.append({'segmentId': segment['id'],
                        'originalTextSha256': source_review.text_sha256(segment['text']),
                        'correctedText': segment['text'].replace(unit['english'], row['correctedText']),
                        'reason': f"{row['sourceUnitId']} heard by {row['heardBy']}: {row['reason']}",
                        'evidenceSha256': evidence_sha})
    return {'schemaVersion': source_review.SCHEMA, 'reviewType': 'model', 'model': receipt['adjudicator']['model'],
            'humanApproval': False, 'status': source_review.STATUS, 'authority': source_review.MACHINE_AUTHORITY,
            'reviewedBy': receipt['decidedBy'], 'reviewedAt': receipt['reviewedAt'],
            'sourceAudioSha256': file_sha256(source_audio), 'asrSha256': file_sha256(asr_reference),
            'evidence': [{'path': receipt_path.name, 'sha256': evidence_sha}], 'patches': patches}


# ---------------------------------------------------------------- CLI

def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixture', type=Path, help='Directory with source.json and anchor.json')
    parser.add_argument('--media', type=Path, required=True, help='The bound media file named by source.json')
    parser.add_argument('--unit', action='append', required=True, help='Doubted source unit; repeatable')
    parser.add_argument('--out-dir', type=Path, required=True, help='New directory for receipt, clips, re-listens')
    parser.add_argument('--listener', action='append', choices=('openai', 'qwen'), default=None,
                        help='Independent listeners (default: openai)')
    parser.add_argument('--asr-model-path', type=Path, help='Qwen3-ASR weights for the qwen listener')
    parser.add_argument('--max-api-calls', type=int, default=8, help='Cap on new paid transcription calls')
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--reasoning-effort', default=EFFORT)
    parser.add_argument('--aligned-segments', type=Path,
                        help='Layer 1 aligned segments; with the two paths below, a corrected unit writes the review')
    parser.add_argument('--source-audio', type=Path, help='The window clip the Layer 1 pipeline transcribed')
    parser.add_argument('--asr-reference', type=Path, help='The ASR reference file the Layer 1 pipeline wrote')
    args = parser.parse_args(argv)
    if args.out_dir.exists():
        raise SystemExit('out dir exists; choose a new path')
    review_inputs = (args.aligned_segments, args.source_audio, args.asr_reference)
    if any(review_inputs) and not all(review_inputs):
        raise SystemExit('--aligned-segments, --source-audio and --asr-reference go together')
    from scripts import sermon_openai_runtime as runtime
    if runtime.selected_route() is None:
        raise SystemExit('start under scripts/run_with_openai_environment.py --environment dev (prod for formal content)')
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    source, anchor = _load(args.fixture / 'source.json'), _load(args.fixture / 'anchor.json')
    segments = None
    if args.aligned_segments:
        expected = source.get('transcript', {}).get('artifact', {}).get('sha256')
        if isinstance(expected, str) and file_sha256(args.aligned_segments) != expected:
            raise SystemExit('aligned segments differ from the transcript artifact source.json binds')
        segments = _load(args.aligned_segments)
    cache = args.out_dir / 'cache'
    listeners: list[Any] = []
    for choice in args.listener or ['openai']:
        if choice == 'openai':
            listeners.append(OpenAiTranscribeListener(cache=cache / 'openai', max_calls=args.max_api_calls))
        else:
            if args.asr_model_path is None:
                raise SystemExit('--listener qwen needs --asr-model-path')
            listeners.append(QwenListener(args.asr_model_path, cache=cache / 'qwen'))
    adjudicator = SolAdjudicator(api_key=api_key, cache=cache, model=args.model, effort=args.reasoning_effort)
    receipt = adjudicate(source, anchor, unit_ids=args.unit, media=args.media, listeners=listeners,
                         adjudicator=adjudicator, out_dir=args.out_dir)
    receipt_path = args.out_dir / 'receipt.json'
    _write_new(receipt_path, receipt)
    summary = {'receiptSha256': receipt_sha256(receipt), 'out': str(args.out_dir.resolve()),
               'decisions': [(row['sourceUnitId'], row['decision'], row['correctedText']) for row in receipt['units']],
               'review': None}
    if segments is not None:
        review = source_text_review(receipt, anchor, segments, receipt_path=receipt_path,
                                    source_audio=args.source_audio, asr_reference=args.asr_reference)
        if review is not None:
            _write_new(args.out_dir / 'source-text-review.json', review)
            summary['review'] = str((args.out_dir / 'source-text-review.json').resolve())
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
