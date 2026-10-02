"""No model/API calls: exact dependency patch and immutable runtime binding."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_native_preview_runtime as subject
from scripts import sermon_review_contracts as c


class NativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def test_exact_patch_defers_only_optional_import_and_rejects_drift(self):
        original = ('import sox\n' + subject.CONTEXT + '        self.tfm = sox.Transformer()\n').encode()
        expected = (subject.CONTEXT + '        import sox\n        self.tfm = sox.Transformer()\n').encode()
        self.assertEqual(subject.patch_source(original, expected_before=c.bytes_sha256(original),
            expected_after=c.bytes_sha256(expected)), expected)
        with self.assertRaisesRegex(ValueError, 'upstream_patch_source_changed'):
            subject.patch_source(original + b'\n', expected_before=c.bytes_sha256(original))
        with self.assertRaisesRegex(ValueError, 'patch_result_changed'):
            subject.patch_source(original, expected_before=c.bytes_sha256(original), expected_after='f' * 64)

    def test_inventory_rejects_unbound_bytecode_and_unexpected_symlinks(self):
        (self.base / 'dependency.py').write_text('pass\n')
        before = subject.inventory(self.base)
        (self.base / 'dependency.pyc').write_bytes(b'untrusted')
        with self.assertRaisesRegex(ValueError, 'unbound_bytecode'): subject.inventory(self.base)
        self.assertEqual(subject.inventory(self.base, allow_bytecode=True), before)
        (self.base / 'dependency.pyc').unlink()
        (self.base / '__pycache__').mkdir()
        self.assertEqual(subject.inventory(self.base), before)
        (self.base / '__pycache__/unexpected').write_bytes(b'cache bytes')
        with self.assertRaisesRegex(ValueError,'unbound_bytecode'):subject.inventory(self.base)
        (self.base / '__pycache__/unexpected').unlink()
        (self.base / 'alias').symlink_to(self.base / 'dependency.py')
        with self.assertRaisesRegex(ValueError, 'unexpected_symlink'): subject.inventory(self.base)

    def manifest(self):
        root = self.base / 'runtime'; root.mkdir()
        package = root / subject.PACKAGE_FILE; package.parent.mkdir(parents=True)
        package.write_bytes(b'synthetic patched module')
        (root / 'bin').mkdir(); executable = root / 'bin/python'; executable.write_bytes(b'inert executable')
        info = dict(prefix=str(root), basePrefix=str(self.base / 'system'), version='3.13.15', platform='darwin', architecture='arm64')
        files = subject.inventory(root)
        inv = dict(schemaVersion=subject.INVENTORY_SCHEMA, files=files, treeSha256=c.canonical_sha256(files))
        inv_path = self.base / 'inventory.json'; subject.public.save_once(inv_path, inv)
        manifest = dict(schemaVersion=subject.SCHEMA, patchId=subject.PATCH_ID,
            runtimeRoot=str(root), upstreamRuntimeRoot=str(self.base / 'unchanged-upstream'),
            upstreamRuntimeTreeSha256='a'*64, python=dict(executable=str(executable), resolvedExecutable=str(executable),
                fileBytesSha256=subject.sha(executable), **info),
            patch=dict(relativePath=subject.PACKAGE_FILE,upstreamSha256=subject.UPSTREAM_SHA256,
                patchedSha256=subject.sha(package),upstreamDistribution='qwen-tts',upstreamVersion='0.1.1'),
            inventory=dict(artifactPath=str(inv_path),fileBytesSha256=subject.sha(inv_path),treeSha256=inv['treeSha256'],fileCount=len(files)),
            builderCodeSha256=subject.sha(Path(subject.__file__)),productionEligible=False,
            scope='synthetic runtime fixture never executable')
        manifest['runtimeId'] = c.canonical_sha256(manifest)
        path = self.base / 'manifest.json';subject.public.save_once(path, manifest)
        return path, package, executable

    def test_tree_interpreter_and_process_must_match_without_execute(self):
        path, package, executable = self.manifest()
        with patch.object(subject,'PATCHED_SHA256',subject.sha(package)):
            binding = subject.validate(path)
            self.assertFalse(subject.public.read_snapshot(path)[0]['productionEligible'])
            with self.assertRaisesRegex(ValueError,'process_mismatch'): subject.validate(path,require_process=True)
            (package.parent / 'extra.py').write_text('unexpected')
            with self.assertRaisesRegex(ValueError,'dependency_tree_changed'): subject.validate(path)
            (package.parent / 'extra.py').unlink()
            executable.write_bytes(b'changed interpreter')
            with self.assertRaisesRegex(ValueError,'dependency_tree_changed'): subject.validate(path)
        self.assertEqual(binding['runtimeManifest']['fileBytesSha256'],subject.sha(path))

    def test_build_requires_exact_upstream_and_never_overwrites_existing_output(self):
        source=self.base/'source'; (source/subject.PACKAGE_FILE).parent.mkdir(parents=True)
        (source/subject.PACKAGE_FILE).write_bytes(b'unknown upstream')
        with self.assertRaisesRegex(ValueError,'upstream_patch_source_changed'):subject.build(source,self.base/'new')
        self.assertFalse((self.base/'new').exists())
        with self.assertRaisesRegex(ValueError,'new_independent_output'):subject.build(source,source)


if __name__ == '__main__':unittest.main()
