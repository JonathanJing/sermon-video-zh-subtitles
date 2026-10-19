import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.development import worktree_venv as subject


def _package(src: Path, label: str) -> None:
    package = src / 'tongxing_production'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text(f'LABEL = {label!r}\n', encoding='utf-8')


class WorktreeVenvTests(unittest.TestCase):
    def test_isolated_child_imports_worktree_package_not_shared_editable_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _package(root / 'main' / subject.PACKAGE_SRC, 'main')
            worktree = root / 'worktree'
            _package(worktree / subject.PACKAGE_SRC, 'worktree')
            shared = root / 'main' / '.venv'
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(shared)], check=True)
            shared_site = subject.site_packages(shared / 'bin' / 'python')
            (shared_site / '__editable__.tongxing_production-0.1.0.pth').write_text(
                f'{root / "main" / subject.PACKAGE_SRC}\n', encoding='utf-8')
            (shared_site / 'shared_dep.py').write_text('VALUE = 1\n', encoding='utf-8')

            python = subject.build(worktree, shared)
            again = subject.build(worktree, shared)

            self.assertEqual(python, again)
            out = subprocess.run(
                [str(python), '-I', '-c', 'import tongxing_production, shared_dep; print(tongxing_production.LABEL)'],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            self.assertEqual(out, 'worktree')

    def test_refuses_to_replace_a_venv_it_did_not_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp).resolve()
            (worktree / '.venv').mkdir()
            with self.assertRaises(SystemExit):
                subject.build(worktree, Path(sys.executable).parents[1])


if __name__ == '__main__':
    unittest.main()
