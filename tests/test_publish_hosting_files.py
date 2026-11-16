import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.ops.publish_hosting_files as PUBLISH
from tongxing_production.delivery import hosting_incremental


class PublishHostingFilesPlanTests(unittest.TestCase):
    """Only the changed files may enter the clone; everything else stays live."""

    def test_plan_lists_only_files_whose_bytes_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            (public / "multilingual-v3.json").write_text('{"pages": []}\n')
            (public / "unchanged.json").write_text("{}\n")
            digests = {"/multilingual-v3.json": hosting_incremental.digest(public / "multilingual-v3.json"),
                       "/unchanged.json": hosting_incremental.digest(public / "unchanged.json")}
            remote = {"/multilingual-v3.json": "0" * 64, "/unchanged.json": digests["/unchanged.json"],
                      "/pages/other/index.html": "1" * 64}
            with mock.patch.object(PUBLISH.hosting_incremental, "remote_files", return_value=remote):
                plan = PUBLISH.build_plan(object(), site="example-site", public=public,
                                          baseline="sites/example-site/versions/abc")
            self.assertEqual(plan["changed"], ["/multilingual-v3.json"])
            self.assertEqual(plan["baselineVersion"], "sites/example-site/versions/abc")
            self.assertEqual(plan["localFiles"], 2)
            self.assertEqual(plan["remoteFiles"], 3)
            self.assertEqual(plan["digests"]["/multilingual-v3.json"], digests["/multilingual-v3.json"])

    def test_identical_snapshot_has_nothing_to_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            (public / "multilingual-v3.json").write_text("{}\n")
            remote = {"/multilingual-v3.json": hosting_incremental.digest(public / "multilingual-v3.json")}
            with mock.patch.object(PUBLISH.hosting_incremental, "remote_files", return_value=remote):
                plan = PUBLISH.build_plan(object(), site="example-site", public=public,
                                          baseline="sites/example-site/versions/abc")
            self.assertEqual(plan["changed"], [])

    def test_the_clone_never_drops_live_files(self):
        """The plan keeps every live path; deploy clones, so removal cannot happen."""
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            (public / "multilingual-v3.json").write_text('{"pages": []}\n')
            remote = {"/multilingual-v3.json": "0" * 64, "/pages/a/index.html": "1" * 64}
            with mock.patch.object(PUBLISH.hosting_incremental, "remote_files", return_value=remote):
                plan = PUBLISH.build_plan(object(), site="example-site", public=public,
                                          baseline="sites/example-site/versions/abc")
        self.assertEqual(set(plan["digests"]), {"/multilingual-v3.json"})
        self.assertEqual(plan["remoteFiles"], 2)


if __name__ == "__main__":
    unittest.main()
