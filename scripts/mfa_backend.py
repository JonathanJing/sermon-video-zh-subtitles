"""MacBook-first MFA selection with a bounded, explicit Spark failover policy."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from scripts import mfa_alignment as local, mfa_spark as spark


class LocalRuntimeUnavailable(RuntimeError):
    pass


def add_arguments(parser):
    import argparse
    parser.add_argument('--mfa-spark-fallback', action=argparse.BooleanOptionalAction,
                        default=os.environ.get('MFA_SPARK_FALLBACK', '1').lower() not in ('0', 'false', 'no'))
    for name, default in [('executable', spark.DEFAULT_ROOT + '/bin/mfa-run'),
                          ('dictionary', spark.DEFAULT_ROOT + '/models/english_mfa.dict'),
                          ('acoustic_model', spark.DEFAULT_ROOT + '/models/english_mfa.zip'),
                          ('g2p_model', spark.DEFAULT_ROOT + '/models/english_us_mfa.zip')]:
        parser.add_argument('--mfa-spark-' + name.replace('_', '-'),
                            default=os.environ.get('MFA_SPARK_' + name.upper(), default))


def options(args):
    from scripts.sermon_pipeline import mfa_options
    remote = spark.transport_options(args)
    for name, target, default in [('executable', 'mfa_executable', spark.DEFAULT_ROOT + '/bin/mfa-run'),
                                  ('dictionary', 'dictionary_path', spark.DEFAULT_ROOT + '/models/english_mfa.dict'),
                                  ('acoustic_model', 'acoustic_model', spark.DEFAULT_ROOT + '/models/english_mfa.zip'),
                                  ('g2p_model', 'g2p_model', spark.DEFAULT_ROOT + '/models/english_us_mfa.zip')]:
        remote[target] = getattr(args, 'mfa_spark_' + name, None) or os.environ.get('MFA_SPARK_' + name.upper(), default)
    local_options = mfa_options(args)
    remote['spoken_forms_path'] = local_options.get('spoken_forms_path')
    return {'local_options':local_options, 'spark_options':remote,
            'allow_spark_fallback':getattr(args, 'mfa_spark_fallback', os.environ.get('MFA_SPARK_FALLBACK', '1').lower() not in ('0','false','no'))}


def local_identity(options):
    # Reference configuration errors are not a runtime outage, and must never
    # be hidden by failover. Validate user supplied forms before dependency checks.
    local._spoken_forms(options.get('spoken_forms_path'))
    executable = shutil.which(str(options['mfa_executable'])) or str(options['mfa_executable'])
    required = [executable, options.get('dictionary_path'), options.get('acoustic_model')]
    if options.get('g2p_model'):
        required.append(options['g2p_model'])
    if any(not value or not Path(value).expanduser().is_file() for value in required):
        raise LocalRuntimeUnavailable('Mac MFA runtime or model files unavailable')
    if not os.access(Path(executable).expanduser(), os.X_OK) or not shutil.which('ffmpeg'):
        raise LocalRuntimeUnavailable('Mac MFA executable or ffmpeg unavailable')
    checked = local.preflight(**options)
    env = os.environ.copy()
    env['PATH'] = str(Path(checked['mfa_executable']).parent) + os.pathsep + env.get('PATH', '')
    try:
        version = subprocess.run([checked['mfa_executable'], 'version'], capture_output=True,
                                 text=True, check=True, timeout=60, env=env).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocalRuntimeUnavailable('Mac MFA runtime cannot start') from exc
    if not version:
        raise LocalRuntimeUnavailable('Mac MFA runtime version unavailable')
    # Bind Conda native dependency builds if this executable lives in an env.
    conda = Path(checked['mfa_executable']).parent.parent / 'conda-meta'
    env_root = Path(checked['mfa_executable']).parent.parent
    native_files = sorted(env_root.glob('lib/python*/site-packages/_kalpy*.so'))
    runtime = {'version':version, 'nativeKalpy':{str(p):local._sha(p) for p in native_files}, 'adapterSha256':local._sha(local.__file__),
               'executionHost':os.uname().nodename, 'executionPlatform':os.uname().sysname,
               'files':{k:{'path':v, 'sha256':local._sha(v)} if v else None
                        for k,v in checked.items() if k != 'spoken_forms_sha256'},
               'condaRecords':{p.name:local._sha(p) for p in sorted(conda.glob('*.json'))}}
    return {'schemaVersion':1, 'backend':'macbook-local', 'runtime':runtime}


def preflight(*, local_options, spark_options, allow_spark_fallback=True):
    try:
        return local_identity(local_options)
    except LocalRuntimeUnavailable as exc:
        if not allow_spark_fallback:
            raise
        selected = dict(spark.preflight(**spark_options))
        selected["fallbackReason"] = {"phase":"preflight", "code":"local-runtime-unavailable", "detail":str(exc)}
        return selected


def _runtime_failure(exc):
    # Adapter data/quality errors are ValueError and never reach this condition.
    # General MFA nonzero exits can mean invalid corpus data: do not retry them.
    cause = exc
    while cause is not None:
        if isinstance(cause, (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, MemoryError)):
            return True
        if isinstance(cause, subprocess.CalledProcessError) and cause.returncode in (-9, -11, 137, 139):
            return True
        cause = cause.__cause__
    return False


def align_reference_chunks(chunks, clip_path, outdir, *, local_options, spark_options, allow_spark_fallback=True):
    # Pin inputs before dispatch; failover cannot quietly consume modified text,
    # audio or spoken forms.
    audio_sha = local._sha(clip_path)
    frozen = json.loads(json.dumps(chunks))
    forms = local_options.get('spoken_forms_path')
    forms_sha = local._sha(forms) if forms else None
    spoken_forms = local._spoken_forms(forms)
    previous_end, nonempty = 0.0, False
    for chunk in frozen:
        start, end = float(chunk['start']), float(chunk['end'])
        if not math.isfinite(start) or not math.isfinite(end) or start < previous_end - 1e-6 or end <= start:
            raise ValueError('Reference chunks must have finite nonoverlapping positive durations')
        if str(chunk.get('text', '')).strip():
            local._reference(chunk['text'], spoken_forms)
            nonempty = True
        previous_end = end
    if not nonempty:
        raise ValueError('No reference chunks for MFA')
    selected = preflight(local_options=local_options, spark_options=spark_options,
                         allow_spark_fallback=allow_spark_fallback)
    if selected['backend'] == 'macbook-local':
        try:
            runtime_key = hashlib.sha256(json.dumps(selected['runtime'], sort_keys=True).encode()).hexdigest()
            segments = local.align_reference_chunks(frozen, clip_path, Path(outdir)/runtime_key, **local_options)
        except (RuntimeError, OSError, subprocess.SubprocessError, MemoryError) as exc:
            if not allow_spark_fallback or not _runtime_failure(exc):
                raise
            if local._sha(clip_path) != audio_sha or (local._sha(forms) if forms else None) != forms_sha:
                raise ValueError('MFA inputs changed before Spark fallback') from exc
            selected = dict(spark.preflight(**spark_options))
            selected["fallbackReason"] = {"phase":"alignment", "code":"local-runtime-failed", "detail":type(exc.__cause__ or exc).__name__}
            segments = spark.align_reference_chunks(frozen, clip_path, outdir, **spark_options)
    else:
        segments = spark.align_reference_chunks(frozen, clip_path, outdir, **spark_options)
    if local._sha(clip_path) != audio_sha or (local._sha(forms) if forms else None) != forms_sha:
        raise ValueError('MFA inputs changed during alignment')
    if selected['backend'] == 'dgx-spark-ssh':
        # Actual alignment response, not only an earlier preflight observation.
        receipt = Path(segments[0]['mfaManifest']).with_name('spark-runtime.json')
        observed = json.loads(receipt.read_text())
        reason = selected.get('fallbackReason')
        selected = {key:observed[key] for key in ('schemaVersion', 'backend', 'runtime')}
        if reason:
            selected['fallbackReason'] = reason
    for segment in segments:
        segment['alignmentExecutionBackend'] = selected['backend']
    Path(outdir).mkdir(parents=True, exist_ok=True)
    local._write(Path(outdir)/'backend.json', selected)
    return segments
