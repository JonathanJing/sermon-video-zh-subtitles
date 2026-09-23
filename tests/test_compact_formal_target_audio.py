import json
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from scripts import compact_formal_target_audio as subject
from scripts import sermon_sentence_interpretation as identity
from tests import test_render_formal_target_language_speech as render_tests


class LeadSynth:
    def __init__(self, checkpoint: Path, **kwargs):
        pass

    def __call__(self, text, language, speaker, *, seed):
        return [0.0] * 8000 + [0.15] * 1600, 16000


class CompactAudioTests(unittest.TestCase):
    def test_trims_only_measured_leading_silence_and_preserves_raw_unit(self):
        fixture = render_tests.FormalRenderTests(
            'test_two_units_full_decode_and_resume_without_synthesis')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.root.joinpath('fixture-model').mkdir(exist_ok=True)
        subject.renderer.render_units(fixture.context, fixture.paths, fixture.root,
                                      fixture.root / 'checkpoint-map.json',
                                      synth_factory=LeadSynth)
        source_job = fixture.paths['job']
        raw = fixture.root / fixture.context['job']['units'][0]['outputRelativePath']
        raw_hash = identity.sha256(raw)
        destination = fixture.root.parent / 'compacted'
        destination.mkdir()
        destination_job = destination / 'job.json'
        shutil.copy2(source_job, destination_job)
        result = subject.compact_unit(source_job, destination_job, 0,
                                      expected_job_hash=identity.json_sha256(fixture.context['job']))
        output = destination / fixture.context['job']['units'][0]['outputRelativePath']
        self.assertEqual(identity.sha256(raw), raw_hash)
        self.assertNotEqual(identity.sha256(output), raw_hash)
        self.assertGreaterEqual(result['removedLeadingSeconds'], 0.4)
        self.assertEqual(result['sourceAudioSha256'], raw_hash)
        self.assertLess(result['durationSeconds'], result['originalDurationSeconds'])
        self.assertEqual(subject.compact_unit(source_job, destination_job, 0,
                                              expected_job_hash=identity.json_sha256(fixture.context['job'])),
                         result)


if __name__ == '__main__':
    unittest.main()
