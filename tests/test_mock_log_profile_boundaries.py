import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import profile_mock_dag_logs as subject


class ProfileBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.saved = self.root/'evidence'/'happy'/'plan'
        self.saved.mkdir(parents=True)
        self.input = self.saved/'input.json'
        self.input.write_text('{}')

    def test_output_in_sibling_scenario_is_rejected(self):
        output = self.root/'evidence'/'failure'/'profile.pstats'
        with self.assertRaisesRegex(ValueError, 'inside_evidence'):
            subject.profile_evidence_root(self.saved, output)
        self.assertFalse(output.exists())

    def test_existing_output_and_symlink_are_preserved(self):
        output = self.root/'already.pstats'
        output.write_bytes(b'existing')
        with self.assertRaisesRegex(ValueError, 'already_exists'):
            subject.profile_evidence_root(self.saved, output)
        link = self.root/'link.pstats'; link.symlink_to(output)
        with self.assertRaisesRegex(ValueError, 'already_exists'):
            subject.profile_evidence_root(self.saved, link)
        self.assertEqual(output.read_bytes(), b'existing')

    def test_profile_checks_input_bytes_after_child(self):
        def mutate(*args):
            self.input.write_text('{"changed":true}')
            return {}
        with patch.object(subject, 'child', side_effect=mutate), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'evidence_changed_during_profile'):
                subject.main(['--child', '--saved', str(self.saved), '--operation', 'file_bytes',
                    '--profile-output', str(self.root/'fresh.pstats')])

    def test_safe_external_output_retains_inputs(self):
        output = self.root/'fresh.pstats'
        with patch.object(subject, 'child', return_value={'status': 'tested'}) as child, contextlib.redirect_stdout(io.StringIO()):
            subject.main(['--child', '--saved', str(self.saved), '--operation', 'file_bytes',
                '--profile-output', str(output)])
        child.assert_called_once()
        self.assertEqual(self.input.read_text(), '{}')


if __name__ == '__main__':
    unittest.main()
