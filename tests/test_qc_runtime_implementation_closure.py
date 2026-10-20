import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.review import seeded_errors as seeded
from tongxing_production.review import waiver
from tests import auto_qc_fixtures as fixtures


class QcRuntimeClosureTests(unittest.TestCase):
    def test_routing_only_change_invalidates_previously_passing_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in waiver.IMPLEMENTATION_PHYSICAL_FILES:
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(__file__).resolve().parents[1] / name, destination)
            original = waiver.implementation_sha256(root)
            calibration = seeded.calibrate('ko', fixtures.groups('ko'),
                policy=fixtures.policy('ko'), call=fixtures.PerfectSemanticJudge('ko'),
                identity=fixtures.SEMANTIC_IDENTITY)
            self.assertEqual(calibration['implementationSha256'], original)
            self.assertEqual(waiver.calibration_problems(calibration, 'ko', original), [])
            runtime = waiver.implementation_path('scripts/sermon_openai_runtime.py', root)
            runtime.write_text(runtime.read_text().replace("'OpenAI-Project': route['projectId']",
                "'OpenAI-Project': 'proj_other'"))
            changed = waiver.implementation_sha256(root)
            self.assertNotEqual(original, changed)
            self.assertIn('QC implementation changed since calibration',
                waiver.calibration_problems(calibration, 'ko', changed))
