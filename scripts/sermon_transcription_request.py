"""Pure bounded PCM-WAV request construction for gpt-transcribe.

No files, credentials, subprocess, network or model call is used here. The caller
owns the existing durable audio budget/HTTP worker and enforces at most two
requests for the whole run. This builder reserves whole-minute-rounded input
cost; the provider's published duration rate does not make input duration an
actual invoice or a reported provider duration. No token zeros are invented.

Accepted WAVs are RIFF/WAVE integer PCM (format 1), with one fmt/data chunk,
coherent block alignment/byte rate, complete frames and exact RIFF length. The
bounded PCM bytes are read through the standard decoder before the multipart
body is built. Compressed/float/extensible/RF64 formats require prior conversion.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import struct
import wave
from fractions import Fraction

SCHEMA = 'sermon-transcription-request-v1'
MODEL = 'gpt-transcribe'
LANGUAGE = 'en'
RESPONSE_FORMAT = 'json'
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_DURATION_SECONDS = 180
WALL_TIME_MS = 300_000
MAX_RESPONSE_BYTES = 200 * 1024
MICROUSD_PER_MINUTE = 4500
PRICE_SOURCE = 'https://developers.openai.com/api/docs/models/gpt-transcribe'
PRICE_VERIFIED_AT = '2026-09-30'


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _ceil(value):
    return (value.numerator + value.denominator - 1) // value.denominator


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pcm(wav_bytes):
    _require(type(wav_bytes) is bytes and 44 <= len(wav_bytes) <= MAX_AUDIO_BYTES,
             'transcription_audio_size_invalid')
    _require(wav_bytes[:4] == b'RIFF' and wav_bytes[8:12] == b'WAVE', 'transcription_requires_pcm_wav')
    _require(struct.unpack_from('<I', wav_bytes, 4)[0] == len(wav_bytes) - 8,
             'transcription_riff_size_mismatch')
    offset, fmt, data, fact = 12, None, None, None
    while offset < len(wav_bytes):
        _require(offset + 8 <= len(wav_bytes), 'transcription_truncated_chunk_header')
        tag, size = struct.unpack_from('<4sI', wav_bytes, offset)
        start, end = offset + 8, offset + 8 + size
        _require(end <= len(wav_bytes), 'transcription_truncated_chunk')
        if tag == b'fmt ':
            _require(fmt is None and data is None, 'transcription_duplicate_or_late_format')
            fmt = wav_bytes[start:end]
        elif tag == b'data':
            _require(data is None and fmt is not None, 'transcription_duplicate_or_early_data')
            data = wav_bytes[start:end]
        elif tag == b'fact':
            _require(fact is None and size == 4, 'transcription_invalid_frame_fact')
            fact = struct.unpack_from('<I', wav_bytes, start)[0]
        offset = end + (size & 1)
        _require(offset <= len(wav_bytes), 'transcription_missing_chunk_padding')
    _require(fmt is not None and data is not None and len(fmt) in (16, 18), 'transcription_missing_pcm_chunks')
    kind, channels, rate, byte_rate, alignment, bits = struct.unpack_from('<HHIIHH', fmt)
    _require(kind == 1 and channels > 0 and rate > 0 and bits in (8, 16, 24, 32),
             'transcription_requires_integer_pcm')
    _require(len(fmt) == 16 or fmt[16:] == b'\0\0', 'transcription_unsupported_pcm_extension')
    width = bits // 8
    _require(alignment == channels * width and byte_rate == rate * alignment,
             'transcription_incoherent_pcm_format')
    _require(data and len(data) % alignment == 0, 'transcription_partial_or_empty_pcm_frames')
    frames = len(data) // alignment
    _require(frames <= rate * MAX_DURATION_SECONDS, 'transcription_duration_exceeded')
    _require(fact is None or fact == frames, 'transcription_frame_fact_mismatch')
    try:
        with wave.open(io.BytesIO(wav_bytes), 'rb') as decoded:
            _require(decoded.getcomptype() == 'NONE' and decoded.getnchannels() == channels and
                     decoded.getsampwidth() == width and decoded.getframerate() == rate and
                     decoded.getnframes() == frames, 'transcription_decoder_identity_mismatch')
            actual = decoded.readframes(frames + 1)
            _require(actual == data and decoded.readframes(1) == b'', 'transcription_decoded_frames_mismatch')
    except (wave.Error, EOFError, struct.error) as exc:
        raise ValueError('transcription_pcm_decode_failed') from exc
    return {'container': 'wav', 'encoding': 'integer_pcm', 'channels': channels,
        'sampleRateHz': rate, 'sampleWidthBytes': width, 'decodedFrameCount': frames,
        'decodedDurationSeconds': float(Fraction(frames, rate)), 'byteCount': len(wav_bytes)}, Fraction(frames, rate)


def build_request(wav_bytes, expected_audio_sha256):
    """Validate exact input and return identity, multipart bytes and audio bounds.

    budgetBounds intentionally has no input/output token dimension: this request
    is billed by audio duration. The primary's audio-specific ledger must retain
    monetary/wall/request caps and must not fill absent token fields with zero.
    """
    _require(type(expected_audio_sha256) is str and re.fullmatch('[a-f0-9]{64}', expected_audio_sha256),
             'transcription_expected_hash_invalid')
    audio, duration = _pcm(wav_bytes)
    _require(hashlib.sha256(wav_bytes).hexdigest() == expected_audio_sha256, 'transcription_audio_identity_mismatch')
    # The body is stable for the exact audio; fixed form field names/filename do
    # not expose a machine path. Refuse the extraordinarily unlikely delimiter
    # collision rather than mutating or silently splitting the caller's audio.
    boundary = 'sermon-transcription-' + expected_audio_sha256
    delimiter = ('--' + boundary).encode('ascii')
    _require(delimiter not in wav_bytes, 'transcription_multipart_boundary_collision')
    parts = []
    for name, value in (('model', MODEL), ('language', LANGUAGE), ('response_format', RESPONSE_FORMAT)):
        parts.append(delimiter + b'\r\nContent-Disposition: form-data; name="' + name.encode('ascii') +
                     b'"\r\n\r\n' + value.encode('ascii') + b'\r\n')
    parts.append(delimiter + b'\r\nContent-Disposition: form-data; name="file"; filename="clip.wav"\r\n'
                 b'Content-Type: audio/wav\r\n\r\n' + wav_bytes + b'\r\n')
    body = b''.join(parts) + delimiter + b'--\r\n'
    reserved_minutes = _ceil(duration / 60)
    identity = {'schemaVersion': SCHEMA, 'model': MODEL,
        'inputDurationSeconds': audio['decodedDurationSeconds'],
        'api': {'model': MODEL, 'language': LANGUAGE,
        'response_format': RESPONSE_FORMAT}, 'audio': dict(audio, sha256=expected_audio_sha256),
        'requestBodySha256': hashlib.sha256(body).hexdigest(),
        'responseMaxBytes': MAX_RESPONSE_BYTES}
    return {'identity': identity, 'identitySha256': hashlib.sha256(_canonical(identity)).hexdigest(),
        'body': body, 'contentType': 'multipart/form-data; boundary=' + boundary,
        'budgetBounds': {'requests': 1, 'wallTimeMs': WALL_TIME_MS,
                         'costMicrousd': reserved_minutes * MICROUSD_PER_MINUTE},
        'responseMaxBytes': MAX_RESPONSE_BYTES, 'reservedBillableMinutes': reserved_minutes,
        'tokenUsage': {'inputTokens': None, 'outputTokens': None, 'cachedInputTokens': None,
                       'reasonCode': 'not_reported_duration_billed_api'}}


def _duration(value, *, bounded):
    if type(value) not in (int, float):
        return None
    if not 0 < value <= (MAX_DURATION_SECONDS if bounded else 10**12) or not math.isfinite(value):
        return None
    return Fraction(str(value))


def usage_cost_evidence(response, inputduration):
    """Keep decoded input measurement separate from actual provider reporting.

    `duration` is accepted from a JSON response, or `usage.seconds` with explicit
    usage.type=duration. If both appear they must agree. Absent/invalid/conflicting
    duration keeps provider cost unknown; a separate input-based estimate and
    whole-minute reservation remain available. Token counters are never inferred
    from bytes, duration or price. This function never returns transcript text.
    """
    source_duration = _duration(inputduration, bounded=True)
    _require(source_duration is not None, 'transcription_input_duration_invalid')
    common = {'model': MODEL, 'currency': 'USD', 'priceSource': PRICE_SOURCE,
        'priceVerifiedAt': PRICE_VERIFIED_AT, 'priceUsdPerAudioMinute': '0.0045',
        'invoiceVerified': False, 'billingBasis': 'transcription_audio_duration',
        'inputAudioDurationSeconds': float(source_duration),
        'inputDurationProvenance': 'caller_supplied_decoded_pcm_frames_over_sample_rate',
        'inputDurationEstimatedCostMicrousd': _ceil(source_duration * MICROUSD_PER_MINUTE / 60),
        'inputDurationReservationCostMicrousd': _ceil(source_duration / 60) * MICROUSD_PER_MINUTE,
        'inputTokens': None, 'outputTokens': None, 'cachedInputTokens': None,
        'tokenUsageReason': 'not_reported_duration_billed_api',
        'providerAudioDurationSeconds': None, 'costMicrousd': None, 'costStatus': 'unknown'}
    if type(response) is not dict:
        return dict(common, providerDurationStatus='invalid_response')
    if 'model' in response and response['model'] != MODEL:
        return dict(common, providerDurationStatus='model_identity_mismatch')
    reported = []
    if 'duration' in response:
        reported.append(_duration(response['duration'], bounded=False))
    usage = response.get('usage')
    if type(usage) is dict and usage.get('type') == 'duration':
        reported.append(_duration(usage.get('seconds'), bounded=False))
    if not reported:
        return dict(common, providerDurationStatus='not_reported')
    if any(value is None for value in reported):
        return dict(common, providerDurationStatus='invalid_reported_duration')
    if any(value != reported[0] for value in reported):
        return dict(common, providerDurationStatus='conflicting_reported_duration')
    actual = reported[0]
    return dict(common, providerDurationStatus='reported', providerAudioDurationSeconds=float(actual),
        costMicrousd=_ceil(actual * MICROUSD_PER_MINUTE / 60), costStatus='estimated_from_provider_duration')
