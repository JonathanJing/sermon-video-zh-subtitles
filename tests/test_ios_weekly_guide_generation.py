"""The bundled weekly guide is locally generated; fixtures contain no source text."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'apps/tongxing-ios/scripts/prepare-weekly-guide.py'
spec = importlib.util.spec_from_file_location('prepare_weekly_guide', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WeeklyGuideGenerationTests(unittest.TestCase):
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
