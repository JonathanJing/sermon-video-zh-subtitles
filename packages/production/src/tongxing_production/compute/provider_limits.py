"""Pure, opt-in bounds for the frozen strict OpenAI chat path.

No network, credentials, tokenization service, approval or quota ledger lives
here. The caller must enforce the user's whole-run target/hard cap in the shared
durable BudgetStore. Request caps include reasoning in max_completion_tokens;
inputs exceeding the conservative UTF-8/framing allowance are rejected intact.

Prices are frozen planning assumptions, not a verified provider invoice. Missing
cache counts remain unknown and all input receives the worst configured input
rate (including the Astra cache-write case). usage_resolver returns measured
request/token/time fields plus this conservative estimated charge; callers must
retain usage_cost_evidence separately and never label that charge invoiced.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import json
import base64
import io
import re
import math

SCHEMA = 'sermon-openai-chat-request-limits-v1'
DEFAULT_REQUEST_LIMITS = {'schemaVersion': SCHEMA, 'maxInputTokens': 8192,
    'maxCompletionTokens': 4096, 'wallTimeMs': 300000, 'serviceTier': 'default'}
MAX_REQUEST_LIMITS = {**DEFAULT_REQUEST_LIMITS, 'maxInputTokens': 16384, 'maxCompletionTokens': 8192}
RUN_TARGET_MICROUSD = 25_000_000
RUN_HARD_CAP_MICROUSD = 40_000_000
SUPPORTED_MODELS = ('gpt-6-astra', 'gpt-6-sol', 'gpt-6.1-sol', 'gpt-6-luna')
# Claude translation is a per-run option. Kept out of SUPPORTED_MODELS so OpenAI
# diagnostics and adjudicators never iterate it; the bounded budget path accepts both.
CLAUDE_MODELS = ('claude-opus-5-5',)
SUPPORTED_REASONING_EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
MODEL_REASONING_EFFORTS = {
    'gpt-6-astra': SUPPORTED_REASONING_EFFORTS,
    'gpt-6-sol': ('low', 'medium', 'high', 'xhigh', 'max'),
    'gpt-6.1-sol': ('low', 'medium', 'high', 'xhigh', 'max'),
    'gpt-6-luna': ('none', 'low', 'medium', 'high', 'xhigh', 'max'),
}
CLAUDE_REASONING_EFFORTS = {'claude-opus-5-5': ('low', 'medium', 'high', 'xhigh', 'max')}
BUDGET_MODELS = SUPPORTED_MODELS + CLAUDE_MODELS


def reasoning_efforts(model):
    return MODEL_REASONING_EFFORTS[model] if model in MODEL_REASONING_EFFORTS else CLAUDE_REASONING_EFFORTS[model]
PRICE_VERIFIED_AT = '2026-10-05'
PRICE_SOURCES = {
    'gpt-6-astra': 'https://developers.openai.com/api/docs/pricing?tab=suite',
    'gpt-6-sol': 'https://developers.openai.com/api/docs/models/gpt-6-sol',
    'gpt-6.1-sol': 'https://developers.openai.com/api/docs/models/gpt-6.1-sol',
    'gpt-6-luna': 'https://developers.openai.com/api/docs/models/gpt-6-luna',
    # Anthropic list price, read from the first-party pricing page on 2026-10-08.
    'claude-opus-5-5': 'https://platform.claude.com/docs/en/about-claude/pricing',
}
PRICE_ASSUMPTION_VERSION = 'strict-chat-worst-case-2026-10-05-v2'
PRICE_VERIFIED_AT_BY_MODEL = {model: PRICE_VERIFIED_AT for model in SUPPORTED_MODELS}
PRICE_ASSUMPTION_VERSION_BY_MODEL = {model: PRICE_ASSUMPTION_VERSION for model in SUPPORTED_MODELS}
PRICE_VERIFIED_AT_BY_MODEL['gpt-6-luna'] = '2026-10-08'
PRICE_ASSUMPTION_VERSION_BY_MODEL['gpt-6-luna'] = 'strict-chat-luna-2026-10-08-v1'
PRICE_VERIFIED_AT_BY_MODEL['claude-opus-5-5'] = '2026-10-08'
PRICE_ASSUMPTION_VERSION_BY_MODEL['claude-opus-5-5'] = 'strict-claude-list-worst-case-2026-10-08-v1'
# USD per million tokens equals micro-USD per token. Exact decimal strings avoid
# float under-reservation; these rates cannot be supplied by a model/caller.
# Claude input uses the 1-hour cache-write rate ($8): the CLI may write prompt
# cache, and the reservation must cover the most expensive input class.
PRICES_USD_PER_MILLION = {
    'gpt-6-astra': {'inputWorstCase': '12.5', 'output': '50'},
    'gpt-6-sol': {'inputWorstCase': '2.5', 'output': '10'},
    'gpt-6.1-sol': {'inputWorstCase': '2.5', 'output': '10'},
    'gpt-6-luna': {'inputWorstCase': '0.125', 'output': '0.5'},
    'claude-opus-5-5': {'inputWorstCase': '8', 'output': '20'},
}
MAX_METRIC = 10**15
MAX_MESSAGES = 16
FRAMING_BASE_TOKEN_ALLOWANCE = 256
FRAMING_PER_MESSAGE_TOKEN_ALLOWANCE = 32


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def validate_request_limits(limits):
    """Validate a closed JSON-compatible configuration; do not apply defaults."""
    _require(type(limits) is dict and set(limits) == set(DEFAULT_REQUEST_LIMITS),
             'invalid_provider_request_limits')
    _require(limits['schemaVersion'] == SCHEMA and limits['serviceTier'] == 'default',
             'unsupported_provider_request_limits')
    for key in ('maxInputTokens', 'maxCompletionTokens', 'wallTimeMs'):
        _require(type(limits[key]) is int and 1 <= limits[key] <= MAX_REQUEST_LIMITS[key],
                 'invalid_provider_request_limit')
    return deepcopy(limits)


def _input_upper_bound(payload):
    # One UTF-8 byte per possible content token, plus fixed/per-message framing.
    # This is a conservative local bound, not measured provider token telemetry.
    try:
        encoded = json.dumps({'messages': payload['messages'],
            'response_format': payload['response_format']}, ensure_ascii=False,
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('invalid_provider_payload_json') from exc
    return len(encoded) + FRAMING_BASE_TOKEN_ALLOWANCE + FRAMING_PER_MESSAGE_TOKEN_ALLOWANCE * len(payload['messages'])


def bounded_payload(payload, limits):
    """Return a bounded copy; reject unsupported/oversized input without edits.

    Existing caps must match the selected limits exactly. No temperature, tools,
    audio/images, streaming, multiple choices or implicit tier/model aliases are
    accepted by this deliberately narrow text-only strict producer contract.
    """
    limits = validate_request_limits(limits)
    required = {'model', 'reasoning_effort', 'messages', 'response_format'}
    _require(type(payload) is dict and required <= set(payload) and
             set(payload) <= required | {'max_completion_tokens', 'service_tier'},
             'unsupported_bounded_provider_payload')
    _require(type(payload['model']) is str and payload['model'] in BUDGET_MODELS,
             'unsupported_bounded_provider_model')
    _require(type(payload['reasoning_effort']) is str and
             payload['reasoning_effort'] in reasoning_efforts(payload['model']),
             'unsupported_bounded_reasoning_effort')
    messages = payload['messages']
    _require(type(messages) is list and 1 <= len(messages) <= MAX_MESSAGES, 'invalid_bounded_messages')
    for message in messages:
        _require(type(message) is dict and set(message) == {'role', 'content'} and
                 type(message['role']) is str and message['role'] in ('system', 'developer', 'user', 'assistant') and
                 type(message['content']) is str and bool(message['content']), 'invalid_bounded_message')
        _require(len(message['content']) <= limits['maxInputTokens'], 'provider_input_bound_exceeded')
    _require(payload['response_format'] == {'type': 'json_object'}, 'unsupported_bounded_response_format')
    if 'max_completion_tokens' in payload:
        _require(type(payload['max_completion_tokens']) is int and
                 payload['max_completion_tokens'] == limits['maxCompletionTokens'], 'provider_output_cap_mismatch')
    if 'service_tier' in payload:
        _require(type(payload['service_tier']) is str and payload['service_tier'] == limits['serviceTier'],
                 'provider_service_tier_mismatch')
    _require(_input_upper_bound(payload) <= limits['maxInputTokens'], 'provider_input_bound_exceeded')
    return dict(deepcopy(payload), max_completion_tokens=limits['maxCompletionTokens'], service_tier=limits['serviceTier'])


LEGACY_MAX_IMAGE_BYTES = 12 * 1024 * 1024
LEGACY_MAX_IMAGES = 12
LEGACY_VISION_SCHEMA = "sermon-legacy-cuv-vision-bounds-v1"

def bounded_legacy_payload(payload, limits):
    """Closed legacy chat formats, separate from the strict text budget adapter.

    Text/schema bytes retain their token allowance. The separate legacy vision
    contract bounds inline image bytes/count and completion output; it does not
    claim the text token cap bounds vision charges or grant spending authority.
    """
    limits=validate_request_limits(limits)
    required={'model','reasoning_effort','messages','response_format'}
    _require(type(payload) is dict and required<=set(payload) and
             set(payload)<=required|{'max_completion_tokens','service_tier'},'unsupported_bounded_provider_payload')
    _require(payload['model'] in SUPPORTED_MODELS,'unsupported_bounded_provider_model')
    _require(payload['reasoning_effort'] in reasoning_efforts(payload['model']),'unsupported_bounded_reasoning_effort')
    messages=payload['messages'];fmt=payload['response_format']
    _require(type(messages) is list and 1<=len(messages)<=MAX_MESSAGES,'invalid_bounded_messages')
    if fmt!={'type':'json_object'}:
        _require(type(fmt) is dict and set(fmt)=={'type','json_schema'} and fmt['type']=='json_schema',
                 'unsupported_bounded_response_format')
        schema=fmt['json_schema']
        _require(type(schema) is dict and set(schema)=={'name','strict','schema'}
                 and isinstance(schema['name'],str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',schema['name'])
                 and schema['strict'] is True and type(schema['schema']) is dict,'unsupported_bounded_response_format')
        from jsonschema import Draft202012Validator
        try:Draft202012Validator.check_schema(schema['schema'])
        except Exception as error:raise ValueError('invalid_bounded_response_schema') from error
    text_messages=[];image_count=0;image_bytes=0
    for message in messages:
        _require(type(message) is dict and set(message)=={'role','content'}
                 and message['role'] in ('system','developer','user','assistant'),'invalid_bounded_message')
        content=message['content']
        if isinstance(content,str):
            _require(bool(content),'invalid_bounded_message');text_messages.append(message);continue
        _require(type(content) is list and 1<=len(content)<=2*LEGACY_MAX_IMAGES+1,'invalid_bounded_message')
        text_parts=[]
        for part in content:
            _require(type(part) is dict,'invalid_bounded_content_part')
            if part.get('type')=='text':
                _require(set(part)=={'type','text'} and isinstance(part['text'],str) and part['text'], 'invalid_bounded_content_part')
                text_parts.append(part);continue
            _require(set(part)=={'type','image_url'} and part['type']=='image_url','invalid_bounded_content_part')
            image=part['image_url']
            _require(type(image) is dict and set(image)<= {'url','detail'} and 'url' in image
                     and image.get('detail','auto') in {'auto','low','high'},'invalid_bounded_image')
            url=image['url']
            _require(isinstance(url,str) and len(url)<=4*((LEGACY_MAX_IMAGE_BYTES+2)//3)+64,'provider_image_bound_exceeded')
            match=re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/]*={0,2})',url)
            _require(match is not None,'invalid_bounded_image')
            try:raw=base64.b64decode(match[2],validate=True)
            except ValueError as error:raise ValueError('invalid_bounded_image') from error
            _require(bool(raw) and (raw.startswith(b'\x89PNG\r\n\x1a\n') if match[1]=='png' else raw.startswith(b'\xff\xd8\xff')),'invalid_bounded_image')
            from PIL import Image
            try:
                with Image.open(io.BytesIO(raw)) as decoded:
                    width,height=decoded.size
                    _require(width>0 and height>0,'invalid_bounded_image')
            except (OSError,ValueError) as error:raise ValueError('invalid_bounded_image') from error
            image_count+=1;image_bytes+=len(raw)
            _require(image_count<=LEGACY_MAX_IMAGES and image_bytes<=LEGACY_MAX_IMAGE_BYTES,'provider_image_bound_exceeded')
            text_parts.append({'type':'text','text':'[bounded inline image]'})
        text_messages.append({'role':message['role'],'content':text_parts})
    _require(_input_upper_bound({**payload,'messages':text_messages})<=limits['maxInputTokens'],'provider_input_bound_exceeded')
    for key,expected in [('max_completion_tokens',limits['maxCompletionTokens']),('service_tier',limits['serviceTier'])]:
        if key in payload:_require(type(payload[key]) is type(expected) and payload[key]==expected,'provider_output_cap_mismatch' if key=='max_completion_tokens' else 'provider_service_tier_mismatch')
    return dict(deepcopy(payload),max_completion_tokens=limits['maxCompletionTokens'],service_tier=limits['serviceTier'])


def _cost(model, inputs, outputs):
    price = PRICES_USD_PER_MILLION[model]
    value = Fraction(price['inputWorstCase']) * inputs + Fraction(price['output']) * outputs
    return (value.numerator + value.denominator - 1) // value.denominator


def request_bounds(payload, limits):
    """Return D5 reservation dimensions; inputs are bounded, not measured."""
    selected = validate_request_limits(limits)
    capped = bounded_payload(payload, selected)
    upper = _input_upper_bound(capped)
    return {'requests': 1, 'inputTokens': upper, 'outputTokens': selected['maxCompletionTokens'],
            'wallTimeMs': selected['wallTimeMs'],
            'costMicrousd': _cost(capped['model'], upper, selected['maxCompletionTokens'])}


def _integer(value):
    return type(value) is int and 0 <= value <= MAX_METRIC


def _observation(observed):
    """Return validated measured dimensions or a safe fixed diagnostic."""
    if type(observed) is not dict:
        return None, 'missing_provider_observation'
    model = observed.get('providerModel', observed.get('actualModel'))
    if (type(model) is not str or model not in SUPPORTED_MODELS or
            observed.get('requestedModel') != model or
            ('actualModel' in observed and observed['actualModel'] != model)):
        return None, 'missing_or_mismatched_actual_model'
    if observed.get('serviceTier') != 'default':
        return None, 'missing_or_unsupported_service_tier'
    usage = observed.get('providerUsage')
    if type(usage) is not dict or not all(_integer(usage.get(key)) for key in ('inputTokens', 'outputTokens')):
        return None, 'missing_or_invalid_token_counts'
    inputs, outputs = usage['inputTokens'], usage['outputTokens']
    for key in ('cachedInputTokens', 'cacheWriteTokens', 'reasoningTokens', 'totalTokens'):
        if usage.get(key) is not None and not _integer(usage[key]):
            return None, 'inconsistent_token_details'
    cached, written, reasoning, total = (usage.get(key) for key in
        ('cachedInputTokens', 'cacheWriteTokens', 'reasoningTokens', 'totalTokens'))
    if ((cached is not None and cached > inputs) or (written is not None and written > inputs) or
        (cached is not None and written is not None and cached + written > inputs) or
        (reasoning is not None and reasoning > outputs) or (total is not None and total != inputs + outputs)):
        return None, 'inconsistent_token_details'
    elapsed = observed.get('elapsedSeconds')
    if type(elapsed) not in (int, float) or not 0 <= elapsed <= MAX_METRIC / 1000 or not math.isfinite(elapsed):
        return None, 'missing_or_invalid_elapsed_time'
    try:
        value = Fraction(str(elapsed)) * 1000
        milliseconds = (value.numerator + value.denominator - 1) // value.denominator
    except (ValueError, OverflowError):
        return None, 'missing_or_invalid_elapsed_time'
    charge = _cost(model, inputs, outputs)
    if charge > MAX_METRIC:
        return None, 'estimated_charge_exceeds_metric_range'
    return {'model': model, 'inputTokens': inputs, 'outputTokens': outputs,
        'cachedInputTokens': cached, 'cacheWriteTokens': written, 'reasoningTokens': reasoning,
        'totalTokens': total, 'wallTimeMs': milliseconds, 'costMicrousd': charge}, None


def usage_resolver(observation):
    """D5 callback: complete measurements plus conservative estimated charge.

    Unknown cache details can be priced at worst-case input rate without being
    converted to zero. Missing token/model/time/tier facts do not settle a row.
    Output completion tokens already include reasoning; never add reasoning twice.
    """
    measured, _ = _observation(observation)
    if measured is None:
        return None
    return {'requests': 1, **{key: measured[key] for key in
        ('inputTokens', 'outputTokens', 'wallTimeMs', 'costMicrousd')}}


def usage_cost_evidence(observation):
    """Safe provenance separate from the numeric durable-budget projection."""
    measured, reason = _observation(observation)
    model = measured['model'] if measured is not None else None
    common = {'currency': 'USD', 'priceAssumptionVersion': PRICE_ASSUMPTION_VERSION_BY_MODEL.get(model, PRICE_ASSUMPTION_VERSION),
        'priceBasis': 'frozen_worst_case_input_and_output_rate_assumption',
        'invoiceVerified': False, 'priceVerifiedAt': PRICE_VERIFIED_AT_BY_MODEL.get(model, PRICE_VERIFIED_AT),
        'priceSource': None if measured is None else PRICE_SOURCES[model],
        'costStatus': 'unknown' if measured is None else 'estimated_upper_bound',
        'reasonCode': reason}
    if measured is None:
        return dict(common, costMicrousd=None)
    return dict(common, **measured, serviceTier='default',
        ratesUsdPerMillion=deepcopy(PRICES_USD_PER_MILLION[measured['model']]),
        cacheDetailStatus='reported' if measured['cachedInputTokens'] is not None and
            measured['cacheWriteTokens'] is not None else 'unknown_or_partial',
        reasoningIncludedInOutputTokens=True)


def request_cost_evidence(payload, limits):
    """Explain the reservation upper bound without claiming actual usage/spend."""
    capped = bounded_payload(payload, limits)
    model = capped['model']
    return {'priceAssumptionVersion': PRICE_ASSUMPTION_VERSION_BY_MODEL[model],
        'priceSource': PRICE_SOURCES[model], 'priceVerifiedAt': PRICE_VERIFIED_AT_BY_MODEL[model],
        'priceBasis': 'frozen_worst_case_input_and_output_rate_assumption', 'invoiceVerified': False,
        'costStatus': 'request_reservation_upper_bound', 'model': capped['model'], 'serviceTier': 'default',
        'inputBoundBasis': 'serialized_messages_response_format_utf8_bytes_plus_framing_allowance',
        'framingBaseTokenAllowance': FRAMING_BASE_TOKEN_ALLOWANCE,
        'framingPerMessageTokenAllowance': FRAMING_PER_MESSAGE_TOKEN_ALLOWANCE,
        'ratesUsdPerMillion': deepcopy(PRICES_USD_PER_MILLION[capped['model']]),
        'bounds': request_bounds(capped, limits)}
