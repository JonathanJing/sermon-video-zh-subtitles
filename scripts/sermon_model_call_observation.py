"""Provider-neutral, content-free model invocation observations.

Counters and generation timings require reported evidence. Request/session rates
include their respective waiting time and never stand in for generation speed.
Observations are not billing receipts and must not be added to invoiced usage.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import math
import re
import time
import uuid

from scripts import sermon_accounting as accounting

SCHEMA = 'sermon-model-call-observation-v1'
CODE = 'model_call_observation'
TOKEN_FIELDS = frozenset({'inputTokens', 'outputTokens', 'cachedInputTokens', 'reasoningTokens', 'totalTokens'})
RATE_FIELDS = frozenset({'requestOutputTokensPerSecond', 'generationOutputTokensPerSecond', 'sessionOutputTokensPerSecond'})
FIELDS = frozenset({'schemaVersion', 'callId', 'parentCallId', 'phase', 'status', 'model', 'backend', 'provider', 'role',
    'timingScope', 'usageSource', 'usageStatus', 'startedAt', 'finishedAt', 'elapsedSeconds', 'generationSeconds',
    'firstTokenSeconds', 'cacheHit', 'usage', 'rates', 'errorType'})
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}')


def _number(value, *, integer=False):
    if integer:
        return type(value) is int and 0 <= value <= 10**15
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10**12


def _pick(data, names):
    for name in names:
        if name in data and data[name] is not None:
            value = data[name]
            if not _number(value, integer=True):
                raise ValueError('invalid_model_usage_counter')
            return value
    return None


def normalize_usage(raw):
    """Whitelist OpenAI, Ollama, MLX and host telemetry aliases; null stays null."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError('invalid_model_usage')
    # Callers must select the per-call host receipt; cumulative session usage is
    # explicitly logged with the agent_session timing scope instead.
    data = raw.get('usage', raw)
    if not isinstance(data, dict):
        raise ValueError('invalid_model_usage')
    aliases = {
        'inputTokens': ('inputTokens', 'input_tokens', 'prompt_tokens', 'prompt_eval_count'),
        'outputTokens': ('outputTokens', 'output_tokens', 'completion_tokens', 'generation_tokens', 'eval_count'),
        'cachedInputTokens': ('cachedInputTokens', 'cached_input_tokens', 'cached_tokens', 'cache_read_input_tokens'),
        'reasoningTokens': ('reasoningTokens', 'reasoning_tokens', 'reasoning_output_tokens'),
        'totalTokens': ('totalTokens', 'total_tokens'),
    }
    result = {key: _pick(data, names) for key, names in aliases.items()}
    for key, containers, alias in (
        ('cachedInputTokens', ('input_tokens_details', 'prompt_tokens_details'), 'cached_tokens'),
        ('reasoningTokens', ('output_tokens_details', 'completion_tokens_details'), 'reasoning_tokens'),
    ):
        if result[key] is None:
            for container in containers:
                details = data.get(container)
                if isinstance(details, dict):
                    value = _pick(details, (alias,))
                    if value is not None:
                        result[key] = value
                        break
    return result


def generation_seconds(raw, usage):
    """Read explicit Ollama duration or MLX measured throughput, never guess."""
    if not isinstance(raw, dict):
        return None
    if raw.get('eval_duration') is not None:
        value = raw['eval_duration']
        if not _number(value):
            raise ValueError('invalid_generation_duration')
        return value / 1_000_000_000
    for key in ('generationSeconds', 'generation_seconds'):
        if raw.get(key) is not None:
            if not _number(raw[key]):
                raise ValueError('invalid_generation_duration')
            return raw[key]
    rate = raw.get('generation_tps')
    if rate is not None:
        if not _number(rate) or rate == 0:
            raise ValueError('invalid_generation_rate')
        if usage['outputTokens'] is not None:
            return usage['outputTokens'] / rate
    return None


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z', value):
        raise ValueError('invalid_model_observation_timestamp')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)


def _utc():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _rate(tokens, seconds):
    return tokens / seconds if tokens is not None and seconds is not None and seconds > 0 else None


def safe_observation(fields):
    """Validate and copy the exact content-free envelope on writing or reading."""
    if not isinstance(fields, dict) or set(fields) != FIELDS or fields['schemaVersion'] != SCHEMA:
        raise ValueError('invalid_model_observation')
    for key in ('model', 'provider', 'callId'):
        if not isinstance(fields[key], str) or LABEL.fullmatch(fields[key]) is None:
            raise ValueError('invalid_model_observation_label')
    for key in ('parentCallId', 'errorType'):
        if fields[key] is not None and (not isinstance(fields[key], str) or LABEL.fullmatch(fields[key]) is None):
            raise ValueError('invalid_model_observation_label')
    for key, allowed in (
        ('backend', {'api', 'local', 'agent_session'}), ('role', {'production', 'supervisor', 'engineering'}),
        ('timingScope', {'request', 'generation', 'agent_session_including_tools'}),
        ('usageSource', {'provider', 'local_tokenizer', 'host_telemetry', 'not_reported'}),
        ('phase', {'started', 'finished'}), ('status', {'started', 'completed', 'failed'}),
        ('usageStatus', {'unknown', 'partial', 'reported'}),
    ):
        if not isinstance(fields[key], str) or fields[key] not in allowed:
            raise ValueError('invalid_model_observation_policy')
    if fields['cacheHit'] is not None and type(fields['cacheHit']) is not bool:
        raise ValueError('invalid_model_observation_cache')
    start = _timestamp(fields['startedAt'])
    if fields['finishedAt'] is not None and _timestamp(fields['finishedAt']) < start:
        raise ValueError('invalid_model_observation_timestamp')
    for key in ('elapsedSeconds', 'generationSeconds', 'firstTokenSeconds'):
        if fields[key] is not None and not _number(fields[key]):
            raise ValueError('invalid_model_observation_timing')
    usage, rates = fields['usage'], fields['rates']
    if not isinstance(usage, dict) or set(usage) != TOKEN_FIELDS or any(v is not None and not _number(v, integer=True) for v in usage.values()):
        raise ValueError('invalid_model_observation_usage')
    if not isinstance(rates, dict) or set(rates) != RATE_FIELDS or any(v is not None and not _number(v) for v in rates.values()):
        raise ValueError('invalid_model_observation_rates')
    known = sum(v is not None for v in usage.values())
    expected_status = 'unknown' if known == 0 else 'reported' if known == len(TOKEN_FIELDS) else 'partial'
    if fields['usageStatus'] != expected_status or (fields['usageSource'] == 'not_reported' and known):
        raise ValueError('invalid_model_observation_usage_source')
    if fields['phase'] == 'started':
        if fields['status'] != 'started' or any(fields[k] is not None for k in ('finishedAt', 'elapsedSeconds', 'generationSeconds', 'firstTokenSeconds', 'cacheHit', 'errorType')) or known or any(v is not None for v in rates.values()):
            raise ValueError('invalid_model_observation_phase')
    elif fields['status'] == 'started' or fields['finishedAt'] is None or fields['elapsedSeconds'] is None or ((fields['status'] == 'failed') != (fields['errorType'] is not None)):
        raise ValueError('invalid_model_observation_phase')
    expected_rates = {
        'requestOutputTokensPerSecond': _rate(usage['outputTokens'], fields['elapsedSeconds']) if fields['timingScope'] == 'request' else None,
        'generationOutputTokensPerSecond': _rate(usage['outputTokens'], fields['generationSeconds']),
        'sessionOutputTokensPerSecond': _rate(usage['outputTokens'], fields['elapsedSeconds']) if fields['timingScope'] == 'agent_session_including_tools' else None,
    }
    if rates != expected_rates:
        raise ValueError('invalid_model_observation_rates')
    return {**fields, 'usage': dict(usage), 'rates': dict(rates)}


def _emit(fields):
    accounting._emit({'event': 'log', 'code': CODE, 'level': 'INFO', 'fields': safe_observation(fields)})


@contextmanager
def invocation(model, *, backend, provider, role, call_id=None, timing_scope='request', usage_source='not_reported', parent_call_id=None):
    """Yield a receipt to populate; preserve original model exceptions on failure."""
    fields = dict(schemaVersion=SCHEMA, callId=call_id or uuid.uuid4().hex, parentCallId=parent_call_id,
        phase='started', status='started', model=model, backend=backend, provider=provider, role=role,
        timingScope=timing_scope, usageSource=usage_source, usageStatus='unknown', startedAt=_utc(),
        finishedAt=None, elapsedSeconds=None, generationSeconds=None, firstTokenSeconds=None, cacheHit=None,
        usage={k: None for k in TOKEN_FIELDS}, rates={k: None for k in RATE_FIELDS}, errorType=None)
    _emit(fields)
    began = time.monotonic()
    receipt = dict(usage=None, generationSeconds=None, firstTokenSeconds=None, cacheHit=None)
    error = None
    try:
        yield receipt
    except BaseException as exc:
        error = exc
        raise
    finally:
        def finish():
            usage = normalize_usage(receipt.get('usage'))
            duration = receipt.get('generationSeconds')
            if duration is None:
                duration = generation_seconds(receipt.get('usage'), usage)
            fields.update(phase='finished', status='failed' if error else 'completed', finishedAt=_utc(),
                elapsedSeconds=max(0, time.monotonic() - began), generationSeconds=duration,
                firstTokenSeconds=receipt.get('firstTokenSeconds'), cacheHit=receipt.get('cacheHit'), usage=usage,
                errorType=accounting._label(type(error).__name__) if error else None)
            known = sum(v is not None for v in usage.values())
            fields['usageStatus'] = 'unknown' if not known else 'reported' if known == len(TOKEN_FIELDS) else 'partial'
            fields['rates'] = dict(
                requestOutputTokensPerSecond=_rate(usage['outputTokens'], fields['elapsedSeconds']) if timing_scope == 'request' else None,
                generationOutputTokensPerSecond=_rate(usage['outputTokens'], duration),
                sessionOutputTokensPerSecond=_rate(usage['outputTokens'], fields['elapsedSeconds']) if timing_scope == 'agent_session_including_tools' else None)
            _emit(fields)
        accounting._finalize(finish, error)
