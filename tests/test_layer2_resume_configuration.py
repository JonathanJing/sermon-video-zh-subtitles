"""Cross-run resume is a configuration binding, not an implicit cache reuse."""
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.text import auto_repair
from tongxing_production.text import controller as subject
from tests import test_canonical_layer2_controller as fixtures


class Layer2ResumeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CanonicalLayer2ControllerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.prior = self.fixture.root / 'prior-run'
        self.prior.mkdir()

    def load(self):
        return subject.load_configuration(self.fixture.path)

    def test_prior_root_is_bound_into_the_configuration(self):
        self.fixture.config_data['layer2Resume'] = {'priorRunRoot': 'prior-run'}
        self.fixture.save_config()
        config = self.load()
        self.assertEqual(config.resume['priorRunRoot'], self.prior.resolve())

    def test_missing_prior_root_is_refused_before_dispatch(self):
        self.fixture.config_data['layer2Resume'] = {'priorRunRoot': 'missing-run'}
        self.fixture.save_config()
        with self.assertRaisesRegex(ValueError, 'invalid_layer2_resume'):
            self.load()

    def test_resume_shape_must_be_exactly_one_prior_root(self):
        for value in ({}, {'priorRunRoot': 'prior-run', 'extra': 'x'}, {'root': 'prior-run'}):
            with self.subTest(value=value):
                self.fixture.config_data['layer2Resume'] = value
                self.fixture.save_config()
                with self.assertRaisesRegex(ValueError, 'invalid_layer2_resume'):
                    self.load()

    def test_auto_repair_execution_accepts_a_resume_root(self):
        self.fixture.config_data.update(
            schemaVersion=subject.AUTO_REPAIR_SCHEMA,
            layer2AutoRepair={'routingVersion': auto_repair.ROUTING_VERSION,
                              'groupWorkers': 2, 'maxActiveLocales': 1},
            layer2Resume={'priorRunRoot': 'prior-run'})
        self.fixture.save_config()
        config = self.load()
        self.assertEqual(config.resume['priorRunRoot'], self.prior.resolve())

    def test_resume_cannot_be_combined_with_payload_cache(self):
        self.fixture.config_data['layer2Resume'] = {'priorRunRoot': 'prior-run'}
        self.fixture.config_data['layer2PayloadCache'] = {}
        self.fixture.save_config()
        with self.assertRaises(ValueError):
            self.load()


if __name__ == '__main__':
    unittest.main()
