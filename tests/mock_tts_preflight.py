"""Native isolated-interpreter environment check; never submits a mock job."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from scripts import sermon_log_profile as profile
from scripts import sermon_mock_tts_worker as worker

SCHEMA = 'sermon-mock-worker-preflight-v1'
SCOPE = 'native_isolated_startup_environment_only'
CODES = frozenset({'ready', 'mock_tts_environment_not_scrubbed',
    'mock_tts_synthetic_accounting_required', 'isolated_startup_failed',
    'isolated_startup_timeout', 'preflight_setup_failed'})
# Fixed program, no request input or execution action. stderr is discarded, and
# only these two contract failures may leave the child as structured output.
CHILD = '''import json, sys
sys.path.insert(0, sys.argv[1])
from scripts import sermon_mock_tts_worker as worker
code = "ready"
try:
    worker.require_environment()
except Exception as exc:
    code = str(exc) if str(exc) in {"mock_tts_environment_not_scrubbed", "mock_tts_synthetic_accounting_required"} else "isolated_startup_failed"
print(json.dumps({"code": code}))
sys.exit(0 if code == "ready" else 1)
'''


def native_worker_preflight():
    """Use real profile propagation and worker scrubbing, without a DAG fixture.

    A temporary synthetic engineering log supplies normal accounting context;
    it creates no source/provider budget, request, task, or worker. No gate is
    mocked or loosened, and all caller secrets are removed by worker.environment.
    """
    started = time.monotonic()
    code = 'preflight_setup_failed'
    try:
        with tempfile.TemporaryDirectory(prefix='mock-tts-preflight-') as directory:
            root = Path(directory).resolve()
            with profile.session(root/'accounting', 'mock_worker_preflight',
                    work_kind='engineering', evidence_mode='synthetic'):
                environment = worker.environment(root/'launcher')
                try:
                    result = subprocess.run([sys.executable, '-I', '-c', CHILD,
                        str(Path(worker.__file__).resolve().parents[1])],
                        env=environment, cwd=root, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, timeout=15)
                    code = 'isolated_startup_failed'
                    if len(result.stdout) <= 128:
                        try:
                            value = json.loads(result.stdout)
                            candidate = value.get('code') if type(value) is dict and set(value) == {'code'} else None
                            if candidate in CODES and result.returncode == (0 if candidate == 'ready' else 1):
                                code = candidate
                        except (ValueError, TypeError):
                            pass
                except subprocess.TimeoutExpired:
                    code = 'isolated_startup_timeout'
                except (OSError, ValueError):
                    code = 'isolated_startup_failed'
    except Exception:
        code = 'preflight_setup_failed'
    return {'schemaVersion': SCHEMA, 'scope': SCOPE,
        'status': 'passed' if code == 'ready' else 'failed', 'reasonCode': code,
        'wallSeconds': round(time.monotonic()-started, 6),
        'jobSubmissions': 0, 'providerCalls': 0, 'modelCalls': 0,
        'productionEligible': False}


def require_native_worker_preflight(scenario):
    if scenario not in {'happy', 'failure', 'timeout'}:
        raise ValueError('invalid_preflight_scenario')
    result = native_worker_preflight()
    # This single bounded record is suitable for a runner's captured log. No
    # env values, arbitrary exception text or child stderr are emitted.
    print('mock-worker-preflight '+json.dumps({'scenario': scenario, **result}, sort_keys=True), flush=True)
    if result['status'] != 'passed':
        raise RuntimeError('mock_worker_preflight_failed:'+result['reasonCode'])
    return result
