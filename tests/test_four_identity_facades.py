"""A changed package target or alias mapping invalidates each bound identity; removed facades are not hashed."""
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import tongxing_host as host  # noqa: F401  configures package ports
from tongxing_production.compute import qc_audio_transports as transport
from tongxing_production.review import waiver
from tongxing_production.audio import screening
from tongxing_production.audio import predicted_schedule as predicted
from tongxing_production import path_aliases


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = path_aliases.PRODUCTION + "path_aliases.py"


class FourIdentityFacadeTests(unittest.TestCase):
    def test_each_physical_target_and_resolver_changes_its_identity(self):
        cases = (
            ("waiver", waiver.implementation_sha256, waiver.IMPLEMENTATION_PHYSICAL_FILES,
             "scripts/machine_quality_waiver.py", path_aliases.resolve("scripts/machine_quality_waiver.py")),
            ("transport", transport.implementation_sha256, transport.TRANSPORT_PHYSICAL_FILES,
             "scripts/machine_qc_audio_transports.py", path_aliases.resolve("scripts/machine_qc_audio_transports.py")),
            ("scoring", screening.implementation_sha256, screening.SCORING_PHYSICAL_FILES,
             "scripts/screen_target_language_audio_units.py", path_aliases.resolve("scripts/screen_target_language_audio_units.py")),
            ("rate", predicted.rate_implementation_sha256, predicted.RATE_PHYSICAL_FILES,
             "scripts/target_audio_predicted_schedule.py", path_aliases.resolve("scripts/target_audio_predicted_schedule.py")),
        )
        original_open = Path.open
        for label, identity, physical, facade, target in cases:
            self.assertEqual(tuple(sorted(set(physical))), physical)
            baseline = identity()
            # The D closure window removed the scripts/ facades: the closure names the target only.
            self.assertNotIn(facade, physical)
            self.assertFalse((ROOT / facade).exists())
            for name in (target, RESOLVER):
                with self.subTest(identity=label, name=name):
                    self.assertIn(name, physical)
                    path_to_change = ROOT / name

                    def changed_open(path, *args, **kwargs):
                        mode = args[0] if args else kwargs.get("mode", "r")
                        if path == path_to_change and mode == "rb":
                            with original_open(path, "rb") as stream:
                                return io.BytesIO(stream.read() + b"\n# independent byte change\n")
                        return original_open(path, *args, **kwargs)

                    with patch.object(Path, "open", changed_open):
                        self.assertNotEqual(identity(), baseline)
            self.assertEqual(identity(), baseline)


if __name__ == "__main__":
    unittest.main()
