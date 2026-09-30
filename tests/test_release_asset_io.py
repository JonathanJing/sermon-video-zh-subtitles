import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import release_asset_io as assets


class ReleaseAssetIOTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.mp3'
        self.data = b'bound fixture bytes' * 100000
        self.source.write_bytes(self.data)
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.public = self.root / 'public'

    def copy(self, **options):
        return assets.copy_bound_asset(options.get('source', self.source), self.public,
                                       options.get('path', '/media/page/ko.mp3'), options.get('sha', self.sha))

    def test_streamed_bytes_match_admitted_identity_without_approval_claim(self):
        row = self.copy()
        self.assertEqual(row, {'path': '/media/page/ko.mp3', 'sha256': self.sha, 'sizeBytes': len(self.data)})
        self.assertEqual((self.public / 'media/page/ko.mp3').read_bytes(), self.data)
        self.assertFalse(list(self.public.rglob('.asset-*')))
        with self.assertRaisesRegex(ValueError, 'already_exists'):
            self.copy()
        self.assertEqual((self.public / 'media/page/ko.mp3').read_bytes(), self.data)

    def test_changed_source_is_rejected_and_no_partial_public_asset_survives(self):
        self.source.write_bytes(b'changed since approval')
        with self.assertRaisesRegex(ValueError, 'admitted_identity'):
            self.copy()
        self.assertFalse((self.public / 'media/page/ko.mp3').exists())
        self.assertFalse(list(self.public.rglob('.asset-*')))

    def test_copy_or_sync_failure_cleans_staging_without_publishing(self):
        for operation in ('read', 'fsync'):
            with self.subTest(operation=operation), patch.object(assets.os, operation, side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    self.copy()
            self.assertFalse((self.public / 'media/page/ko.mp3').exists())
            self.assertFalse(list(self.public.rglob('.asset-*')))

    def test_destination_collision_does_not_overwrite_other_bytes(self):
        link = assets.os.link
        def collide(source, destination, **kwargs):
            destination.write_bytes(b'other transaction')
            return link(source, destination, **kwargs)
        with patch.object(assets.os, 'link', side_effect=collide):
            with self.assertRaises(FileExistsError):
                self.copy()
        self.assertEqual((self.public / 'media/page/ko.mp3').read_bytes(), b'other transaction')
        self.assertFalse(list(self.public.rglob('.asset-*')))

    def test_bad_hash_or_public_paths_never_copy(self):
        for path in ('../x', '/media/../x', '//host/x', '/media/./x', '/x?query', '/x#fragment', '/x/'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.copy(path=path)
        with self.assertRaises(ValueError):
            self.copy(sha='not-a-hash')
        self.assertFalse(self.public.exists())

    def test_symlink_sources_and_destination_directories_are_rejected(self):
        linked = self.root / 'linked'
        linked.symlink_to(self.source)
        with self.assertRaises(OSError):
            self.copy(source=linked)
        self.public = self.root / "other-public"
        self.public.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.public / 'media').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.copy()
        self.assertEqual(list(outside.iterdir()), [])
