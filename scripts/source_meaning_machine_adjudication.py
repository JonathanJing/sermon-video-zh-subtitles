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
4. when listeners independent of the Layer 1 transcription all heard exactly
   the frozen words inside a stretch their neighbours bound, the transcript is
   confirmed without a model call; otherwise ``gpt-6.1-sol`` chooses among the
   frozen text and what the listeners heard, never a wording nobody heard.

The receipt is machine evidence (``humanApproval`` false). A corrected unit also
yields a ``sermon-source-text-review-v2`` review on its ASR segment, which the
existing Layer 1 path applies and realigns; the new Layer 1 identity then
invalidates every locale downstream, as the contract requires. A confirmed or
undetermined unit keeps the frozen text; ``meaning-notes.json`` carries its
``meaningNote``, bound to the same Layer 1 inputs, for the Layer 2 repair brief.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable
import wave

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sermon_provider_limits as limits  # noqa: E402
from scripts import sermon_source_text_review as source_review  # noqa: E402
from scripts import target_language_policy as policies  # noqa: E402

SCHEMA = source_review.MACHINE_RECEIPT_SCHEMA
# Receipts written before verdicts were reproduced from the request cache; read under their own rules.
SCHEMA_V1 = source_review.MACHINE_RECEIPT_SCHEMA_V1
QUESTION_SCHEMA = 'sermon-source-meaning-adjudication-question-v1'
RESPONSE_SCHEMA = 'sermon-source-meaning-adjudication-response-v1'
PROMPT_VERSION = 'source-meaning-adjudication-v2'
NOTES_SCHEMA = 'sermon-source-meaning-notes-v1'
VERSION = '2026-10-08-v3'
# Every implementation of this module that wrote v1 receipts (its git history from 9a34493 through a565df1),
# with the version it signed. A v1 receipt is read under its pre-cache rules only when it names one of them,
# so relabelling a newer receipt as v1 cannot switch off the cache and question checks.
V1_IMPLEMENTATIONS = {
    'd0069ae329a1a976e28d67592142f71fb3fb1b55cf3c480c393c5f8ebf76acc4': '2026-10-08-v1',
    'a996f72e59e26ec2c9f697bd38ebcc5eb96574b6abf1a34a4fbb00edc88b6da4': '2026-10-08-v2',
    '043afa8872162cadaf65bc2d32b7b2a1c5862d7cbd3c5b5bb82ff781514dc7a9': '2026-10-08-v2',
    '82495ef91b07d346f564a593f1666fce2c8d49a31f13e7e8afa1da83ee2f947b': '2026-10-08-v3',
    'aa9844492a04c0e134145d44731937bcedf14985f6874f641ffcf684351cf705': '2026-10-08-v3',
    '103dd09e7a8e16a66948a22e9dfa790d95e289f7098d405112c2274b6fa263d4': '2026-10-08-v3',
    'a8752fb10c61a58578fe14519d4930f3f1d6294ae98178657a391a86bf4ae541': '2026-10-08-v3',
    'e856a679593682306943eda3a41a1c0301140f1db18ba2c1d6aca8b02074be6c': '2026-10-08-v3',
    '95e48ac4649725369526a2e83a500e87303bc17b7231f404a7d736166b6867e7': '2026-10-08-v3',
    'adf10632baf989ebb7192d801bc39af4307d0a835b35b9a37d0dde726361118b': '2026-10-08-v3',
    'e2142ff7817ae4c79805e762048adc733bd488cd4e214f2a24b31bc0b0943437': '2026-10-08-v3',
    '743fec4cb4e255d86e0ad05d99c8093176c4ebbbdfe12a2a683beb814fbe47f7': '2026-10-08-v3',
}
ROLE = source_review.MACHINE_ROLE
MODEL, EFFORT = 'gpt-6.1-sol', 'medium'
# Only a model the Layer 1 review path also accepts may adjudicate; otherwise a
# correction would be paid for and then refused by sermon_source_text_review.
ADJUDICATOR_MODELS = frozenset(source_review.SUPPORTED_MODELS) & frozenset(limits.SUPPORTED_MODELS)
DECISIONS = ('transcript_confirmed', 'transcript_corrected', 'undetermined')
CLIP_CONTEXT_UNITS = 1   # neighbouring units cut with the doubted unit, each side
TEXT_CONTEXT_UNITS = 5   # neighbouring units the adjudicator reads, each side
NEIGHBOUR_MATCH_MIN = 0.5  # share of a neighbour's frozen words a listener must have heard to bound the unit
SAMPLE_RATE = 16000
MAX_NOTE_CHARS = 300
TIME_TOLERANCE = source_review.UNIT_TIME_TOLERANCE
BUDGET_SCHEMA = 'sermon-source-meaning-budget-authorization-v1'
BUDGET_APPROVAL_SCHEMA = 'sermon-source-meaning-budget-approval-v1'
BUDGET_DIR = 'budget'            # the SourceBudget ledger under --out-dir
ADJUDICATOR_CACHE = 'cache'      # the request cache under --out-dir, receipts name files inside it
LISTEN_REQUEST_SCHEMA = 'sermon-source-meaning-listen-request-v1'
CHAT_URL = 'https://api.openai.com/v1/chat/completions'
QWEN_SETTINGS = {'dtype': 'bfloat16', 'executionDevice': 'cuda:0', 'batchSize': 1, 'maxNewTokens': 2048,
                 'language': 'English'}
LISTEN_PROMPT = ('Transcribe this English church sermon audio exactly as spoken. '
                 'Do not add, correct or complete words that are not audible.')
CONFIRMED_NOTE = ('Independent listeners heard exactly these words: translate them literally as the '
                  "speaker's own phrasing and do not add, infer or soften meaning.")
SYSTEM_PROMPT = """You adjudicate what an English sermon speaker actually said in one timed unit.
A translation reviewer doubted the frozen transcript of that unit. Independent listeners transcribed
the audio of the unit with its neighbours without seeing the transcript. Decide, from the frozen text,
what each listener heard for the unit and the surrounding units, which wording the speaker said.

Rules: choose only among the frozen text and the listeners' wordings for the unit; never compose a
wording nobody heard. A listener that heard the frozen words supports the transcript. A listener's wording
may be chosen as a correction only when its unitBoundedByNeighbours is true; an unbounded wording may carry
the neighbours' words, so prefer undetermined. When the evidence does not settle the wording, answer
undetermined. Do not rewrite, improve, translate or interpret beyond
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


def _align(a: list[str], b: list[str]) -> list[tuple[int | None, int | None]]:
    """Minimum-edit alignment of two token lists as (i, j) pairs; None marks a deletion or insertion."""
    n, m = len(a), len(b)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i
    for j in range(1, m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(cost[i - 1][j - 1] + (a[i - 1] != b[j - 1]), cost[i - 1][j] + 1, cost[i][j - 1] + 1)
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def _contains_run(haystack: list[str], needle: list[str]) -> int:
    """How many times ``needle`` occurs as a contiguous run in ``haystack``."""
    if not needle or len(needle) > len(haystack):
        return 0
    return sum(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def locate_unit(before: list[str], unit: list[str], after: list[str], heard: str) -> dict[str, Any]:
    """What a listener heard for the doubted unit, bounded by its neighbours' frozen words.

    The whole clip transcript is aligned with the frozen words of the clip's
    units; the unit's stretch is what lies between the last word heard for
    the unit before and the first word heard for the unit after. A clip edge
    bounds the stretch when the unit has no neighbour on that side. The
    stretch is ``bounded`` only when each neighbour was mostly heard and the
    unit's words do not recur elsewhere in the clip, so an identical phrase in
    a neighbour can never stand in for an inaudible unit.
    """
    rows = [(token, word) for token, word in ((_normal(word), word) for word in _words(heard)) if token]
    heard_tokens = [token for token, _ in rows]
    empty = {'text': '', 'tokens': [], 'similarity': 0.0, 'bounded': False,
             'boundary': {'before': None, 'after': None, 'reason': 'nothing_heard'}}
    if not unit or not rows:
        return empty
    frozen = before + unit + after
    a_start, a_end = len(before), len(before) + len(unit)
    pairs = _align(frozen, heard_tokens)
    matched_before = sum(1 for i, j in pairs if i is not None and j is not None and i < a_start and frozen[i] == heard_tokens[j])
    matched_after = sum(1 for i, j in pairs if i is not None and j is not None and i >= a_end and frozen[i] == heard_tokens[j])
    before_js = [j for i, j in pairs if i is not None and j is not None and i < a_start]
    after_js = [j for i, j in pairs if i is not None and j is not None and i >= a_end]
    j_start = max(before_js) + 1 if before_js else 0
    j_end = min(after_js) if after_js else len(rows)
    window = rows[j_start:j_end]
    window_tokens = [token for token, _ in window]
    ratio = difflib.SequenceMatcher(None, unit, window_tokens, autojunk=False).ratio()
    before_share = None if not before else round(matched_before / len(before), 6)
    after_share = None if not after else round(matched_after / len(after), 6)
    reason = None
    if _contains_run(before, unit) or _contains_run(after, unit) or _contains_run(heard_tokens, unit) > 1:
        reason = 'phrase_repeated_in_clip'
    elif (before_share is not None and before_share < NEIGHBOUR_MATCH_MIN) or \
            (after_share is not None and after_share < NEIGHBOUR_MATCH_MIN):
        reason = 'neighbour_not_heard'
    return {'text': ' '.join(word for _, word in window), 'tokens': window_tokens, 'similarity': round(ratio, 6),
            'bounded': reason is None, 'boundary': {'before': before_share, 'after': after_share, 'reason': reason}}


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

def _route_identity(route: dict[str, Any] | None) -> dict[str, Any] | None:
    """The selected OpenAI Project without its secret: environment, project id and credential alias."""
    if route is None:
        return None
    return {key: route[key] for key in ('environment', 'projectId', 'credentialAlias')}


def _route_key(route: dict[str, Any] | None) -> str:
    """Namespaces cached answers by the selected OpenAI Project, so dev answers never serve prod."""
    return 'unrouted' if route is None else f"{route['environment']}-{route['projectId']}"


def _wav_seconds(wav: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav)) as handle:
            return handle.getnframes() / handle.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise SourceAdjudicationError('listener_clip_not_wav') from exc


class OpenAiTranscribeListener:
    """``gpt-transcribe`` through the selected OpenAI Project; it never sees the frozen text.

    Runs only under ``scripts/run_with_openai_environment.py``; the key is read from
    the environment the launcher sets. ``max_calls`` caps new paid requests."""

    name = model = 'gpt-transcribe'

    def __init__(self, *, cache: Path, max_calls: int, budget: dict[str, Any] | None = None):
        from scripts import machine_qc_audio_transports as transports
        from scripts import sermon_openai_runtime as runtime
        self.route = _route_identity(runtime.selected_route())
        _require(self.route is not None, 'openai_environment_launcher_required')
        self.cache = transports.CallCache(cache, paid=True)
        self.max_calls, self.calls = max_calls, 0
        # A new paid request dispatches only through the run's bound budget (``load_budget_authorization``);
        # without one the listener may replay its cache and nothing else.
        self.budget = budget
        self.operations = self.cache.root / 'operations.json'
        self.fields = [('model', self.model), ('response_format', 'json'), ('prompt', LISTEN_PROMPT),
                       ('languages[]', 'en')]

    def identity(self) -> dict[str, Any]:
        # The route is part of the identity, so a cached dev re-listen is never served to a prod run.
        return {'backend': 'openai-api', 'endpoint': '/v1/audio/transcriptions', 'model': self.model,
                'language': 'en', 'promptSha256': _sha(LISTEN_PROMPT.encode('utf-8')), 'route': self.route}

    def _operations_table(self) -> dict[str, str]:
        table = _load(self.operations) if self.operations.is_file() else {}
        _require(isinstance(table, dict) and all(isinstance(v, str) for v in table.values()),
                 'listener_operations_corrupt')
        return table

    def _operation(self, audio_sha: str) -> str:
        """The ledger operation of one clip, ``asr.NNNN`` in first-heard order, kept across a resumed run."""
        from scripts import english_source_judge_cache as judge_cache
        table = self._operations_table()
        if audio_sha not in table:
            _require(len(table) < 9999, 'listener_operation_cap')
            table[audio_sha] = f'asr.{len(table) + 1:04d}'
            judge_cache._atomic(self.operations, table)
        return table[audio_sha]

    def _request(self, wav: bytes) -> tuple[bytes, str, dict[str, Any]]:
        """The multipart body, its content type and the ledger identity of one clip's request."""
        from scripts import machine_qc_audio_transports as transports
        body, content_type = transports._multipart(self.fields, wav)
        identity = {'schemaVersion': LISTEN_REQUEST_SCHEMA, 'model': self.model,
                    'endpoint': transports.TRANSCRIBE_URL, 'audioSha256': _sha(wav),
                    'inputDurationSeconds': round(_wav_seconds(wav), 3), 'requestBodySha256': _sha(body),
                    'listener': self.identity()}
        return body, content_type, identity

    def _returned(self, wav: bytes) -> bool:
        """Whether the ledger already holds this clip's returned response (read only; nothing is numbered)."""
        known = self._operations_table().get(_sha(wav))
        return known is not None and self.budget['store'].returned(known, self._request(wav)[2])

    def _send(self, wav: bytes) -> dict[str, Any]:
        from scripts import machine_qc_audio_transports as transports
        from scripts import sermon_transcription_request as transcription
        _require(self.budget is not None, 'budget_authorization_required')
        body, content_type, identity = self._request(wav)
        audio_sha, seconds = _sha(wav), _wav_seconds(wav)
        # Reserved before dispatch, like the Layer 1 transcription: one request, its wall time and the
        # duration-billed minutes at the frozen planning price; never a token dimension.
        bounds = {'requests': 1, 'wallTimeMs': transcription.WALL_TIME_MS,
                  'costMicrousd': max(1, math.ceil(seconds / 60)) * transcription.MICROUSD_PER_MINUTE}
        store = self.budget['store']
        if not self._returned(wav):
            # The cap counts new paid requests only: a response the ledger already holds for this clip
            # replays at no cost, so a resumed run with ``--max-api-calls 0`` still recovers it.
            _require(self.calls < self.max_calls, 'listener_call_cap_reached')
            self.calls += 1
        response = store.call(
            operation=self._operation(audio_sha), identity=identity, bounds=bounds, request=body,
            api_key=os.environ.get('OPENAI_API_KEY', ''), content_type=content_type,
            endpoint=transports.TRANSCRIBE_URL)
        _require(isinstance(response, dict) and isinstance(response.get('text'), str), 'listener_returned_no_text')
        return {'text': response['text'], 'usage': response.get('usage')}

    def transcribe(self, wav: bytes) -> str:
        audio_sha = _sha(wav)
        key = policies.canonical_sha256({'listener': self.name, 'audioSha256': audio_sha, 'identity': self.identity()})
        done = self.cache.get(key)
        if done is None:
            _require(self.budget is not None, 'budget_authorization_required')
            # The budget ledger is the paid-call record (reserved, live, returned or unknown) and replays a
            # returned response itself; a refused reservation leaves nothing to reconcile. The cache keeps
            # the returned text so the next run reads it without opening the ledger.
            request = {'audioSha256': audio_sha, 'listener': self.name}
            started = (self.cache.root / key / 'started.json').exists()
            # A started marker settles only from a response the ledger already holds. Without one the marker
            # may come from a run that sent the request before this ledger existed, so its outcome is unknown:
            # it is never sent again and waits for an operator to reconcile it.
            _require(not started or self._returned(wav), 'source_marker_outcome_unknown')
            response = self._send(wav)
            if started:
                # A run that died after the ledger kept the returned text but before this cache recorded it
                # leaves the started marker. The ledger replayed that operation above; bind its response to
                # the marker instead of treating the paid clip as an unknown outcome for good.
                done = self.cache.reconcile(key, request, response)
            else:
                done = self.cache.run(key, request, lambda: response)
        return done['text'].strip()


class QwenListener:
    """Local Qwen3-ASR, the Layer 3 screening model, as the second independent listener.

    Local model compute runs on Spark (compute policy): the weights load only
    once a live Spark exclusive session owns this process, so the CLI with
    ``--listener qwen`` runs on Spark inside that session, never on a Mac. There
    is no cross-host adapter; a cached re-listen replays without a session."""

    name = model = 'qwen3-asr'
    host = 'spark_exclusive_session'

    def __init__(self, model_path: Path, *, cache: Path, identity_probe: Callable[[Path], dict[str, Any]] | None = None,
                 session_verifier: Callable[[], dict[str, Any]] | None = None):
        from scripts import machine_qc_audio_transports as transports
        self.model_path = Path(model_path).resolve()
        weights = self.model_path / 'model.safetensors'
        _require(weights.is_file(), 'qwen_weights_missing')
        self.model_revision = f'model.safetensors:sha256:{file_sha256(weights)}'
        # The listener's identity is its whole runtime: weights, model metadata
        # (config, tokenizer, preprocessor), package versions and inference settings.
        probe = identity_probe or transports.qwen_inference_identity
        self.runtime = probe(self.model_path)
        _require(isinstance(self.runtime, dict) and self.runtime.get('backend') == 'qwen-asr-local',
                 'qwen_runtime_identity')
        self.cache = transports.CallCache(cache, paid=False)
        self.session_verifier = session_verifier
        # The live session once admitted, else the session restored from the first cached re-listen.
        self.session_receipt: dict[str, Any] | None = None
        # Every distinct session whose transcripts this run used, cached or live, in first-use order.
        self.sessions: list[dict[str, Any]] = []
        self._model = None

    def identity(self) -> dict[str, Any]:
        return {'backend': 'qwen-asr-local', 'host': self.host, 'model': self.model,
                'modelRevision': self.model_revision, 'runtime': self.runtime, 'settings': dict(QWEN_SETTINGS)}

    def _admit(self) -> None:
        """A live Spark exclusive session must own this process before any CUDA or model load."""
        from scripts.production_spark_admission import require_bound_model_session
        from scripts.spark_exclusive_session import SessionError
        try:
            receipt = require_bound_model_session(verifier=self.session_verifier)
        except SessionError as exc:
            raise SourceAdjudicationError('qwen_requires_bound_spark_exclusive_session') from exc
        _require(isinstance(receipt, dict), 'qwen_session_receipt')
        self.session_receipt = {key: receipt.get(key) for key in ('sessionId', 'jobId', 'owner', 'bootId')
                                if receipt.get(key) is not None}

    def _run(self, wav: bytes) -> str:
        if self._model is None:
            self._admit()
            import torch
            from qwen_asr import Qwen3ASRModel
            self._model = Qwen3ASRModel.from_pretrained(str(self.model_path), dtype=torch.bfloat16,
                                                        device_map=QWEN_SETTINGS['executionDevice'],
                                                        max_inference_batch_size=QWEN_SETTINGS['batchSize'],
                                                        max_new_tokens=QWEN_SETTINGS['maxNewTokens'])
        import soundfile as sf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'clip.wav'
            path.write_bytes(wav)
            audio, rate = sf.read(path, dtype='float32')
        values = self._model.transcribe(audio=(audio, rate), language=QWEN_SETTINGS['language'])
        _require(len(values) == 1 and isinstance(values[0].text, str), 'listener_output_cardinality')
        return values[0].text

    def transcribe(self, wav: bytes) -> str:
        audio_sha = _sha(wav)
        key = policies.canonical_sha256({'listener': self.name, 'audioSha256': audio_sha, 'identity': self.identity()})

        def listen() -> dict[str, Any]:
            text = self._run(wav)  # admits the session first; the entry records which session generated it
            _require(isinstance(self.session_receipt, dict), 'qwen_session_receipt')
            return {'text': text, 'session': self.session_receipt}
        entry = self.cache.run(key, {'audioSha256': audio_sha, 'listener': self.name}, listen)
        _require(isinstance(entry, dict) and isinstance(entry.get('text'), str) and isinstance(entry.get('session'), dict),
                 'qwen_cache_entry')
        if entry['session'] not in self.sessions:
            self.sessions.append(entry['session'])
        if self.session_receipt is None:
            # A resumed run serving this clip from cache keeps the bound compute identity that produced it.
            self.session_receipt = entry['session']
        return entry['text'].strip()


# ---------------------------------------------------------------- adjudicator

class SolAdjudicator:
    """One bounded JSON call per doubted unit, cached by request identity.

    Spend is bounded before dispatch: every payload carries the default request
    limits (worst-case tokens, default tier), ``max_calls`` caps the new paid
    requests of one run, and a cached answer is served without a call."""

    def __init__(self, *, api_key: str, cache: Path, model: str = MODEL, effort: str = EFFORT,
                 caller: Callable[..., dict[str, Any]] | None = None, max_calls: int | None = None,
                 budget: dict[str, Any] | None = None):
        _require(model in ADJUDICATOR_MODELS and effort in limits.MODEL_REASONING_EFFORTS[model],
                 'unsupported_adjudicator_model')
        _require(max_calls is None or (type(max_calls) is int and max_calls >= 0), 'adjudicator_call_cap')
        # The authorization pays for the model and effort it was approved for, and nothing else.
        _require(budget is None or budget.get('adjudicator') == {'model': model, 'reasoningEffort': effort},
                 'budget_authorization_binding_changed')
        # The request limits are the bound budget's approved tier; an unbound run (cache replay only)
        # always uses the default tier, which is what its receipt must then record.
        self.budget = budget
        self.limits = limits.validate_request_limits(
            budget['requestLimits'] if budget is not None else limits.DEFAULT_REQUEST_LIMITS)
        if caller is None:
            # A new paid request dispatches only through the bound budget's ledger; with no budget the
            # default caller refuses before any transport exists, so a cache miss cannot spend.
            caller = self._budgeted_call if budget is not None else _unbound_call
        self.api_key, self.cache, self.model, self.effort, self.caller = api_key, Path(cache), model, effort, caller
        self.max_calls, self.calls = max_calls, 0
        from scripts import sermon_openai_runtime as runtime
        self.route = _route_identity(runtime.selected_route())

    def _ledger_identity(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The ledger row's identity: the model the transport accounts for, the selected OpenAI Project
        and the request, so a response paid for under one Project is never replayed to a run on another
        (``source_operation_identity_changed``)."""
        return {'model': payload['model'], 'route': self.route, 'payload': payload}

    @staticmethod
    def _ledger_operation(payload: dict[str, Any]) -> str:
        from scripts import sermon_workflow_jobs as jobs
        return 'judge.' + jobs._digest(payload)

    def _budgeted_call(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        inputs = limits._input_upper_bound(payload)
        bounds = {'requests': 1, 'wallTimeMs': self.limits['wallTimeMs'],
                  'costMicrousd': limits._cost(payload['model'], inputs, self.limits['maxCompletionTokens'])}
        return self.budget['store'].call(
            operation=self._ledger_operation(payload), identity=self._ledger_identity(payload), bounds=bounds,
            request=json.dumps(payload, ensure_ascii=False).encode('utf-8'), api_key=key,
            content_type='application/json', endpoint=CHAT_URL)

    @property
    def route_key(self) -> str:
        return _route_key(self.route)

    def identity(self) -> dict[str, Any]:
        return {'model': self.model, 'reasoningEffort': self.effort, 'promptVersion': PROMPT_VERSION,
                'promptSha256': _sha(SYSTEM_PROMPT.encode('utf-8')),
                'requestLimits': dict(self.limits), 'maxNewCalls': self.max_calls,
                'route': self.route}

    def payload(self, question: dict[str, Any]) -> dict[str, Any]:
        payload = {'model': self.model, 'reasoning_effort': self.effort,
                   'response_format': {'type': 'json_object'},
                   'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                                {'role': 'user', 'content': json.dumps(question, ensure_ascii=False)}],
                   'max_completion_tokens': self.limits['maxCompletionTokens'],
                   'service_tier': self.limits['serviceTier']}
        # The strict transport refuses anything but a payload already carrying its worst-case cap.
        _require(limits.bounded_payload(payload, self.limits) == payload, 'adjudicator_payload_unbounded')
        return payload

    def decide(self, unit_id: str, question: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        from scripts import english_source_judge_cache as judge_cache
        from scripts import sermon_sentence_interpretation as contract
        payload, stage = self.payload(question), f'source-meaning-{self.route_key}-{unit_id}'
        request_hash = contract.json_sha256({'schemaVersion': judge_cache.RUN_SCHEMA, 'stage': stage,
                                             'payload': payload})
        path = self.cache.resolve() / 'cache' / f'{stage}-{request_hash}.json'
        cached, caller = path.is_file(), self.caller
        if not cached:
            # A response the ledger already holds replays at no cost and is not a new call for the cap.
            replay = self.budget is not None and self.budget['store'].returned(self._ledger_operation(payload),
                                                                                 self._ledger_identity(payload))
            marker = path.with_suffix('.started.json')
            # A started marker settles only from a response the ledger already holds. Without one the marker
            # may come from a run that sent the request directly, before this ledger existed, so its outcome is
            # unknown: it is never sent again and waits for an operator to reconcile it.
            _require(not marker.is_file() or self.budget is None or replay, 'source_marker_outcome_unknown')
            _require(replay or self.max_calls is None or self.calls < self.max_calls, 'adjudicator_call_cap_reached')
            # Refused before the cache writes its started marker, so an unbound run leaves nothing to reconcile.
            _require(self.caller is not _unbound_call, 'budget_authorization_required')
            if not replay:
                self.calls += 1
            if self.budget is not None and (marker.is_file() or self.caller == self._budgeted_call):
                # The ledger is the paid-call record, so it reserves and dispatches (or replays) before the cache
                # writes its marker: a refused reservation (bounds, authorization, session) leaves no marker
                # behind, and every marker this run writes has the ledger's returned response beside it.
                response = self._budgeted_call(self.api_key, payload)
                if marker.is_file():
                    # A run that died after the ledger kept the response but before the cache file was written
                    # left this marker; bind the replayed response into the cache instead of staying blocked.
                    judge_cache.reconcile_returned_response(marker_path=marker, response=response,
                                                            expected_request_sha256=request_hash,
                                                            requested_model=self.model)
                else:
                    caller = lambda _key, _payload: response  # noqa: E731
        result, request = judge_cache.cached_call(out=self.cache, stage=stage, payload=payload, api_key=self.api_key,
                                                  requested_model=self.model, caller=caller)
        return result, {**request, 'cached': cached, 'bounds': limits.request_bounds(payload, self.limits)}


def _unbound_call(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    raise SourceAdjudicationError('budget_authorization_required')


# ---------------------------------------------------------------- budget

def budget_binding(source: dict[str, Any], anchor: dict[str, Any], unit_ids: list[str], out_dir: Path, *,
                   model: str, effort: str) -> dict[str, Any]:
    """What a spend authorization must name: the frozen package, the doubted units, the code closure,
    the selected OpenAI Project, the adjudicator's model and reasoning effort and the ledger root under
    the output directory. Any other run is a different authorization: in particular one approved for dev
    cannot be loaded, replayed or spent under prod, one approved for Sol at medium effort cannot pay for
    another model or effort, and the binding exists only under the environment launcher."""
    from scripts import canonical_layer2_controller as controller
    from scripts import sermon_openai_runtime as runtime
    _require(model in ADJUDICATOR_MODELS and effort in limits.MODEL_REASONING_EFFORTS[model],
             'unsupported_adjudicator_model')
    route = _route_identity(runtime.selected_route())
    _require(route is not None, 'openai_environment_launcher_required')
    return {'bindings': {'source.json': policies.canonical_sha256(source), 'anchor.json': policies.canonical_sha256(anchor)},
            'doubtedUnits': sorted(unit_ids), 'codeIdentitySha256': controller.code_identity(), 'route': route,
            'adjudicator': {'model': model, 'reasoningEffort': effort},
            'budgetRoot': str(Path(out_dir).resolve() / BUDGET_DIR)}


def _authorization_identity(path: Path, *, binding: dict[str, Any]) -> dict[str, Any]:
    """What the authorization file and its approval receipt say now, refused unless they bind this run."""
    value = _load(path)
    _require(isinstance(value, dict) and set(value) == {'schemaVersion', 'binding', 'authority', 'approvalReceipt'}
             and value['schemaVersion'] == BUDGET_SCHEMA and isinstance(value['authority'], dict)
             and set(value['authority']) == {'approvalSha256', 'globalBounds', 'requestLimits'}
             and isinstance(value['approvalReceipt'], str), 'budget_authorization_schema')
    _require(value['binding'] == binding, 'budget_authorization_binding_changed')
    authority = value['authority']
    approval_path = (path.parent / value['approvalReceipt']).resolve()
    _require(approval_path.is_file(), 'budget_approval_not_bound')
    approval = _load(approval_path)
    _require(file_sha256(approval_path) == authority['approvalSha256'] and isinstance(approval, dict)
             and approval.get('schemaVersion') == BUDGET_APPROVAL_SCHEMA
             and approval.get('binding') == {**binding, 'globalBounds': authority['globalBounds'],
                                             'requestLimits': authority['requestLimits']}
             and approval.get('humanApproval') is True and approval.get('decision') == 'approved'
             and approval.get('operatorEvidence') and approval.get('reviewedBy') and approval.get('reviewedAt'),
             'budget_approval_not_bound')
    return {'schemaVersion': BUDGET_SCHEMA, 'authorizationSha256': file_sha256(path),
            'approvalSha256': authority['approvalSha256'], 'budgetRoot': binding['budgetRoot'],
            'globalBounds': dict(authority['globalBounds']), 'requestLimits': dict(authority['requestLimits'])}


def load_budget_authorization(path: Path, *, binding: dict[str, Any], transport: Any = None) -> dict[str, Any]:
    """The human-approved spend authority for exactly this run, with its durable ledger.

    Shaped like the Layer 1 source budget: the authorization names the binding, the global
    bounds and the request limits; the approval receipt it hashes into its authority repeats
    them with a human decision. Every paid call of the run then dispatches through one
    ``SourceBudget`` ledger under ``budgetRoot``: reserved before dispatch, replayed after,
    never retried on an unknown outcome. The ledger re-reads the authorization, its approval
    and the code closure before every reservation, dispatch and returned response, so a file
    replaced or code changed after this load refuses (``budget_authorization_changed`` /
    ``budget_authorization_binding_changed``) before the ledger moves. ``transport`` is a
    test seam only."""
    from scripts import canonical_layer2_controller as controller
    from scripts import sermon_source_budget as source_budget
    path = Path(path).resolve()
    identity = _authorization_identity(path, binding=binding)

    def verify() -> None:
        current = _authorization_identity(path, binding={**binding, 'codeIdentitySha256': controller.code_identity()})
        _require(current == identity, 'budget_authorization_changed')

    authority = {key: identity[key] for key in ('approvalSha256', 'globalBounds', 'requestLimits')}
    store = source_budget.SourceBudget(Path(binding['budgetRoot']), authority, verify=verify, transport=transport)
    return {**identity, 'store': store, 'adjudicator': dict(binding['adjudicator'])}


BUDGET_IDENTITY_KEYS = ('schemaVersion', 'authorizationSha256', 'approvalSha256', 'budgetRoot', 'globalBounds',
                        'requestLimits')


def budget_identity(budget: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the receipt records of the authority a run spent under; the ledger store stays out."""
    return None if budget is None else {key: budget[key] for key in BUDGET_IDENTITY_KEYS}


def _is_budget_identity(value: Any) -> bool:
    """Whether ``value`` could have come from ``load_budget_authorization``: two file hashes, an absolute
    ledger root named ``budget``, ledger-valid global bounds and a supported request-limit tier."""
    from scripts import sermon_source_budget as source_budget
    if not (isinstance(value, dict) and set(value) == set(BUDGET_IDENTITY_KEYS) and value['schemaVersion'] == BUDGET_SCHEMA
            and all(isinstance(value[key], str) and re.fullmatch('[a-f0-9]{64}', value[key])
                    for key in ('authorizationSha256', 'approvalSha256'))
            and isinstance(value['budgetRoot'], str) and Path(value['budgetRoot']).is_absolute()
            and Path(value['budgetRoot']).name == BUDGET_DIR):
        return False
    bounds = value['globalBounds']
    if not (isinstance(bounds, dict) and set(bounds) == set(source_budget.METRICS)
            and all(type(v) is int and 0 < v <= 10**15 for v in bounds.values())):
        return False
    try:
        limits.validate_request_limits(value['requestLimits'])
    except ValueError:
        return False
    return True


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
        # An unbounded window may carry the neighbours' words; it can never replace one unit.
        _require(by_name[heard_by]['bounded'], 'corrected_text_unbounded')
    else:
        _require(corrected is None, 'corrected_text_without_correction')
        # A confirmation rests on the frozen words or on a listener that heard exactly them.
        _require(decision != 'transcript_confirmed' or heard_by == 'frozen'
                 or by_name[heard_by]['unitTokens'] == frozen, 'confirmed_by_disagreeing_listener')
    return {'decision': decision, 'heardBy': heard_by, 'correctedText': corrected.strip() if corrected else None,
            'meaningNote': note.strip(), 'reason': reason.strip()}


# ---------------------------------------------------------------- adjudication

def _units(anchor: dict[str, Any]) -> list[dict[str, Any]]:
    units = anchor.get('sourceUnits')
    _require(isinstance(units, list) and units and all(
        isinstance(u, dict) and isinstance(u.get('sourceUnitId'), str) and isinstance(u.get('english'), str)
        for u in units), 'anchor_units')
    return units


def _source_asr_model(source: dict[str, Any]) -> str | None:
    """The model that produced the Layer 1 transcript, when the package records one."""
    model = source.get('transcript', {}).get('provenance', {}).get('model')
    if isinstance(model, str) and model.strip() and model.strip().lower() != 'unknown':
        return model.strip()
    return None


def listener_independence(listener_models: list[str], source_model: str | None) -> dict[str, Any]:
    """Whether the listeners can confirm the transcript without the adjudicator.

    One listener that is the same model as the Layer 1 transcription (or an
    unknown one) only repeats its own hearing; independence needs two distinct
    listener models, or one model known to differ from the source ASR."""
    distinct = sorted(set(listener_models))
    independent = [model for model in distinct if source_model is not None and model != source_model]
    if len(distinct) >= 2:
        reason = 'two_distinct_listener_models'
    elif independent:
        reason = 'listener_differs_from_source_asr'
    else:
        reason = 'single_listener_not_independent_of_source_asr'
    return {'sourceAsrModel': source_model, 'listenerModels': distinct, 'independentOfSourceAsr': independent,
            'independent': len(distinct) >= 2 or bool(independent), 'reason': reason}


def _media_binding(source: dict[str, Any]) -> tuple[dict[str, Any], float]:
    media = source.get('source', {}).get('media')
    window = source.get('source', {}).get('approvedWindow')
    _require(isinstance(media, dict) and isinstance(media.get('sha256'), str)
             and type(media.get('sizeBytes')) is int, 'source_media_identity')
    _require(isinstance(window, dict) and isinstance(window.get('startSeconds'), (int, float)), 'source_window')
    return media, float(window['startSeconds'])


def _question(units: list[dict[str, Any]], index: int, independence: dict[str, Any],
              heard: list[dict[str, Any]]) -> dict[str, Any]:
    """What the adjudicator is asked about ``units[index]``; a v2 receipt's request cache must hold exactly this.

    The doubted unit with its neighbouring text, the clip's units and length,
    the listeners' independence and, per listener, what it heard and how the
    neighbours bound it. ``heard`` rows are the receipt's hearing rows."""
    unit = units[index]
    low, high = max(0, index - CLIP_CONTEXT_UNITS), min(len(units) - 1, index + CLIP_CONTEXT_UNITS)
    context = [{'sourceUnitId': units[i]['sourceUnitId'], 'english': units[i]['english'],
                'position': 'doubted' if i == index else 'before' if i < index else 'after'}
               for i in range(max(0, index - TEXT_CONTEXT_UNITS), min(len(units), index + TEXT_CONTEXT_UNITS + 1))]
    return {'schemaVersion': QUESTION_SCHEMA, 'sourceUnitId': unit['sourceUnitId'], 'frozenText': unit['english'],
            'context': context, 'listenerIndependence': independence,
            'clip': {'sourceUnitIds': [units[i]['sourceUnitId'] for i in range(low, high + 1)],
                     'seconds': round(float(units[high]['end']) - float(units[low]['start']), 3)},
            'listeners': [{'name': row['listener'], 'model': row['model'], 'heardClip': row['text'],
                           'heardForUnit': row['unitWindow'], 'similarityToFrozen': row['similarityToFrozen'],
                           'agreesWithFrozen': row['agreesWithFrozen'], 'unitBoundedByNeighbours': row['bounded'],
                           'boundary': row['boundary']} for row in heard]}


def _require_bound_anchor(source: dict[str, Any], anchor: dict[str, Any]) -> None:
    """The anchor must be the one the English Source Package names, built on the package's transcript.

    Two files hashing separately prove nothing about each other: a stale or
    mixed anchor would cut the wrong media times and correct the wrong words."""
    expected = source.get('anchors', {}).get('artifact', {}).get('jsonSha256')
    _require(isinstance(expected, str) and policies.canonical_sha256(anchor) == expected, 'anchor_not_bound_to_source')
    transcript = source.get('transcript', {}).get('artifact', {}).get('sha256')
    built_on = anchor.get('input', {}).get('mfaSegmentsSha256')
    if transcript is not None or built_on is not None:
        _require(isinstance(transcript, str) and transcript == built_on, 'anchor_transcript_binding_changed')


def adjudicate(source: dict[str, Any], anchor: dict[str, Any], *, unit_ids: list[str], media: Path | None,
               listeners: list[Any], adjudicator: SolAdjudicator | None, out_dir: Path,
               cut: Callable[[Path, float, float], bytes] = cut_clip,
               now: datetime | None = None, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """Adjudicate the doubted units; write clips and re-listens under ``out_dir``; return the receipt.

    Unit times in the anchor are relative to the approved window, so each clip
    is cut at ``window start + unit time`` of the bound media. ``media`` may be
    None only when ``cut`` does not read it (tests)."""
    _require(listeners, 'listeners_required')
    _require(len(unit_ids) == len(set(unit_ids)) and unit_ids, 'unit_ids')
    units = _units(anchor)
    by_id = {u['sourceUnitId']: i for i, u in enumerate(units)}
    _require(all(uid in by_id for uid in unit_ids), 'unit_unknown')
    _require_bound_anchor(source, anchor)
    media_info, offset = _media_binding(source)
    independence = listener_independence([listener.model for listener in listeners], _source_asr_model(source))
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
        before = [t for i in range(low, index) for t in tokens(units[i]['english'])]
        after = [t for i in range(index + 1, high + 1) for t in tokens(units[i]['english'])]
        heard: list[dict[str, Any]] = []
        for listener in listeners:
            text = listener.transcribe(wav)
            window = locate_unit(before, frozen, after, text)
            row = {'listener': listener.name, 'model': listener.model, 'clipSha256': clip_sha, 'text': text,
                   'unitWindow': window['text'], 'unitTokens': window['tokens'],
                   'similarityToFrozen': window['similarity'], 'agreesWithFrozen': window['tokens'] == frozen,
                   'bounded': window['bounded'], 'boundary': window['boundary']}
            heard.append(row)
            (out_dir / 'listeners' / f'{uid}.{listener.name}.json').write_text(
                json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Deterministic confirmation needs listeners independent of the Layer 1 transcription,
        # every one hearing the frozen words inside a stretch its neighbours bound; anything
        # else (an unbounded match, a lone listener repeating the source ASR) goes to the adjudicator.
        if independence['independent'] and all(row['agreesWithFrozen'] and row['bounded'] for row in heard):
            verdict = {'decision': 'transcript_confirmed', 'heardBy': 'frozen', 'correctedText': None,
                       'meaningNote': CONFIRMED_NOTE,
                       'reason': f'{len(heard)} independent listener(s) heard exactly the frozen words '
                                 f"between the words of the neighbouring units ({independence['reason']})"}
            decided_by, request = 'listeners_agree_with_transcript', None
        else:
            _require(adjudicator is not None, 'adjudicator_required')
            question = _question(units, index, independence, heard)
            result, request = adjudicator.decide(uid, question)
            verdict = _checked_answer(result, frozen, heard)
            decided_by = 'model'
        timing = {'start': float(unit['start']), 'end': float(unit['end'])}
        if unit.get('referenceChunkId') is not None:
            timing['referenceChunkId'] = str(unit['referenceChunkId'])
        rows.append({'sourceUnitId': uid, 'sourceSentenceId': unit.get('sourceSentenceId'),
                     'frozenText': unit['english'], 'unit': timing,
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
        'listeners': [{'name': item.name, 'model': item.model, 'identity': item.identity(),
                       'session': getattr(item, 'session_receipt', None),
                       'sessions': getattr(item, 'sessions', None)} for item in listeners],
        'listenerIndependence': independence,
        'adjudicator': None if adjudicator is None else adjudicator.identity(),
        'budget': budget_identity(budget),
        'units': rows,
        'counts': {'units': len(rows), **{d: sum(r['decision'] == d for r in rows) for d in DECISIONS}},
        'notice': ('Machine evidence from the bound audio; not human approval. A corrected unit changes '
                   'Layer 1 through sermon-source-text-review-v2 and invalidates every locale downstream. '
                   'A confirmed or undetermined unit keeps the frozen text; meaning-notes.json carries its '
                   "meaningNote for the translator's and reviewer's repair instruction."),
    }
    return receipt


def receipt_sha256(receipt: dict[str, Any]) -> str:
    return policies.canonical_sha256(receipt)


UNIT_DECIDERS = {'listeners_agree_with_transcript', 'model'}


def validate_receipt(receipt: Any, *, source: dict[str, Any] | None = None, anchor: dict[str, Any] | None = None,
                     media_sha256: str | None = None, cache: Path | None = None) -> dict[str, Any]:
    """Refuse anything but a receipt this module wrote, bound to the package and media it names.

    The role string and signature prove nothing by themselves. The receipt must
    carry its own evidence (listeners with identities, every unit's hearings,
    a correction that one bounded listener actually heard), and when the
    adjudicated ``source``/``anchor`` or the media hash are supplied, its
    bindings must be theirs: a stale or synthetic receipt for other inputs
    is refused before any patch of Layer 1 or any repair note is admitted.
    In a v2 receipt a model-decided row is accepted only with ``cache`` (the
    adjudicator's request cache, ``<out-dir>/cache``): its verdict is derived
    again from the hash-bound response the row names, so an edited decision is
    refused, and with ``anchor`` the cached question must be the one this
    receipt and anchor ask. A v1 receipt was written before that contract and
    keeps its rules: its model rows name a request, nothing more is checked. Those
    rules apply only to a receipt signed by an implementation that wrote v1
    (``V1_IMPLEMENTATIONS``)."""
    _require(isinstance(receipt, dict) and receipt.get('schemaVersion') in (SCHEMA_V1, SCHEMA)
             and receipt.get('decidedByRole') == ROLE and receipt.get('humanApproval') is False, 'receipt_schema')
    current = receipt['schemaVersion'] == SCHEMA
    version, implementation = receipt.get('version'), receipt.get('implementationSha256')
    _require(isinstance(version, str) and isinstance(implementation, str) and len(implementation) == 64
             and receipt.get('decidedBy') == f'source_meaning_machine_adjudication {version} {implementation[:16]}',
             'receipt_signature')
    # The schema label alone never selects the older rules: a v1 receipt must name an implementation that
    # wrote v1, with the version it signed. A v2 receipt relabelled v1 names this or a later implementation.
    _require(current or V1_IMPLEMENTATIONS.get(implementation) == version, 'receipt_v1_implementation_unknown')
    bindings, media = receipt.get('bindings'), receipt.get('media')
    _require(isinstance(bindings, dict) and set(bindings) == {'source.json', 'anchor.json'}
             and all(isinstance(v, str) and len(v) == 64 for v in bindings.values())
             and isinstance(media, dict) and isinstance(media.get('sha256'), str)
             and type(media.get('sizeBytes')) is int and isinstance(media.get('offsetSeconds'), (int, float)),
             'receipt_bindings')
    # A v2 receipt always records its budget: ``null`` for a cache-only run, otherwise an authorization
    # identity this module could have written (every field is checked, not only the key set and the schema
    # string). A v1 receipt was written before the budget contract and carries none.
    if current:
        _require('budget' in receipt and (receipt['budget'] is None or _is_budget_identity(receipt['budget'])),
                 'receipt_budget')
    else:
        _require('budget' not in receipt, 'receipt_budget')
    listeners, independence = receipt.get('listeners'), receipt.get('listenerIndependence')
    _require(isinstance(listeners, list) and listeners
             and all(isinstance(row, dict) and isinstance(row.get('name'), str) and isinstance(row.get('model'), str)
                     and isinstance(row.get('identity'), dict) for row in listeners)
             and isinstance(independence, dict) and isinstance(independence.get('independent'), bool),
             'receipt_listeners')
    # The stored independence verdict proves nothing by itself: derive it again from the listener
    # models and the source ASR model the receipt names.
    _require(independence == listener_independence([row['model'] for row in listeners],
                                                   independence.get('sourceAsrModel')), 'receipt_listeners')
    names = sorted(row['name'] for row in listeners)
    models = {row['name']: row['model'] for row in listeners}
    adjudicator, units = receipt.get('adjudicator'), receipt.get('units')
    if current and adjudicator is not None:
        _adjudicator_runtime(adjudicator, receipt['budget'])
    _require(isinstance(units, list) and units, 'receipt_units')
    seen: set[str] = set()
    asked: dict[str, dict[str, Any]] = {}
    for row in units:
        _require(isinstance(row, dict) and isinstance(row.get('sourceUnitId'), str) and row['sourceUnitId'] not in seen
                 and isinstance(row.get('frozenText'), str) and row.get('decision') in DECISIONS
                 and isinstance(row.get('meaningNote'), str) and row['meaningNote'].strip()
                 and isinstance(row.get('unit'), dict)
                 and all(isinstance(row['unit'].get(k), (int, float)) for k in ('start', 'end'))
                 and row.get('decidedBy') in UNIT_DECIDERS, 'receipt_unit')
        seen.add(row['sourceUnitId'])
        heard = row.get('heard')
        _require(isinstance(heard, list) and sorted(h.get('listener') for h in heard if isinstance(h, dict)) == names
                 and all(isinstance(h.get('unitTokens'), list) and isinstance(h.get('bounded'), bool)
                         and isinstance(h.get('agreesWithFrozen'), bool) and isinstance(h.get('text'), str)
                         for h in heard), 'receipt_unit_hearings')
        # A v2 hearing names the model of the listener it belongs to; the cached question carries it.
        _require(not current or all(h.get('model') == models[h['listener']] for h in heard), 'receipt_unit_hearings')
        # Agreement is a fact about the words heard, not a stored flag.
        frozen_tokens = tokens(row['frozenText'])
        _require(all(h['agreesWithFrozen'] == (h['unitTokens'] == frozen_tokens) for h in heard),
                 'receipt_unit_hearings')
        by_name = {h['listener']: h for h in heard}
        if row['decidedBy'] == 'model':
            _require(isinstance(adjudicator, dict) and isinstance(row.get('request'), dict), 'receipt_decision_evidence')
            if current:
                _require(cache is not None, 'receipt_model_response_missing')
                asked[row['sourceUnitId']] = _verify_model_verdict(row, adjudicator, cache, frozen_tokens)
        else:
            _require(row['decision'] == 'transcript_confirmed' and independence['independent']
                     and all(h['agreesWithFrozen'] and h['bounded'] for h in heard), 'receipt_decision_evidence')
        if row['decision'] == 'transcript_corrected':
            corrected, heard_by = row.get('correctedText'), row.get('heardBy')
            _require(isinstance(corrected, str) and corrected.strip() and heard_by in by_name
                     and by_name[heard_by]['bounded'] and tokens(corrected) == by_name[heard_by]['unitTokens']
                     and tokens(corrected) != tokens(row['frozenText']), 'receipt_correction_not_heard')
        else:
            _require(row.get('correctedText') is None, 'receipt_correction_not_heard')
            heard_by = row.get('heardBy')
            _require(row['decision'] != 'transcript_confirmed' or heard_by == 'frozen'
                     or (heard_by in by_name and by_name[heard_by]['agreesWithFrozen']), 'receipt_decision_evidence')
    if media_sha256 is not None:
        _require(media['sha256'] == media_sha256, 'receipt_media_binding_changed')
    if source is not None:
        info, offset = _media_binding(source)
        _require(media['sha256'] == info['sha256'] and media['sizeBytes'] == info['sizeBytes']
                 and float(media['offsetSeconds']) == offset, 'receipt_media_binding_changed')
        _require(bindings['source.json'] == policies.canonical_sha256(source), 'receipt_source_binding_changed')
        _require(independence['sourceAsrModel'] == _source_asr_model(source), 'receipt_source_binding_changed')
    if anchor is not None:
        _require(bindings['anchor.json'] == policies.canonical_sha256(anchor), 'receipt_anchor_binding_changed')
        if source is not None:
            _require_bound_anchor(source, anchor)
        all_units = _units(anchor)
        position = {u['sourceUnitId']: i for i, u in enumerate(all_units)}
        for row in units:
            index = position.get(row['sourceUnitId'])
            unit = all_units[index] if index is not None else None
            _require(unit is not None and unit['english'] == row['frozenText']
                     and abs(float(unit['start']) - float(row['unit']['start'])) < 1e-6
                     and abs(float(unit['end']) - float(row['unit']['end'])) < 1e-6, 'receipt_unit_not_in_anchor')
            # What each listener heard for the unit, and whether its neighbours bound it, is derived
            # again from the listener's own transcript and the anchor's neighbouring units.
            low, high = max(0, index - CLIP_CONTEXT_UNITS), min(len(all_units) - 1, index + CLIP_CONTEXT_UNITS)
            before = [t for i in range(low, index) for t in tokens(all_units[i]['english'])]
            after = [t for i in range(index + 1, high + 1) for t in tokens(all_units[i]['english'])]
            frozen_tokens = tokens(unit['english'])
            for h in row['heard']:
                window = locate_unit(before, frozen_tokens, after, h['text'])
                _require(window['tokens'] == h['unitTokens'] and window['bounded'] == h['bounded'],
                         'receipt_unit_hearings')
                if current:
                    _require(window == {'text': h.get('unitWindow'), 'tokens': h['unitTokens'],
                                        'similarity': h.get('similarityToFrozen'), 'bounded': h['bounded'],
                                        'boundary': h.get('boundary')}, 'receipt_unit_hearings')
            if not current:
                continue
            # The clip the row names is the anchor's, and the adjudicator was asked exactly what this
            # receipt and anchor ask: a cache answered for another fixture's context, clip or hearings
            # cannot vouch for this unit even when its raw transcripts match.
            clip = row.get('clip')
            _require(isinstance(clip, dict)
                     and clip.get('sourceUnitIds') == [all_units[i]['sourceUnitId'] for i in range(low, high + 1)]
                     and clip.get('windowStart') == float(all_units[low]['start'])
                     and clip.get('windowEnd') == float(all_units[high]['end']), 'receipt_unit_not_in_anchor')
            if row['decidedBy'] == 'model':
                _require(asked[row['sourceUnitId']] == _question(all_units, index, independence, row['heard']),
                         'receipt_model_question_changed')
    corrected_ids = [row['sourceUnitId'] for row in units if row['decision'] == 'transcript_corrected']
    return {'receiptSha256': receipt_sha256(receipt), 'decidedBy': receipt['decidedBy'], 'bindings': dict(bindings),
            'mediaSha256': media['sha256'], 'units': [row['sourceUnitId'] for row in units],
            'correctedUnits': corrected_ids, 'listeners': names, 'independent': independence['independent']}


def _adjudicator_runtime(adjudicator: Any, budget: dict[str, Any] | None) -> None:
    """A v2 adjudicator identity names a route the environment launcher could select and the one tier
    the run could have used: the tier its budget approved, or the default tier of an unbound run. The
    cache shows a request's completion cap and service tier but not its input cap or wall time, so the
    whole tier is held to the value the run had to use; each cached request is then held to both
    (``_verify_model_verdict``), so a receipt cannot claim another Project or tier than its cache was
    asked under."""
    from scripts import sermon_openai_runtime as runtime
    _require(isinstance(adjudicator, dict), 'receipt_adjudicator_runtime')
    route = adjudicator.get('route')
    _require(route is None or (isinstance(route, dict) and set(route) == {'environment', 'projectId', 'credentialAlias'}
                               and runtime.safe_route({'schemaVersion': 'sermon-openai-runtime-route-v1',
                                                       'identitySource': 'configured_runtime', **route}) is not None),
             'receipt_adjudicator_runtime')
    try:
        tier = limits.validate_request_limits(adjudicator.get('requestLimits'))
    except ValueError as exc:
        raise SourceAdjudicationError('receipt_adjudicator_runtime') from exc
    # A budget exists only under the launcher and pays for the tier it approved, nothing else; without
    # one, SolAdjudicator uses the default tier.
    _require(tier == (limits.DEFAULT_REQUEST_LIMITS if budget is None else budget['requestLimits'])
             and (budget is None or route is not None), 'receipt_adjudicator_runtime')


def _verify_model_verdict(row: dict[str, Any], adjudicator: dict[str, Any], cache: Path,
                          frozen_tokens: list[str]) -> dict[str, Any]:
    """Reproduce a model-decided verdict from the hash-bound cached request/response the row names.

    Returns the question the cached request asked, which the caller compares in
    full with the one the receipt and anchor ask when the anchor is supplied."""
    from scripts import sermon_sentence_interpretation as contract
    from scripts.run_sentence_interpretation_models import _model_result
    request = row['request']
    _require(all(isinstance(request.get(key), str) for key in ('path', 'sha256', 'requestSha256')),
             'receipt_decision_evidence')
    path = Path(cache).resolve() / 'cache' / Path(request['path']).name
    _require(path.is_file(), 'receipt_model_response_missing')
    _require(contract.sha256(path) == request['sha256'], 'receipt_model_response_changed')
    cached = _load(path)
    _require(isinstance(cached, dict) and cached.get('requestSha256') == request['requestSha256']
             and contract.json_sha256(cached.get('request')) == request['requestSha256']
             and contract.json_sha256(cached.get('response')) == cached.get('responseSha256'),
             'receipt_model_response_changed')
    try:
        payload = cached['request']['payload']
        system, question = payload['messages'][0]['content'], json.loads(payload['messages'][1]['content'])
        asked = [(item['name'], item['heardClip']) for item in question['listeners']]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SourceAdjudicationError('receipt_model_question_changed') from exc
    _require(payload.get('model') == adjudicator.get('model')
             and payload.get('reasoning_effort') == adjudicator.get('reasoningEffort')
             and _sha(system.encode('utf-8')) == adjudicator.get('promptSha256')
             and question.get('schemaVersion') == QUESTION_SCHEMA
             and question.get('sourceUnitId') == row['sourceUnitId'] and question.get('frozenText') == row['frozenText']
             and asked == [(h['listener'], h['text']) for h in row['heard']], 'receipt_model_question_changed')
    # The request was asked under the Project and tier the receipt names: the cache stage carries the
    # route, the payload the tier's caps (``_adjudicator_runtime`` has checked both identities).
    try:
        bounded = limits.bounded_payload(payload, adjudicator['requestLimits']) == payload
    except ValueError:
        bounded = False
    _require(bounded and cached['request'].get('stage')
             == f"source-meaning-{_route_key(adjudicator.get('route'))}-{row['sourceUnitId']}",
             'receipt_model_runtime_changed')
    try:
        result = _model_result(cached['response'], adjudicator['model'])
    except ValueError as exc:
        raise SourceAdjudicationError('receipt_model_response_changed') from exc
    verdict = _checked_answer(result, frozen_tokens, row['heard'])
    _require(all(row.get(key) == value for key, value in verdict.items()), 'receipt_verdict_not_from_model')
    return question


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
                       receipt_name: str, receipt_sha256: str, source_audio: Path,
                       asr_reference: Path) -> dict[str, Any] | None:
    """A ``sermon-source-text-review-v2`` review for the corrected units, or None when nothing changed.

    The review binds the window clip and ASR reference the Layer 1 pipeline
    will apply it against, and the receipt file (its name beside the review,
    and the sha256 of its bytes) as its evidence, so it can be built and
    checked before the receipt file is written."""
    corrected = [row for row in receipt['units'] if row['decision'] == 'transcript_corrected']
    if not corrected:
        return None
    _require(receipt.get('adjudicator') is not None, 'adjudicator_identity_missing')
    by_id = {u['sourceUnitId']: u for u in _units(anchor)}
    evidence_sha = receipt_sha256
    # Units are finer than ASR segments: corrections that share a segment become one patch.
    per_segment: dict[int, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for row in corrected:
        segment = _segment_for(by_id[row['sourceUnitId']], segments)
        _require(type(segment.get('id')) is int, 'segment_id_invalid')
        per_segment.setdefault(segment['id'], (segment, []))[1].append(row)
    patches: list[dict[str, Any]] = []
    for segment_id, (segment, rows) in sorted(per_segment.items()):
        text = segment['text']
        for row in rows:
            english = by_id[row['sourceUnitId']]['english']
            _require(text.count(english) == 1, 'segment_corrections_overlap')
            text = text.replace(english, row['correctedText'])
        patches.append({'segmentId': segment_id,
                        'originalTextSha256': source_review.text_sha256(segment['text']),
                        'correctedText': text,
                        'reason': '; '.join(f"{row['sourceUnitId']} heard by {row['heardBy']}: {row['reason']}"
                                            for row in rows),
                        'evidenceSha256': evidence_sha})
    return {'schemaVersion': source_review.SCHEMA_V2, 'reviewType': 'model', 'model': receipt['adjudicator']['model'],
            'humanApproval': False, 'status': source_review.STATUS, 'authority': source_review.MACHINE_AUTHORITY,
            'reviewedBy': receipt['decidedBy'], 'reviewedAt': receipt['reviewedAt'],
            'sourceAudioSha256': file_sha256(source_audio), 'asrSha256': file_sha256(asr_reference),
            'evidence': [{'path': receipt_name, 'sha256': evidence_sha}], 'patches': patches}


# ---------------------------------------------------------------- Layer 2 repair notes

def meaning_notes(receipt: dict[str, Any], *, receipt_sha256: str) -> dict[str, Any] | None:
    """The repair input for units that keep their frozen text, or None when every unit was corrected.

    A Layer 2 repair brief for a group holding one of these units appends the
    note; the artifact is bound to the receipt and to the Layer 1 inputs the
    receipt was bound to, and names the frozen text it speaks about."""
    rows = [{'sourceUnitId': row['sourceUnitId'], 'decision': row['decision'],
             'frozenTextSha256': source_review.text_sha256(row['frozenText']), 'meaningNote': row['meaningNote'],
             'decidedBy': row['decidedBy']}
            for row in receipt['units'] if row['decision'] != 'transcript_corrected']
    if not rows:
        return None
    return {'schemaVersion': NOTES_SCHEMA, 'bindings': dict(receipt['bindings']), 'receiptSha256': receipt_sha256,
            'decidedBy': receipt['decidedBy'], 'decidedByRole': receipt['decidedByRole'], 'humanApproval': False,
            'units': rows,
            'notice': ('Machine evidence for the Layer 2 repair instruction of the groups holding these units; '
                       'the frozen English text is unchanged. Not human approval.')}


def load_meaning_notes(path: Path, *, source: dict[str, Any], anchor: dict[str, Any],
                       receipt_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Notes bound to exactly these Layer 1 inputs and reproduced from their receipt, keyed by unit.

    The notes file is a projection of the receipt it names. That receipt must
    exist (beside the notes as ``receipt.json``, or at ``receipt_path``), hash
    to the notes' ``receiptSha256``, carry the same bindings, and yield these
    very rows, so a stale or hand-edited notes file cannot pass an invented
    decision or note off as machine audio adjudication."""
    path = Path(path)
    notes = _load(path)
    _require(isinstance(notes, dict) and notes.get('schemaVersion') == NOTES_SCHEMA, 'meaning_notes_schema')
    _require(notes.get('bindings') == {'source.json': policies.canonical_sha256(source),
                                       'anchor.json': policies.canonical_sha256(anchor)}, 'meaning_notes_binding_changed')
    receipt_path = Path(receipt_path) if receipt_path is not None else path.parent / 'receipt.json'
    _require(receipt_path.is_file(), 'meaning_notes_receipt_missing')
    _require(isinstance(notes.get('receiptSha256'), str) and file_sha256(receipt_path) == notes['receiptSha256'],
             'meaning_notes_receipt_changed')
    receipt = _load(receipt_path)
    try:
        validate_receipt(receipt, source=source, anchor=anchor, cache=receipt_path.parent / ADJUDICATOR_CACHE)
        _require(receipt['bindings'] == notes['bindings'], 'meaning_notes_receipt_changed')
        expected = meaning_notes(receipt, receipt_sha256=notes['receiptSha256'])
    except (KeyError, TypeError) as exc:
        raise SourceAdjudicationError('meaning_notes_receipt_changed') from exc
    _require(expected is not None and all(notes.get(key) == expected[key]
                                          for key in ('decidedBy', 'decidedByRole', 'humanApproval', 'units')),
             'meaning_notes_unit_changed')
    units = {u['sourceUnitId']: u for u in _units(anchor)}
    out: dict[str, dict[str, Any]] = {}
    for row in notes['units']:
        uid = row.get('sourceUnitId')
        _require(uid in units and row.get('decision') in DECISIONS and row['decision'] != 'transcript_corrected'
                 and isinstance(row.get('meaningNote'), str) and row['meaningNote'].strip()
                 and source_review.text_sha256(units[uid]['english']) == row.get('frozenTextSha256')
                 and uid not in out, 'meaning_notes_unit_changed')
        out[uid] = row
    return out


def repair_instruction(notes: dict[str, dict[str, Any]], source_unit_ids: list[str]) -> str:
    """What a Layer 2 repair brief appends for a group that holds noted units; empty when it holds none."""
    return ' '.join(f"Source unit {uid} ({notes[uid]['decision'].replace('_', ' ')} by machine audio adjudication): "
                    f"{notes[uid]['meaningNote']}" for uid in source_unit_ids if uid in notes)


# ---------------------------------------------------------------- CLI

def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _encode(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


SIDECARS = ('source-text-review.json', 'meaning-notes.json')


PARTIAL_SUFFIX = '.partial'


def _write_new(path: Path, value: dict[str, Any]) -> None:
    """Publish ``path`` whole, and never over an existing file.

    The bytes go to a sibling partial file and are flushed before the final
    name appears, so a process killed mid-write leaves no truncated
    ``receipt.json`` for the next attempt to mistake for a finished run. The
    final name is taken by a link, which fails when the file already exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f'.{path.name}{PARTIAL_SUFFIX}')
    with partial.open('wb') as handle:
        handle.write(_encode(value))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def write_outputs(out_dir: Path, receipt: dict[str, Any], review: dict[str, Any] | None,
                  notes: dict[str, Any] | None) -> dict[str, Any]:
    """Write the derived sidecars first and the receipt last; return the paths written.

    The receipt file is the completion marker: a failure while writing a
    sidecar leaves no receipt, so the directory stays resumable and no artifact
    the receipt vouches for can be missing beside it."""
    out_dir = Path(out_dir)
    written: dict[str, Any] = {'review': None, 'meaningNotes': None}
    if review is not None:
        _write_new(out_dir / SIDECARS[0], review)
        written['review'] = str((out_dir / SIDECARS[0]).resolve())
    if notes is not None:
        _write_new(out_dir / SIDECARS[1], notes)
        written['meaningNotes'] = str((out_dir / SIDECARS[1]).resolve())
    _write_new(out_dir / 'receipt.json', receipt)
    return written


def resumable_out_dir(path: Path) -> Path:
    """An output directory that is new, or an incomplete earlier attempt whose caches are reused.

    A directory already holding a receipt is complete and is never overwritten;
    one left by a failed run keeps its paid re-listens and model answers, which
    the next attempt serves from cache instead of paying again. Sidecars such
    an attempt left behind bind a receipt that was never written; they are
    discarded, since the next attempt derives them again from its own receipt."""
    path = Path(path)
    if (path / 'receipt.json').exists():
        raise SystemExit('out dir already holds a receipt; choose a new path')
    if path.exists() and not path.is_dir():
        raise SystemExit('out dir is not a directory')
    for name in SIDECARS:
        (path / name).unlink(missing_ok=True)
    for partial in path.glob(f'.*{PARTIAL_SUFFIX}'):
        partial.unlink()  # bytes a killed attempt never published
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixture', type=Path, help='Directory with source.json and anchor.json')
    parser.add_argument('--media', type=Path, required=True, help='The bound media file named by source.json')
    parser.add_argument('--unit', action='append', required=True, help='Doubted source unit; repeatable')
    parser.add_argument('--out-dir', type=Path, required=True,
                        help='Directory for receipt, clips, re-listens; an incomplete earlier attempt resumes')
    parser.add_argument('--listener', action='append', choices=('openai', 'qwen'), default=None,
                        help='Independent listeners (default: openai)')
    parser.add_argument('--asr-model-path', type=Path, help='Qwen3-ASR weights for the qwen listener')
    parser.add_argument('--max-api-calls', type=int, default=8, help='Cap on new paid transcription calls')
    parser.add_argument('--max-adjudicator-calls', type=int, default=None,
                        help='Cap on new paid adjudicator calls (default: one per doubted unit)')
    parser.add_argument('--model', default=MODEL, choices=sorted(ADJUDICATOR_MODELS))
    parser.add_argument('--reasoning-effort', default=EFFORT)
    parser.add_argument('--aligned-segments', type=Path,
                        help='Layer 1 aligned segments; with the two paths below, a corrected unit writes the review')
    parser.add_argument('--source-audio', type=Path, help='The window clip the Layer 1 pipeline transcribed')
    parser.add_argument('--asr-reference', type=Path, help='The ASR reference file the Layer 1 pipeline wrote')
    parser.add_argument('--budget-authorization', type=Path,
                        help=f'{BUDGET_SCHEMA} bound to this fixture, these units, the code and --out-dir; '
                             'without it the run may only replay cached calls')
    parser.add_argument('--print-budget-binding', action='store_true',
                        help='Print the binding a budget authorization must carry for this run and exit')
    args = parser.parse_args(argv)
    if args.print_budget_binding:
        source, anchor = _load(args.fixture / 'source.json'), _load(args.fixture / 'anchor.json')
        print(json.dumps(budget_binding(source, anchor, args.unit, args.out_dir, model=args.model,
                                        effort=args.reasoning_effort), ensure_ascii=False, indent=2))
        return 0
    resumable_out_dir(args.out_dir)
    review_inputs = (args.aligned_segments, args.source_audio, args.asr_reference)
    if any(review_inputs) and not all(review_inputs):
        raise SystemExit('--aligned-segments, --source-audio and --asr-reference go together')
    from scripts import sermon_openai_runtime as runtime
    if runtime.selected_route() is None:
        raise SystemExit('start under scripts/run_with_openai_environment.py --environment dev (prod for formal content)')
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    source, anchor = _load(args.fixture / 'source.json'), _load(args.fixture / 'anchor.json')
    # Unbound requests are refused before dispatch: with no authorization the listeners and the
    # adjudicator replay their caches, and the first cache miss stops the run without spending.
    budget = None if args.budget_authorization is None else load_budget_authorization(
        args.budget_authorization, binding=budget_binding(source, anchor, args.unit, args.out_dir, model=args.model,
                                                          effort=args.reasoning_effort))
    segments = None
    if args.aligned_segments:
        expected = source.get('transcript', {}).get('artifact', {}).get('sha256')
        if isinstance(expected, str) and file_sha256(args.aligned_segments) != expected:
            raise SystemExit('aligned segments differ from the transcript artifact source.json binds')
        segments = _load(args.aligned_segments)
    cache = args.out_dir / ADJUDICATOR_CACHE
    listeners: list[Any] = []
    for choice in args.listener or ['openai']:
        if choice == 'openai':
            listeners.append(OpenAiTranscribeListener(cache=cache / 'openai', max_calls=args.max_api_calls,
                                                      budget=budget))
        else:
            if args.asr_model_path is None:
                raise SystemExit('--listener qwen needs --asr-model-path')
            listeners.append(QwenListener(args.asr_model_path, cache=cache / 'qwen'))
    adjudicator = SolAdjudicator(api_key=api_key, cache=cache, model=args.model, effort=args.reasoning_effort,
                                 max_calls=len(args.unit) if args.max_adjudicator_calls is None
                                 else args.max_adjudicator_calls, budget=budget)
    receipt = adjudicate(source, anchor, unit_ids=args.unit, media=args.media, listeners=listeners,
                         adjudicator=adjudicator, out_dir=args.out_dir, budget=budget)
    # Everything derived from the receipt is built first: the receipt file marks the
    # output complete, and a failure before it leaves a resumable directory.
    file_sha = _sha(_encode(receipt))
    review = None
    if segments is not None:
        review = source_text_review(receipt, anchor, segments, receipt_name='receipt.json', receipt_sha256=file_sha,
                                    source_audio=args.source_audio, asr_reference=args.asr_reference)
    notes = meaning_notes(receipt, receipt_sha256=file_sha)
    written = write_outputs(args.out_dir, receipt, review, notes)
    summary = {'receiptSha256': receipt_sha256(receipt), 'receiptFileSha256': file_sha,
               'out': str(args.out_dir.resolve()),
               'decisions': [(row['sourceUnitId'], row['decision'], row['correctedText']) for row in receipt['units']],
               **written}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
