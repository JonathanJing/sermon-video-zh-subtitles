"""The per-process executable digest memo returns today's identity and re-hashes on change."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tongxing_production.compute import outcomes


def reference_identity(path):
    """The pre-memo algorithm, kept verbatim as the digest oracle."""
    resolved = Path(path).resolve(strict=True)
    identity = {'resolvedPath': str(resolved), 'sha256': hashlib.sha256(resolved.read_bytes()).hexdigest()}
    bundled = resolved.parent.parent / 'CodexCLI.app/Contents/MacOS/codex'
    if bundled.is_file():
        identity['bundleBinarySha256'] = hashlib.sha256(bundled.read_bytes()).hexdigest()
    return identity


def write_executable(path, text, *, age_seconds=3600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o700)
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(path, (old, old))


class ExecutableIdentityMemoTests(unittest.TestCase):
    def setUp(self):
        outcomes._EXECUTABLE_IDENTITIES.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        # ChatGPT.app layout: bin/codex is a small shim next to the bundled CLI.
        self.shim = self.root / 'codex-cli/bin/codex'
        self.bundled = self.root / 'codex-cli/CodexCLI.app/Contents/MacOS/codex'
        write_executable(self.shim, '#!/bin/sh\nexec bundled "$@"\n')
        write_executable(self.bundled, 'bundled-binary-v1' * 1000)
        self.link = self.root / 'codex'
        self.link.symlink_to(self.shim)
        real = outcomes._file_sha256
        self.hashed = []
        def counting(path):
            self.hashed.append(Path(path).name if Path(path) != self.bundled else 'bundled')
            return real(path)
        patcher = patch.object(outcomes, '_file_sha256', side_effect=counting)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(outcomes._EXECUTABLE_IDENTITIES.clear)

    def test_memoized_identity_matches_reference_and_request_digest(self):
        expected = reference_identity(self.link)
        self.assertIn('bundleBinarySha256', expected)
        first = outcomes.executable_identity(self.link)
        second = outcomes.executable_identity(self.link)
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertEqual(list(first), list(expected))
        self.assertEqual(self.hashed, ['codex', 'bundled'])
        # Callers own the returned dict; mutating it cannot poison the memo.
        second['sha256'] = 'tampered'
        self.assertEqual(outcomes.executable_identity(self.link), expected)
        def invoke(*, codex_cli):
            return None
        memoized = outcomes.request_identity(invoke, (), {'codex_cli': self.link}, 'test')
        outcomes._EXECUTABLE_IDENTITIES.clear()
        with patch.object(outcomes, 'executable_identity', side_effect=reference_identity):
            self.assertEqual(memoized, outcomes.request_identity(invoke, (), {'codex_cli': self.link}, 'test'))

    def test_rehashes_after_size_mtime_or_inode_change(self):
        outcomes.executable_identity(self.link)
        cases = {
            'bundled size': lambda: write_executable(self.bundled, 'bundled-binary-v22' * 1000, age_seconds=1800),
            'bundled mtime, same size': lambda: write_executable(self.bundled, 'bundled-binary-v33' * 1000, age_seconds=900),
            'shim mtime, same size': lambda: write_executable(self.shim, '#!/bin/sh\nexec bundlex "$@"\n', age_seconds=900),
        }
        for name, change in cases.items():
            with self.subTest(name):
                change()
                self.hashed.clear()
                self.assertEqual(outcomes.executable_identity(self.link), reference_identity(self.link))
                self.assertEqual(self.hashed, ['codex', 'bundled'])
        with self.subTest('replaced file, same size and mtime'):
            stat = self.bundled.stat()
            replacement = self.bundled.with_name('codex.new')
            write_executable(replacement, 'bundled-binary-v44' * 1000, age_seconds=0)
            os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            os.replace(replacement, self.bundled)
            self.hashed.clear()
            self.assertEqual(outcomes.executable_identity(self.link), reference_identity(self.link))
            self.assertEqual(self.hashed, ['codex', 'bundled'])
        with self.subTest('bundled binary removed'):
            self.bundled.unlink()
            identity = outcomes.executable_identity(self.link)
            self.assertNotIn('bundleBinarySha256', identity)
            self.assertEqual(identity, reference_identity(self.link))

    def test_recently_modified_file_is_not_memoized(self):
        write_executable(self.bundled, 'bundled-binary-v1' * 1000, age_seconds=0)
        outcomes.executable_identity(self.link)
        outcomes.executable_identity(self.link)
        self.assertEqual(self.hashed, ['codex', 'bundled', 'codex', 'bundled'])

    def test_concurrent_callers_share_one_hash(self):
        expected = reference_identity(self.link)
        start = threading.Barrier(16)
        def call(_):
            start.wait()
            return outcomes.executable_identity(self.link)
        with ThreadPoolExecutor(16) as pool:
            results = list(pool.map(call, range(64)))
        self.assertTrue(all(result == expected for result in results))
        self.assertEqual(self.hashed, ['codex', 'bundled'])

    def test_invalid_executable_is_still_rejected_after_memo(self):
        outcomes.executable_identity(self.link)
        self.shim.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'api_cli_executable_identity_invalid'):
            outcomes.executable_identity(self.link)


if __name__ == '__main__':
    unittest.main()
