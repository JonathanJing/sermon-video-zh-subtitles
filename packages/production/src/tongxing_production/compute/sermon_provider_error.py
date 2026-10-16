"""Bounded provider-error diagnostics. No raw message, headers or body survives."""
import json

SCHEMA = 'sermon-provider-error-diagnostic-v1'
MAX_ERROR_BYTES = 16384
CODES = frozenset({'invalid_request_error', 'invalid_value', 'invalid_parameter',
    'unsupported_parameter', 'unsupported_value', 'context_length_exceeded',
    'invalid_api_key', 'insufficient_quota', 'rate_limit_exceeded', 'model_not_found'})
PARAMS = frozenset({'model', 'messages', 'response_format', 'response_format.type',
    'max_completion_tokens', 'max_tokens', 'reasoning_effort', 'service_tier', 'temperature'})
REASONS = frozenset({'http_request_rejected', 'unsupported_parameter', 'unsupported_value',
    'json_mode_requires_json_word', 'invalid_api_key', 'insufficient_quota',
    'rate_limit_exceeded', 'context_length_exceeded', 'model_not_found', 'audio_file_invalid'})


def _summary(http_status,reason,param):
    # Preserve the legacy audio-reencode trigger using a fixed phrase only.
    text='Audio file might be corrupted or unsupported' if reason=='audio_file_invalid' else reason
    return f'HTTP {http_status}: {text}' + (f' / {param}' if param is not None else '')


def diagnostic(http_status, raw=b''):
    code = param = None
    reason = 'http_request_rejected'
    basis = 'http_status_only'
    if type(raw) is bytes and len(raw) <= MAX_ERROR_BYTES:
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise ValueError('duplicate_error_field')
                    result[key] = value
                return result
            value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
            error = value.get('error') if type(value) is dict else None
            if type(error) is dict:
                code = error.get('code') if type(error.get('code')) is str and error['code'] in CODES else None
                param = error.get('param') if type(error.get('param')) is str and error['param'] in PARAMS else None
                if code in REASONS:
                    reason, basis = code, 'error_code'
                message = error.get('message')
                if (http_status == 400 and param in (None, 'messages') and type(message) is str and
                        ('must contain the word' in message.lower() and 'json' in message.lower())):
                    reason, basis = 'json_mode_requires_json_word', 'known_message_pattern'
                elif (http_status==400 and param in PARAMS-{'messages'} and type(message) is str and
                        message.lower().startswith('unsupported parameter:')):
                    reason, basis = 'unsupported_parameter', 'known_message_pattern'
                elif (http_status==400 and type(message) is str and
                        'Audio file might be corrupted or unsupported' in message):
                    reason, basis = 'audio_file_invalid', 'known_message_pattern'
        except (ValueError, UnicodeError, RecursionError):
            pass
    if type(http_status) is not int or not 300 <= http_status <= 599:
        raise ValueError('invalid_error_http_status')
    summary = _summary(http_status,reason,param)
    return {'schemaVersion': SCHEMA, 'httpStatus': http_status, 'errorCode': code,
            'errorParam': param, 'reasonCode': reason, 'reasonBasis': basis, 'summary': summary}


def validate(value):
    if (type(value) is not dict or set(value) != {'schemaVersion','httpStatus','errorCode','errorParam','reasonCode','reasonBasis','summary'}
            or value['schemaVersion'] != SCHEMA or type(value['httpStatus']) is not int or
            not 300 <= value['httpStatus'] <= 599 or
            (value['errorCode'] is not None and (type(value['errorCode']) is not str or value['errorCode'] not in CODES)) or
            (value['errorParam'] is not None and (type(value['errorParam']) is not str or value['errorParam'] not in PARAMS)) or
            type(value['reasonCode']) is not str or value['reasonCode'] not in REASONS or
            value['reasonBasis'] not in ('http_status_only','error_code','known_message_pattern')):
        raise ValueError('invalid_provider_error_diagnostic')
    reason=value['reasonCode']
    if (value['reasonBasis']=='error_code' and reason != value['errorCode'] or
            value['reasonBasis']=='http_status_only' and reason!='http_request_rejected' or
            value['reasonBasis']=='known_message_pattern' and reason not in ('json_mode_requires_json_word','unsupported_parameter','audio_file_invalid')):
        raise ValueError('invalid_provider_error_diagnostic')
    if value['reasonBasis']=='known_message_pattern' and value['httpStatus']!=400:
        raise ValueError('invalid_provider_error_diagnostic')
    if reason=='json_mode_requires_json_word' and (value['httpStatus']!=400 or value['errorParam'] not in (None,'messages')):
        raise ValueError('invalid_provider_error_diagnostic')
    expected = _summary(value['httpStatus'],value['reasonCode'],value['errorParam'])
    if value['summary'] != expected: raise ValueError('invalid_provider_error_diagnostic')
    return dict(value)
