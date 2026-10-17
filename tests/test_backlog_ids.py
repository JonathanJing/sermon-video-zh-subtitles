import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from scripts import backlog_ids as subject
from tools.development import backlog_ids as implementation

SAMPLE = """# Backlog

## 2026-10-10：状态刷新

| 归属 | 状态 | 下一步 |
|---|---|---|
| `DEV-L4-001/005`、`DEV-CICD-001` | `in_progress` | 部署验收 |
| `DEV-R242-011` | P1 / `pending` | 新的首拒绝停止语义 |

## 2026-10-04：剩余工作

### 子节不改变所属小节

| 子任务 | 状态 | 验收 |
|---|---|---|
| `DEV-R242-011` L2 正式入口 | `in_progress` | 三语 138 组 |
| `DEV-R242-012` L1/L3 adapter | `in_progress` | 稳定恢复 |

文本里提到 `DEV-R242-099` 但不在表格行首，不算定义。
"""


class BacklogIdTests(unittest.TestCase):
    def test_legacy_import_resolves_to_tool_module(self):
        self.assertIs(subject, implementation)

    def test_combined_ids_expand_and_rows_are_ordered_newest_section_first(self):
        found = subject.lookup("DEV-L4-005", SAMPLE)
        self.assertEqual([(row[0], row[1]) for row in found], [("DEV-L4-005", "2026-10-10：状态刷新")])
        self.assertEqual([row[0] for row in subject.lookup("DEV-L4", SAMPLE)], ["DEV-L4-001", "DEV-L4-005"])
        both = subject.lookup("DEV-R242-011", SAMPLE)
        self.assertEqual([row[1] for row in both], ["2026-10-10：状态刷新", "2026-10-04：剩余工作"])
        self.assertLess(both[0][2], both[1][2])
        self.assertEqual(both[0][3], "P1 / `pending`")

    def test_only_table_rows_define_an_id_and_prefix_lookup_is_exact(self):
        self.assertEqual(subject.lookup("DEV-R242-099", SAMPLE), [])
        self.assertEqual({row[0] for row in subject.lookup("DEV-R242", SAMPLE)}, {"DEV-R242-011", "DEV-R242-012"})
        self.assertEqual(subject.lookup("DEV-L", SAMPLE), [])  # a prefix is a whole family name, not a string prefix
        with self.assertRaises(ValueError):
            subject.lookup("R242-011", SAMPLE)

    def test_prefix_summary_counts_rows_and_sections(self):
        summary = subject.prefixes(SAMPLE)
        self.assertEqual(summary["DEV-R242"]["rows"], 3)
        self.assertEqual(len(summary["DEV-R242"]["ids"]), 2)
        self.assertEqual(summary["DEV-R242"]["sections"], ["2026-10-10：状态刷新", "2026-10-04：剩余工作"])
        self.assertEqual(summary["DEV-CICD"]["rows"], 1)

    def test_real_backlog_resolves_known_ids_and_cli_exit_codes(self):
        self.assertTrue(subject.lookup("DEV-GOV-001"))
        self.assertGreater(len(subject.lookup("DEV-R242")), 20)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(subject.main(["DEV-GOV-001"]), 0)
        self.assertIn("DEV-GOV-001", out.getvalue())
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(subject.main(["--prefixes"]), 0)
        self.assertIn("DEV-R242", out.getvalue())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(subject.main(["DEV-NOPE-001"]), 1)


if __name__ == "__main__":
    unittest.main()
