"""Hash-only historical model provenance; never a current provider/spend receipt."""
import hashlib
import json
from pathlib import Path
try:
    from scripts import sermon_accounting as accounting
except ImportError:
    import sermon_accounting as accounting

CODE = 'model_cache_observation'
SCHEMA = 'sermon-model-cache-observation-v1'
HASHES = {'cacheSha256', 'originCacheSha256', 'rawReceiptSha256', 'payloadSha256', 'responseIdSha256'}
FIELDS = HASHES | {'schemaVersion', 'role', 'requestedModel', 'model', 'provider', 'usage',
                   'usageProvenance', 'reuseMode', 'newProviderCalls', 'historicalCostUsd'}
MODES = {'carried_forward_group', 'validated_cache', 'raw_response_recovery'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_observation(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value.get('schemaVersion') != SCHEMA:
        raise ValueError('invalid_model_cache_observation')
    for key in HASHES:
        item = value[key]
        if item is not None and (not isinstance(item, str) or len(item) != 64 or any(c not in '0123456789abcdef' for c in item)):
            raise ValueError('invalid_model_cache_hash')
    if (value['role'] not in {'translator', 'reviewer'} or value['reuseMode'] not in MODES
            or type(value['newProviderCalls']) is not int or value['newProviderCalls'] != 0
            or value['historicalCostUsd'] is not None or value['provider'] != 'openai'
            or value['usageProvenance'] not in {'historical_bound_provider_receipt', 'missing_raw_receipt', 'unbound_raw_receipt'}):
        raise ValueError('invalid_model_cache_provenance')
    for key in ('requestedModel', 'model'):
        if value[key] is not None and accounting._label(value[key], None) is None:
            raise ValueError('invalid_model_cache_label')
    usage = value['usage']
    if not isinstance(usage, dict) or set(usage) != set(accounting.normalize_usage(None)) or any(
            x is not None and accounting._number(x) is None for x in usage.values()):
        raise ValueError('invalid_model_cache_usage')
    if value['usageProvenance'] != 'historical_bound_provider_receipt' and any(x is not None for x in usage.values()):
        raise ValueError('unbound_model_cache_usage')
    return {**value, 'usage': dict(usage)}


def record(role, saved, output, *, mode, origin=None):
    """Observe already admitted caches, without changing business admission rules."""
    raw_path = Path(output).with_suffix('.raw.json')
    raw, raw_hash = None, None
    if raw_path.is_file():
        raw_hash = sha(raw_path)
        try:
            raw = json.loads(raw_path.read_text())
        except (ValueError, UnicodeError):
            pass
    response = raw.get('response') if isinstance(raw, dict) else None
    bound = (isinstance(response, dict) and raw.get('payloadSha256') == saved.get('payloadSha256')
             and response.get('id') == saved.get('requestId') and response.get('model') == saved.get('model'))
    fields = dict(schemaVersion=SCHEMA, role=role, requestedModel=saved.get('model'),
        model=response.get('model') if bound else None, provider='openai', reuseMode=mode,
        cacheSha256=sha(output), originCacheSha256=sha(origin) if origin is not None else sha(output),
        rawReceiptSha256=raw_hash, payloadSha256=saved.get('payloadSha256'),
        responseIdSha256=hashlib.sha256(saved['requestId'].encode()).hexdigest(),
        usage=accounting.normalize_usage(response.get('usage') if bound else None),
        usageProvenance='historical_bound_provider_receipt' if bound else 'missing_raw_receipt' if raw_hash is None else 'unbound_raw_receipt',
        newProviderCalls=0, historicalCostUsd=None)
    accounting._emit({'event': 'log', 'code': CODE, 'level': 'INFO', 'fields': safe_observation(fields)})
