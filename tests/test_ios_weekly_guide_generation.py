"""The bundled weekly guide is locally generated; fixtures contain no source text."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'apps/tongxing-ios/scripts/prepare-weekly-guide.py'
spec = importlib.util.spec_from_file_location('prepare_weekly_guide', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WeeklyGuideGenerationTests(unittest.TestCase):
    def test_legacy_cli_requires_output_and_rejects_active_bundle(self):
        base = [sys.executable, str(SCRIPT), '--source', '/nonexistent/source', '--cuv', '/nonexistent/cuv']
        missing = subprocess.run(base, capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('--output', missing.stderr)
        active = SCRIPT.parent.parent / 'GuideResources'
        rejected = subprocess.run(base + ['--output', str(active)], capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('output must be a fresh path within ignored artifacts', rejected.stderr)

    def test_legacy_v1_can_be_reproduced_only_in_new_ignored_directory(self):
        artifacts = SCRIPT.parents[3] / 'artifacts'
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as directory:
            root = Path(directory); source=root/'source.md'; cuv=root/'cuv.json'; out=root/'result'
            source.write_text('synthetic source'); cuv.write_text('{}')
            args=['prepare-weekly-guide.py','--source',str(source),'--cuv',str(cuv),'--output',str(out)]
            with mock.patch.object(sys,'argv',args), mock.patch.object(module,'WEEKS',[]), \
                 mock.patch.object(module,'SOURCE_SHA256',hashlib.sha256(source.read_bytes()).hexdigest()), \
                 mock.patch.object(module,'CUV_SHA256',hashlib.sha256(cuv.read_bytes()).hexdigest()):
                module.main()
                payload=(out/'weekly-guides.json').read_bytes()
                self.assertEqual(json.loads(payload),{'guides':[]})
                self.assertEqual((out/'weekly-guides.sha256').read_text().strip(),hashlib.sha256(payload).hexdigest())
                with self.assertRaisesRegex(ValueError,'new directory'):
                    module.main()

    def test_build_pin_matches_app_and_rejects_self_consistent_other_payload(self):
        app = SCRIPT.parent.parent
        yml = (app/'project.yml').read_text()
        match = re.search(r'(?s)      - name: Copy local weekly guides\n.*?        script: \|\n(.*?)(?=    settings:)',yml)
        self.assertIsNotNone(match)
        script = textwrap.dedent(match.group(1))
        build_pin = re.search(r'if \[ "\$actual" != "([0-9a-f]{64})" \]; then',script)
        swift_pin = re.search(r'acceptedBundleSHA = "([0-9a-f]{64})"',(app/'App/WeeklyGuideData.swift').read_text())
        self.assertIsNotNone(build_pin);self.assertIsNotNone(swift_pin)
        self.assertEqual(build_pin.group(1),swift_pin.group(1))
        self.assertNotEqual(build_pin.group(1),'99b494d5c52104df38e5a4be1a563b2905edd9cbe612209188ae2ea87ed860f2')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); resources=root/'GuideResources';resources.mkdir()
            payload=b'{"guides":[]}'
            (resources/'weekly-guides.json').write_bytes(payload)
            (resources/'weekly-guides.sha256').write_text(hashlib.sha256(payload).hexdigest()+'\n')
            for configuration in ('Release','BetaDebug','BetaRelease'):
                env={**os.environ,'SRCROOT':str(root),'TARGET_BUILD_DIR':str(root/'build'),
                     'UNLOCALIZED_RESOURCES_FOLDER_PATH':'resources','CONFIGURATION':configuration}
                run=subprocess.run(['/bin/sh','-c',script],env=env,capture_output=True,text=True)
                self.assertNotEqual(run.returncode,0)
                self.assertIn('not the revision accepted by this App',run.stdout)

    def test_table_cells_keep_headers_order_and_surrounding_text(self):
        source = ('Before\n\n| | Meaning | Reference |\n|---|---|---|\n'
                  '| Item A | First | Book 1 |\n| Item B | Second |  |\n\nAfter')
        result = module.readable_tables(source)
        self.assertEqual(result, 'Before\n\nItem A\nMeaning：First\nReference：Book 1\n\n'
                         'Item B\nMeaning：Second\nReference：\n\nAfter')
        self.assertNotIn('|---|', result)

    def test_multiple_tables_and_literal_pipe_do_not_change_other_lines(self):
        source = ('| Name | Meaning |\n|:---|---:|\n| A | left \\| right |\n\n'
                  'Normal line\n\n| Name | Meaning |\n|---|---|\n| B | value |')
        result = module.readable_tables(source)
        self.assertEqual(result, 'Name：A\nMeaning：left | right\n\nNormal line\n\n'
                         'Name：B\nMeaning：value')
        self.assertEqual(module.readable_tables('Some | prose\n\nAnother line'),
                         'Some | prose\n\nAnother line')

    def test_week_pages_and_appendix_remain_in_order_for_exact_aliases(self):
        source = ('## PAGE 1（印刷页 10，id a）\n\nfirst sample\n\n'
                  '## PAGE 2（印刷页 11，id b）\n\nsecond sample\n\n'
                  '## PAGE 5（印刷页 14，id c）\n\nappendix sample\n')
        week = {'ids': ['page-a', 'page-b'], 'week': 1, 'title': 'Sample',
                'scripture': 'Example', 'first_page': 1, 'last_page': 2, 'appendix_page': 5,
                'scripture_first_page': 2, 'scripture_start': '1:1', 'scripture_end': '1:2'}
        cuv = {'1:1': 'Verse one', '1:2': 'Verse two', '2:1': 'Other'}
        guides = module.build_guides(source, [week], cuv)['guides']
        self.assertEqual([guide['id'] for guide in guides], ['page-a', 'page-b'])
        self.assertEqual([section['body'] for section in guides[0]['sections']],
                         ['first sample', '1:1 Verse one\n\n1:2 Verse two', 'second sample', 'appendix sample'])
        self.assertIn('并非手册原刊', guides[0]['sections'][1]['subtitle'])
        self.assertTrue(guides[0]['sections'][-1]['title'].startswith('附录'))

    def test_missing_or_duplicated_page_is_rejected(self):
        week = {'ids': ['page'], 'week': 1, 'title': 'Sample', 'scripture': 'Example',
                'first_page': 1, 'last_page': 1, 'appendix_page': 2,
                'scripture_first_page': 1, 'scripture_start': '1:1', 'scripture_end': '1:1'}
        with self.assertRaisesRegex(ValueError, 'missing or empty page'):
            module.build_guides('## PAGE 1（印刷页 1，id a）\n\nsample', [week], {'1:1': 'Sample'})
        with self.assertRaisesRegex(ValueError, 'duplicate page'):
            module.build_guides('## PAGE 1（印刷页 1，id a）\n\na\n## PAGE 1（印刷页 1，id b）\n\nb', [week], {'1:1': 'Sample'})
        with self.assertRaisesRegex(ValueError, 'missing scripture boundary'):
            module.build_guides('## PAGE 1（印刷页 1，id a）\n\nsample', [week], {})


if __name__ == '__main__':
    unittest.main()
