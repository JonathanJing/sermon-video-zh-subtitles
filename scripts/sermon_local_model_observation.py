"""Explicit local-model identity: no provider tokens, price or quality inference."""
import re
from scripts import sermon_accounting as accounting

CODE = 'local_model_observation'
SCHEMA = 'sermon-local-model-observation-v1'
FIELDS = {'schemaVersion', 'model', 'checkpointSha256', 'inputSha256', 'outputSha256',
          'status', 'elapsedSeconds', 'usageProvenance', 'providerTokens', 'providerCostUsd'}


def safe_observation(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value.get('schemaVersion') != SCHEMA:
        raise ValueError('invalid_local_model_observation')
    if not isinstance(value['model'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?', value['model']) or len(value['model']) > 200:
        raise ValueError('invalid_local_model_identifier')
    for key in ('checkpointSha256', 'inputSha256', 'outputSha256'):
        if value[key] is not None and (not isinstance(value[key], str) or not re.fullmatch(r'[a-f0-9]{64}', value[key])):
            raise ValueError('invalid_local_model_hash')
    if value['status'] not in {'started', 'completed', 'failed'} or value['usageProvenance'] != 'local_execution_no_provider_receipt' or value['providerTokens'] is not None or value['providerCostUsd'] is not None:
        raise ValueError('invalid_local_model_scope')
    if value['elapsedSeconds'] is not None and accounting._number(value['elapsedSeconds']) is None:
        raise ValueError('invalid_local_model_elapsed')
    return dict(value)


def record(model, checkpoint_sha256, input_sha256, *, status, output_sha256=None, elapsed_seconds=None, span_id=None):
    fields = safe_observation(dict(schemaVersion=SCHEMA, model=model, checkpointSha256=checkpoint_sha256,
        inputSha256=input_sha256, outputSha256=output_sha256, status=status, elapsedSeconds=elapsed_seconds,
        usageProvenance='local_execution_no_provider_receipt', providerTokens=None, providerCostUsd=None))
    event = {'event': 'log', 'code': CODE, 'level': 'INFO', 'fields': fields}
    if span_id is not None:
        if accounting._label(span_id, None) is None: raise ValueError('invalid_local_model_span')
        event['spanId'] = span_id
    accounting._emit(event)
