"""The staged feedback API source must carry every module the runtime imports."""
import re
import unittest

import deploy_feedback as deploy

IMPORT = re.compile(r"""from\s+['"]\./([^'"]+)['"]""")


class RuntimeFilesTests(unittest.TestCase):
    def test_every_relative_import_is_staged(self):
        pending, seen = ["index.mjs"], set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            pending.extend(IMPORT.findall((deploy.SOURCE / name).read_text(encoding="utf-8")))
        self.assertIn("listening-core.mjs", seen)
        self.assertIn("alignment-core.mjs", seen)
        self.assertLessEqual(seen, set(deploy.RUNTIME_FILES))


if __name__ == "__main__":
    unittest.main()
