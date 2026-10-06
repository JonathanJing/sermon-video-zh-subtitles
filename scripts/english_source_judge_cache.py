"""Single-flight L1 requests. An abandoned request remains unknown, never retried."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from scripts import sermon_sentence_interpretation as contract
from scripts.run_sentence_interpretation_models import RUN_SCHEMA, _model_result


def _atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cached_call(*, out: Path, stage: str, payload: dict[str, Any], api_key: str,
                requested_model: str, caller: Callable) -> tuple[dict, dict]:
    # Preserve the established request identity and receipt format. Both prewarm
    # and final runs resolve out to the same canonical cache root.
    request = {'schemaVersion': RUN_SCHEMA, 'stage': stage, 'payload': payload}
    request_hash = contract.json_sha256(request)
    directory = out.resolve() / 'cache'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{stage}-{request_hash}.json'
    marker = path.with_suffix('.started.json')
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            receipt = json.loads(path.read_text(encoding='utf-8'))
            if (receipt.get('requestSha256') != request_hash or receipt.get('request') != request
                    or receipt.get('responseSha256') != contract.json_sha256(receipt.get('response'))):
                raise ValueError('Cached L1 request or response identity changed')
        else:
            if marker.exists():
                raise ValueError(f'Unknown L1 request outcome; reconcile original response before retry: {marker}')
            admission = getattr(caller, 'admit_resource', None)
            if admission is not None:
                admission(payload)
            _atomic(marker, {'requestSha256': request_hash, 'request': request,
                             'status': 'started_response_unconfirmed'})
            response = caller(api_key, payload)
            # Save before parsing: an invalid returned response cannot trigger a
            # second paid call. A crash before this save leaves the marker unknown.
            receipt = {'schemaVersion': RUN_SCHEMA, 'request': request,
                       'requestSha256': request_hash, 'response': response,
                       'responseSha256': contract.json_sha256(response)}
            _atomic(path, receipt)
        result = _model_result(receipt['response'], requested_model)
        return result, {'path': str(path), 'sha256': contract.sha256(path),
                        'requestSha256': request_hash,
                        'responseId': receipt['response'].get('id'),
                        'model': receipt['response'].get('model')}


def reconcile_returned_response(*, marker_path: Path, response: dict,
                                expected_request_sha256: str, requested_model: str) -> Path:
    """Bind an explicitly recovered provider response to the original request.

    This operation never invokes the provider or deletes the unknown marker.
    A receipt is still machine evidence, and semantic admission remains in judge.
    """
    if not marker_path.name.endswith('.started.json'):
        raise ValueError('Expected original started marker')
    path = marker_path.with_name(marker_path.name.removesuffix('.started.json') + '.json')
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
        request = marker.get('request')
        if (marker.get('requestSha256') != expected_request_sha256
                or contract.json_sha256(request) != expected_request_sha256
                or request.get('payload', {}).get('model') != requested_model):
            raise ValueError('Reconciliation request identity changed')
        _model_result(response, requested_model)
        if not isinstance(response.get('id'), str) or not response['id']:
            raise ValueError('Reconciliation requires original provider response ID')
        receipt = {'schemaVersion': RUN_SCHEMA, 'request': request,
                   'requestSha256': expected_request_sha256, 'response': response,
                   'responseSha256': contract.json_sha256(response)}
        if path.exists():
            if json.loads(path.read_text(encoding='utf-8')) != receipt:
                raise ValueError('Original returned response already exists and differs')
        else:
            _atomic(path, receipt)
    return path
