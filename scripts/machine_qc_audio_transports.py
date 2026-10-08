#!/usr/bin/env python3
"""ASR and TTS transports for the machine listening waiver.

The audio QC (``target_audio_auto_qc``) and its seeded-error calibration
(``auto_qc_seeded_errors.calibrate``) take their ASR and TTS as injected
callables. This module provides the production ones:

* **Primary ASR** (:class:`QwenPrimaryAsr`): the same local Qwen3-ASR runtime
  that wrote the bound v2 screening receipt. Its opinions carry exactly the
  receipt's ``asrSettings``; audio the receipt already transcribed reuses the
  receipt's own transcript, and any other audio (calibration renders) is
  transcribed only after the live weights, inference identity and screener
  implementation are proven to be the receipt's.
* **Secondary ASR** (:class:`OpenAiTranscribeSecondary`): ``gpt-transcribe``
  through the OpenAI audio transcription API, the model production already uses
  for source transcription. It never sees the expected text (no prompt text from
  the script and no keywords), so it cannot "fill in" a dropped word. It runs
  only under ``scripts/run_with_openai_environment.py``; the key is read from the
  environment the launcher sets and never written anywhere.
* **TTS** (:class:`QwenTtsRender`): the formal Layer 3 renderer's synthesizer
  (``render_formal_target_language_speech.QwenSynthesizer``) on the speech job's
  own checkpoint, speaker and language parameter, so the calibration's
  ``renderIdentity`` is the job's synthesis identity.

Every call is cached under the run's state dir by audio (or text) hash and
runtime identity. A paid call writes ``started.json`` before dispatch and
``response.json`` + ``outcome.json`` after; a call that started without a
completed outcome has an unknown outcome and blocks new dispatch until an
operator reconciles it. No transport retries a paid request.

The fake transports exist for plumbing tests only; their identities name a
``fake-not-evidence`` backend.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import machine_quality_waiver as waiver
from scripts import target_audio_auto_qc as audio_qc

json_sha256 = waiver.json_sha256
ROOT = Path(__file__).resolve().parents[1]
SCREENER = ROOT / "scripts" / "screen_target_language_audio_units.py"
CACHE_NAMESPACE = "machine-qc-audio-v1"
QWEN_LANGUAGES = {"zh-Hans": "Chinese", "ko": "Korean", "es": "Spanish"}

SECONDARY_MODEL = "gpt-transcribe"
SECONDARY_PROTOCOL = "openai-audio-transcriptions-v1"
TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_LANGUAGES = {"zh-Hans": "zh", "ko": "ko", "es": "es"}
# Generic per-language instructions. The expected sentence is never sent: an ASR
# primed with the script would hear words the dub dropped.
SECONDARY_PROMPTS = {
    "zh-Hans": "Transcribe this Simplified Chinese church sermon audio exactly as spoken. "
               "Do not add, correct or complete words that are not audible.",
    "ko": "Transcribe this Korean church sermon audio exactly as spoken. "
          "Do not add, correct or complete words that are not audible.",
    "es": "Transcribe this Spanish church sermon audio exactly as spoken. "
          "Do not add, correct or complete words that are not audible.",
}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def implementation_sha256() -> str:
    """This transport module; its hash joins every opinion's ``settings``."""
    return file_sha256(Path(__file__))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UnknownOutcome(RuntimeError):
    """A paid call started and never recorded a completed outcome."""


def _write_once(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


class CallCache:
    """One directory per request: ``started.json``, then ``response.json`` and ``outcome.json``.

    ``paid`` calls whose run raises keep an ``unknown_outcome`` marker: the
    request may have been billed, so it is never sent again automatically. A
    local (unpaid) call that raises leaves nothing behind and may be retried."""

    def __init__(self, root: Path, *, paid: bool):
        self.root, self.paid = Path(root), paid

    def get(self, key: str):
        folder = self.root / key
        try:
            outcome = json.loads((folder / "outcome.json").read_text(encoding="utf-8"))
            response = json.loads((folder / "response.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if outcome.get("status") != "completed" or outcome.get("responseJsonSha256") != json_sha256(response):
            raise ValueError(f"Cached call {key} does not match its recorded outcome")
        return response

    def run(self, key: str, request: dict, function):
        done = self.get(key)
        if done is not None:
            return done
        folder = self.root / key
        if (folder / "started.json").exists():
            raise UnknownOutcome(f"call {key} started earlier without a completed outcome; reconcile it first")
        _write_once(folder / "started.json", {"request": request})
        try:
            response = function()
        except BaseException as error:
            if self.paid:
                _write_once(folder / "outcome.json", {"status": "unknown_outcome", "errorType": type(error).__name__})
            else:
                (folder / "started.json").unlink(missing_ok=True)
            raise
        _write_once(folder / "response.json", response)
        _write_once(folder / "outcome.json", {"status": "completed", "responseJsonSha256": json_sha256(response)})
        return response

    def uncertain(self) -> list[str]:
        if not self.paid:
            return []
        found = []
        for started in sorted(self.root.glob("*/started.json")):
            try:
                status = json.loads((started.parent / "outcome.json").read_text(encoding="utf-8")).get("status")
            except (OSError, ValueError):
                status = None
            if status != "completed" or not (started.parent / "response.json").exists():
                found.append(started.parent.name)
        return found


class _Asr:
    """Shared opinion builder: ``(role, wav, text, locale) -> opinion`` for calibration."""

    role = ""
    model: str
    model_revision: str | None
    settings: dict

    def transcribe(self, wav: bytes) -> str:
        raise NotImplementedError

    def opinion(self, wav: bytes, text: str, locale: str) -> dict:
        return audio_qc.asr_opinion(self.transcribe(wav), audio=wav, text=text, locale=locale, model=self.model,
                                    settings=self.settings, model_revision=self.model_revision)

    def identity(self) -> dict:
        return {"model": self.model, "modelRevision": self.model_revision,
                "settingsSha256": json_sha256(self.settings)}

    def uncertain(self) -> list[str]:
        return []


def asr_router(primary: _Asr, secondary: _Asr):
    """The ``asr(role, wav, text, locale)`` callable ``auto_qc_seeded_errors.calibrate`` takes."""
    def call(role, wav, text, locale):
        return (primary if role == "primary" else secondary).opinion(wav, text, locale)
    return call


# ---------------------------------------------------------------- primary ASR

def qwen_inference_identity(model_path: Path) -> dict:
    """The runtime identity the screening CLI records for its local Qwen3-ASR."""
    import importlib.metadata
    import torch
    try:
        asr_version = importlib.metadata.version("qwen-asr")
    except importlib.metadata.PackageNotFoundError:
        asr_version = "unavailable"
    model_path = Path(model_path).resolve()
    return {"backend": "qwen-asr-local", "torchVersion": getattr(torch, "__version__", "unavailable"),
            "qwenAsrVersion": asr_version,
            "modelMetadataSha256s": {str(path.relative_to(model_path)): file_sha256(path)
                                     for path in sorted(model_path.rglob("*.json"))}}


class QwenPrimaryAsr(_Asr):
    """The bound screening's local Qwen3-ASR, with the receipt's own runtime settings."""

    role = "primary"

    def __init__(self, screening: dict, *, cache: Path, model_path: Path | None = None,
                 identity_probe=qwen_inference_identity, loader=None):
        self.settings = audio_qc.screening_asr_settings(screening)
        self.model, self.model_revision = screening["model"], screening.get("modelRevision")
        self.locale = screening["targetLocale"]
        # The receipt's own outputs for its own audio: the QC rows must carry exactly these.
        self.heard = {row["audioSha256"]: row["recognized"] for row in screening["results"]}
        self.cache = CallCache(cache, paid=False)
        self.model_path = None if model_path is None else Path(model_path)
        self.identity_probe, self.loader = identity_probe, loader
        self._model = None

    def runtime_problems(self) -> list[str]:
        """Why the live runtime is not the one the screening receipt recorded."""
        if self.model_path is None:
            return ["no --asr-model-path: audio the screening did not transcribe cannot be transcribed"]
        problems = []
        weights = self.model_path / "model.safetensors"
        if not weights.is_file() or self.model_revision != f"model.safetensors:sha256:{file_sha256(weights)}":
            problems.append("live Qwen3-ASR weights differ from the screening's modelRevision")
        if self.settings.get("implementationSha256") != file_sha256(SCREENER):
            problems.append("the screener changed since this screening; rescreen with the current code")
        if (self.settings.get("executionDevice"), self.settings.get("dtype")) != ("cuda:0", "bfloat16"):
            problems.append("screening ran on another device or precision")
        try:
            live = self.identity_probe(self.model_path)
        except Exception as error:  # A missing runtime is reported, not guessed.
            problems.append(f"cannot read the live ASR runtime: {type(error).__name__}")
        else:
            if live != self.settings.get("runtime"):
                problems.append("live ASR runtime (torch, qwen-asr, model metadata) differs from the screening's")
        return problems

    def _load(self):
        if self._model is None:
            problems = self.runtime_problems()
            if problems:
                raise ValueError("Primary ASR cannot reproduce the screening runtime: " + "; ".join(problems))
            if self.loader is not None:
                self._model = self.loader(self.model_path, self.settings)
            else:
                import torch
                from qwen_asr import Qwen3ASRModel
                self._model = Qwen3ASRModel.from_pretrained(
                    str(self.model_path.resolve()), dtype=torch.bfloat16, device_map="cuda:0",
                    max_inference_batch_size=self.settings.get("batchSize", 1),
                    max_new_tokens=self.settings.get("maxNewTokens", 2048))
        return self._model

    def _run(self, wav: bytes) -> str:
        model = self._load()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unit.wav"
            path.write_bytes(wav)
            if self.loader is not None:
                text = model(path, QWEN_LANGUAGES[self.locale])
            else:
                import soundfile as sf
                audio, rate = sf.read(path, dtype="float32")
                values = model.transcribe(audio=(audio, rate), language=QWEN_LANGUAGES[self.locale])
                if len(values) != 1 or not isinstance(values[0].text, str):
                    raise ValueError("ASR scalar output cardinality differs")
                text = values[0].text
        # The screener stores what it heard stripped; so does every later opinion.
        return text.strip()

    def transcribe(self, wav: bytes) -> str:
        audio_sha = _sha(wav)
        if audio_sha in self.heard:
            return self.heard[audio_sha]
        key = json_sha256({"role": "primary", "audioSha256": audio_sha, "settingsSha256": json_sha256(self.settings),
                           "cacheNamespace": CACHE_NAMESPACE})
        return self.cache.run(key, {"audioSha256": audio_sha, "role": "primary"},
                              lambda: {"recognized": self._run(wav)})["recognized"]


# ---------------------------------------------------------------- secondary ASR

def _multipart(fields: list[tuple[str, str]], wav: bytes) -> tuple[bytes, str]:
    boundary = "sermon-audio-qc-" + _sha(wav)
    delimiter = ("--" + boundary).encode("ascii")
    if delimiter in wav:
        raise ValueError("multipart boundary collides with the audio bytes")
    parts = [delimiter + b'\r\nContent-Disposition: form-data; name="' + name.encode("ascii")
             + b'"\r\n\r\n' + value.encode("utf-8") + b"\r\n" for name, value in fields]
    parts.append(delimiter + b'\r\nContent-Disposition: form-data; name="file"; filename="unit.wav"\r\n'
                 b"Content-Type: audio/wav\r\n\r\n" + wav + b"\r\n")
    return b"".join(parts) + delimiter + b"--\r\n", "multipart/form-data; boundary=" + boundary


class OpenAiTranscribeSecondary(_Asr):
    """``gpt-transcribe`` as the stronger second opinion, through the selected OpenAI Project.

    Requires the explicit environment launcher (``run_with_openai_environment.py``):
    without its selected route nothing is sent. ``max_calls`` caps new paid requests
    for this process; the cap is checked before dispatch."""

    role = "secondary"

    def __init__(self, locale: str, *, cache: Path, max_calls: int, request_executor=None):
        from scripts import sermon_openai_runtime as runtime
        route = runtime.selected_route()
        if route is None:
            raise ValueError("The secondary ASR calls the OpenAI API: start this driver under "
                             "scripts/run_with_openai_environment.py --environment dev (or prod for formal content)")
        self.locale, self.max_calls, self.calls = locale, max_calls, 0
        self.executor = request_executor
        self.model, self.model_revision = SECONDARY_MODEL, None
        prompt = SECONDARY_PROMPTS[locale]
        self.fields = [("model", SECONDARY_MODEL), ("response_format", "json"), ("prompt", prompt),
                       ("languages[]", OPENAI_LANGUAGES[locale])]
        self.settings = {
            "protocol": SECONDARY_PROTOCOL, "model": SECONDARY_MODEL, "modelRevision": None, "language": locale,
            "minSimilarity": audio_qc.THRESHOLDS["asrMinSimilarity"], "scoring": _scoring(),
            "implementationSha256": implementation_sha256(),
            "runtime": {"backend": "openai-api", "endpoint": "/v1/audio/transcriptions",
                        "responseFormat": "json", "apiLanguages": [OPENAI_LANGUAGES[locale]],
                        "promptSha256": _sha(prompt.encode("utf-8")), "keywords": [],
                        "upload": "unit_pcm16_wav_bytes", "retries": 0,
                        "modelPinning": "provider_alias_no_revision_reported",
                        "openaiEnvironment": route["environment"], "credentialAlias": route["credentialAlias"],
                        "cacheNamespace": CACHE_NAMESPACE}}
        self.cache = CallCache(cache, paid=True)

    def _send(self, wav: bytes) -> dict:
        from scripts import sermon_pipeline
        from scripts.sermon_openai_runtime import project_headers
        body, content_type = _multipart(self.fields, wav)
        key = os.environ["OPENAI_API_KEY"]
        request = urllib.request.Request(TRANSCRIBE_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": content_type, **project_headers(key)})
        request.accounting_model = SECONDARY_MODEL
        request.accounting_settings = {"requestPayloadSha256": _sha(body)}
        options = {"request_executor": self.executor} if self.executor is not None else {}
        response = sermon_pipeline.request_json(request, retries=1, **options)
        if not isinstance(response, dict) or not isinstance(response.get("text"), str):
            raise ValueError("gpt-transcribe returned no transcript text")
        # Keep only what the QC needs; usage stays for cost accounting.
        return {"text": response["text"], "usage": response.get("usage")}

    def transcribe(self, wav: bytes) -> str:
        audio_sha = _sha(wav)
        key = json_sha256({"role": "secondary", "audioSha256": audio_sha,
                           "settingsSha256": json_sha256(self.settings), "cacheNamespace": CACHE_NAMESPACE})
        done = self.cache.get(key)
        if done is None:
            if len(wav) > MAX_UPLOAD_BYTES:
                raise ValueError("unit audio exceeds the transcription upload limit")
            if self.calls >= self.max_calls:
                raise ValueError(f"secondary ASR call cap reached ({self.max_calls}); raise --max-api-calls deliberately")
            self.calls += 1
            done = self.cache.run(key, {"audioSha256": audio_sha, "role": "secondary", "model": SECONDARY_MODEL,
                                        "settingsSha256": json_sha256(self.settings)}, lambda: self._send(wav))
        return done["text"].strip()

    def uncertain(self) -> list[str]:
        return self.cache.uncertain()


def _scoring() -> str:
    from scripts.screen_target_language_audio_units import SCORING
    return SCORING


# ---------------------------------------------------------------- TTS

def render_identity(job: dict) -> dict:
    """The production TTS behind a speech job: its voice and synthesis identity."""
    from scripts.target_audio_predicted_schedule import synthesis_identity
    adapter = job.get("adapter") or {}
    return {"provider": adapter.get("provider"), "model": adapter.get("model"),
            "checkpointSha256": adapter.get("conditioningSha256"), "synthesis": synthesis_identity(job)}


def checkpoint_path(job: dict, checkpoint_map: dict) -> Path:
    """The model directory the formal renderer's checkpoint map binds to the job's speaker."""
    adapter = job["adapter"]
    if checkpoint_map.get("schemaVersion") != "sermon-speaker-checkpoint-map-v1":
        raise ValueError("Unsupported checkpoint map")
    rows = [row for row in checkpoint_map.get("checkpoints", []) if row.get("speakerId") == adapter["speakerId"]]
    if len(rows) != 1 or not isinstance(rows[0].get("path"), str) or (
            adapter.get("conditioningRef") and rows[0].get("checkpointRef") != adapter["conditioningRef"]):
        raise ValueError("Checkpoint map must bind exactly the speech job's speaker checkpoint")
    return Path(rows[0]["path"]).expanduser().resolve()


class QwenTtsRender:
    """``render(text, locale) -> wav`` with the formal renderer's synthesizer and the job's voice."""

    def __init__(self, job: dict, *, checkpoint: Path, cache: Path, seed: int = 42, device: str = "cuda:0",
                 dtype: str = "bfloat16", attention: str | None = "sdpa", instruct: str | None = None,
                 synth_factory=None):
        self.job, self.adapter = job, job["adapter"]
        self.identity = render_identity(job)
        self.checkpoint = Path(checkpoint)
        self.factory = synth_factory
        self.settings = {"seed": seed, "device": device, "dtype": dtype, "attention": attention,
                         "deliveryInstruction": instruct, "temperature": 0.7, "repetitionPenalty": 1.05,
                         "maxNewTokens": 768, "languageParameter": self.adapter["languageParameter"],
                         "speakerKey": self.adapter["speakerKey"],
                         "renderer": "render_formal_target_language_speech.QwenSynthesizer",
                         "implementationSha256": implementation_sha256()}
        self.cache = Path(cache)
        self._synth = None

    def _synthesizer(self):
        if self._synth is None:
            from scripts import render_formal_target_language_speech as formal
            from scripts import render_multilingual_voice_demos as demos
            demos.validate_checkpoint({"checkpointPath": str(self.checkpoint),
                                       "checkpointSha256": self.adapter["conditioningSha256"],
                                       "speakerKey": self.adapter["speakerKey"],
                                       "speakerId": self.adapter["speakerId"]})
            factory = self.factory or formal.QwenSynthesizer
            self._synth = factory(self.checkpoint, device=self.settings["device"], dtype=self.settings["dtype"],
                                  attention=self.settings["attention"], instruct=self.settings["deliveryInstruction"])
        return self._synth

    def __call__(self, text: str, locale: str) -> bytes:
        if locale != self.job["targetLocale"]:
            raise ValueError("TTS render requested for another locale")
        key = json_sha256({"text": text, "identity": self.identity, "settings": self.settings,
                           "cacheNamespace": CACHE_NAMESPACE})
        folder = self.cache / key
        record_path, wav_path = folder / "record.json", folder / "unit.wav"
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            data = wav_path.read_bytes()
            if record.get("audioSha256") != _sha(data):
                raise ValueError(f"Cached TTS render {key} changed after it was written")
            return data
        from scripts import render_formal_target_language_speech as formal
        samples, rate = self._synthesizer()(text, self.adapter["languageParameter"], self.adapter["speakerKey"],
                                            seed=self.settings["seed"])
        folder.mkdir(parents=True, exist_ok=True)
        partial = folder / f".unit.{os.getpid()}.wav"
        formal.write_pcm16(partial, samples, rate)
        os.replace(partial, wav_path)
        data = wav_path.read_bytes()
        _write_once(record_path, {"textSha256": _sha(text.encode("utf-8")), "audioSha256": _sha(data),
                                  "identity": self.identity, "settings": self.settings})
        return data


# ---------------------------------------------------------------- fakes (plumbing only)

FAKE_BACKEND = "fake-not-evidence"


class FakeTts:
    """Plumbing-only TTS: distinct synthetic audio per text, remembering what it 'said'."""

    def __init__(self, job: dict):
        from scripts.target_audio_predicted_schedule import speech_units
        self.speech_units = speech_units
        self.identity = render_identity(job)
        self.said: dict[str, str] = {}

    def __call__(self, text: str, locale: str) -> bytes:
        import math
        seconds = 0.2 + 0.17 * self.speech_units(text, locale) + 0.001 * (len(self.said) + 1)
        rate = 8000
        samples = [(0.6 if (index / rate) % 0.25 < 0.2 else 0.0) * math.sin(2 * math.pi * 220 * index / rate)
                   for index in range(int(seconds * rate))]
        wav = audio_qc.encode_pcm16(samples, rate)
        self.said[_sha(wav)] = text
        return wav


class FakePrimaryAsr(QwenPrimaryAsr):
    """The screening's own transcripts; rendered audio is heard as the fake TTS said it."""

    def __init__(self, screening: dict, tts: FakeTts):
        super().__init__(screening, cache=Path(tempfile.gettempdir()))
        self.tts = tts

    def transcribe(self, wav: bytes) -> str:
        audio_sha = _sha(wav)
        if audio_sha in self.heard:
            return self.heard[audio_sha]
        return self.tts.said.get(audio_sha, "")


class FakeSecondaryAsr(_Asr):
    """A perfect strong ASR over known audio: package units and fake renders."""

    role = "secondary"

    def __init__(self, locale: str, texts_by_audio: dict[str, str], tts: FakeTts):
        self.model, self.model_revision = "fake-strong-asr", None
        self.texts, self.tts = texts_by_audio, tts
        self.settings = {"protocol": "fake-secondary-asr-v1", "model": self.model, "modelRevision": None,
                         "language": locale, "minSimilarity": audio_qc.THRESHOLDS["asrMinSimilarity"],
                         "scoring": _scoring(), "implementationSha256": implementation_sha256(),
                         "runtime": {"backend": FAKE_BACKEND, "cacheNamespace": CACHE_NAMESPACE}}

    def transcribe(self, wav: bytes) -> str:
        audio_sha = _sha(wav)
        return self.texts.get(audio_sha, self.tts.said.get(audio_sha, ""))
