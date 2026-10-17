"""Versioned Codex purchased-credit equivalent, never an invoice/quota debit.

No network, account sampling or API price conversion. Cached input is a subset
of input and reasoning is a subset of output. Missing counters remain unknown.
"""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

RATE_CARD_PATH = Path(__file__).resolve().parents[1] / 'config/codex-credit-rates-2026-10-05.json'
RATE_CARD_BYTES = RATE_CARD_PATH.read_bytes()
RATE_CARD = json.loads(RATE_CARD_BYTES)
RATE_CARD_SHA256 = hashlib.sha256(RATE_CARD_BYTES).hexdigest()
SCHEMA = 'codex-credit-usage-v1'
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}')


def _label(value):
    return value if isinstance(value, str) and LABEL.fullmatch(value) else None


def _tier(value):
    return 'default' if value == 'standard' else value if value in ('default', 'fast', 'ultrafast') else None


def estimate_credit_usage(model, usage, *, requested_service_tier=None, server_model=None,
                          server_service_tier=None, status='completed', cache_hit=None):
    """Estimate reported usage at the frozen rate card, or explain why unknown.

    A requested tier/model is an explicit assumption when the host cannot
    report its effective identity. This is not an included-limit conversion.
    """
    model_source = 'server' if server_model is not None else 'requested'
    selected_model = _label(server_model if server_model is not None else model)
    requested_tier = _tier(requested_service_tier)
    selected_tier = _tier(server_service_tier) if server_service_tier is not None else requested_tier
    tier_source = 'server' if server_service_tier is not None else 'requested' if requested_tier else 'unavailable'
    rates = RATE_CARD['ratesPerMillionTokens'].get(selected_model)
    multiplier = RATE_CARD['purchasedCreditMultipliers'].get(selected_tier)
    result = dict(schemaVersion=SCHEMA, status='unknown', estimatedCredits=None,
        actualCredits=None, actualQuotaUsage=None, basis=RATE_CARD['basis'],
        model=selected_model, modelSource=model_source, requestedServiceTier=requested_tier,
        appliedServiceTier=selected_tier, tierSource=tier_source,
        rateCardVersion=RATE_CARD['version'], rateCardSha256=RATE_CARD_SHA256,
        verifiedAt=RATE_CARD['verifiedAt'], sources=list(RATE_CARD['sources']),
        ratesPerMillionTokens=dict(rates) if rates else None, speedMultiplier=multiplier,
        reason='usage_not_reported')
    if status not in {'completed', 'failed'}:
        result['reason'] = 'conflicting_evidence' if status == 'conflict' else 'outcome_not_finished'
        return result
    if cache_hit is True:
        result.update(status='cache_reuse', estimatedCredits=0, reason='no_new_model_dispatch')
        return result
    if rates is None:
        result['reason'] = 'model_rate_not_available'
        return result
    if multiplier is None:
        result['reason'] = 'service_tier_not_available'
        return result
    if selected_tier == 'ultrafast' and selected_model not in RATE_CARD['ultrafastModels']:
        result.update(reason='unsupported_speed_model', speedMultiplier=None)
        return result
    usage = usage if isinstance(usage, dict) else {}
    counts = [usage.get(k) for k in ('inputTokens', 'cachedInputTokens', 'outputTokens')]
    if any(v is None for v in counts):
        return result
    if any(type(v) is not int or not 0 <= v <= 10**15 for v in counts) or counts[1] > counts[0]:
        result['reason'] = 'invalid_usage_counters'
        return result
    input_tokens, cached_tokens, output_tokens = counts
    total = ((input_tokens - cached_tokens) * Decimal(str(rates['input']))
             + cached_tokens * Decimal(str(rates['cachedInput']))
             + output_tokens * Decimal(str(rates['output']))) * Decimal(str(multiplier)) / 1_000_000
    result.update(status='estimated', estimatedCredits=float(total.quantize(Decimal('0.000000001'))),
        reason='reported_failed_usage_subtotal' if status == 'failed' else
               'requested_identity_assumption' if model_source == 'requested' or tier_source == 'requested' else 'reported_identity')
    return result


def safe_credit_usage(value, model, usage, *, status='completed', cache_hit=None):
    """Reject extra/private fields, stale rate identities and altered estimates."""
    if not isinstance(value, dict):
        raise ValueError('invalid_codex_credit_usage')
    expected = estimate_credit_usage(model, usage,
        requested_service_tier=value.get('requestedServiceTier'),
        server_model=value.get('model') if value.get('modelSource') == 'server' else None,
        server_service_tier=value.get('appliedServiceTier') if value.get('tierSource') == 'server' else None,
        status=status, cache_hit=cache_hit)
    if json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
        raise ValueError('invalid_codex_credit_usage')
    return expected
