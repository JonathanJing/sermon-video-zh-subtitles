import io
import hashlib
import sys
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import mfa_spark as spark


class SparkTransportTests(unittest.TestCase):
    def options(self):
        return dict(host='user@spark', python='/env/bin/python', root='/jobs',
                    mfa_executable='/env/bin/mfa', dictionary_path='/models/dict', acoustic_model='/models/acoustic')

    def test_transport_streams_bundle_and_preserves_remote_model_paths(self):
        def execute(command, **kwargs):
            with tarfile.open(fileobj=kwargs['stdin']) as bundle:
                self.assertEqual(bundle.getnames(), ['request.json', 'mfa_alignment.py'])
                request = json.load(bundle.extractfile('request.json'))
                self.assertEqual(request['options']['dictionary_path'], '/models/dict')
            self.assertEqual(command[0], 'ssh')
            self.assertNotIn('StrictHostKeyChecking=no', command)
            return subprocess.CompletedProcess(command, 0, b'{"schemaVersion":1,"backend":"dgx-spark-ssh","runtime":{}}')
        with patch.object(spark.subprocess, 'run', side_effect=execute):
            self.assertEqual(spark.preflight(**self.options())['backend'], 'dgx-spark-ssh')

    def test_transport_uploads_symlinked_audio_as_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / 'original.wav'
            audio.write_bytes(b'cached audio')
            link = root / 'audio.wav'
            link.symlink_to(audio)

            def execute(command, **kwargs):
                with tarfile.open(fileobj=kwargs['stdin']) as bundle:
                    member = bundle.getmember('audio')
                    self.assertTrue(member.isfile())
                    self.assertEqual(bundle.extractfile(member).read(), b'cached audio')
                return subprocess.CompletedProcess(command, 0, b'{"schemaVersion":1,"backend":"dgx-spark-ssh","runtime":{}}')

            with patch.object(spark.subprocess, 'run', side_effect=execute):
                spark._call('align', chunks=[{'text': 'Hello.'}], clip_path=link, **self.options())

    def test_nested_relay_uses_mini_key_and_host_alias(self):
        with patch.object(spark.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"schemaVersion":1,"backend":"dgx-spark-ssh"}')) as run:
            spark.preflight(**self.options(), relay_host='jony@100.1.2.3', relay_host_key_alias='mini.local')
        command = run.call_args.args[0]
        self.assertIn('HostKeyAlias=mini.local', command)
        self.assertEqual(command[-2], 'jony@100.1.2.3')
        self.assertIn('user@spark', command[-1])

    def test_failure_never_calls_local_mfa(self):
        with patch.object(spark.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ssh', 180)) as run:
            with self.assertRaisesRegex(RuntimeError, 'no local fallback'):
                spark.preflight(**self.options())
        self.assertEqual(run.call_count, 1)

    def test_rejects_transport_option_injection_before_execution(self):
        for changes in ({'host':'-oProxyCommand=bad'}, {'proxy_jump':'bad;cmd'}, {'relay_host':'bad;cmd'}, {'root':'relative'}):
            with self.subTest(changes=changes), patch.object(spark.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    spark.preflight(**{**self.options(), **changes})
                run.assert_not_called()

    def test_worker_extracts_stream_and_identifies_runtime(self):
        # Exercise the real tar/bootstrap protocol locally; only the hardware
        # assertion is disabled for this synthetic transport test.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root/'mfa'
            executable.write_text('#!/bin/sh\necho 3.4.2\n')
            executable.chmod(0o755)
            adapter = b"import hashlib\ndef _sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()\ndef preflight(**kw): return kw\n"
            request = {'action':'preflight', 'adapterSha256':hashlib.sha256(adapter).hexdigest(),
                       'options':{'mfa_executable':str(executable)}}
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as bundle:
                for name, data in [('request.json', json.dumps(request).encode()), ('mfa_alignment.py', adapter)]:
                    entry = tarfile.TarInfo(name); entry.size = len(data)
                    bundle.addfile(entry, io.BytesIO(data))
            worker = spark.WORKER.replace("if sys.platform != 'linux' or os.uname().machine not in ('aarch64', 'arm64'):", 'if False:')
            completed = subprocess.run([sys.executable, '-c', worker, str(root/'jobs')],
                                       input=stream.getvalue(), capture_output=True, check=True)
            result = json.loads(completed.stdout)
            self.assertEqual(result['runtime']['version'], '3.4.2')
            self.assertEqual(result['runtime']['files']['mfa_executable']['sha256'], spark._sha(executable))

    def test_rejects_changed_reference_on_return(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = root/'audio'; clip.write_bytes(b'fake')
            response = {'audioSha256':spark._sha(clip), 'requestSha256':'a'*64,
                        'manifest':{'identity':{'audioSha256':spark._sha(clip)}},
                        'segments':[{'text':'Changed.'}]}
            with patch.object(spark, '_call', return_value=response):
                with self.assertRaisesRegex(ValueError, 'changed frozen text'):
                    spark.align_reference_chunks([{'text':'Original.'}], clip, root/'out', **self.options())
