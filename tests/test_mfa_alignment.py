import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from scripts import mfa_alignment as mfa


class AlignmentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clip = self.root / 'audio.wav'
        self.clip.write_bytes(b'frozen audio')
        self.exe = self.root / 'mfa'
        self.exe.write_text('mfa stub')
        self.dictionary = self.root / 'english.dict'
        self.dictionary.write_text("no N OW\nbut B AH T\ni AY\ncan't K AE N T\nseventy S\nthree TH\n")
        self.acoustic = self.root / 'acoustic.zip'
        self.acoustic.write_bytes(b'model')
        self.chunks = [{'id': 2, 'start': 5., 'end': 8., 'text': 'No. But I can’t 73.'}]
        self.calls = []
        self.corrupt = None

    def fake_run(self, command, **kwargs):
        command = [str(v) for v in command]
        self.calls.append(command)
        if command[1] == 'version':
            return subprocess.CompletedProcess(command, 0, stdout='3.4.2\n')
        if command[0] == 'ffmpeg':
            with wave.open(command[-1], 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b'\0\0' * int(float(command[command.index('-t') + 1]) * 16000))
        elif command[1] == 'align':
            out = Path(command[5]) / 'speaker'
            out.mkdir(parents=True, exist_ok=True)
            for lab in Path(command[2]).rglob('*.lab'):
                words = lab.read_text().split()
                entries = [[i * .4 + .1, i * .4 + .35, w] for i, w in enumerate(words)]
                if self.corrupt == 'missing':
                    entries.pop()
                if self.corrupt == 'wrong':
                    entries[0][2] = 'yes'
                phones = [[s, e, 'AH'] for s, e, _ in entries]
                if self.corrupt == 'unknown':
                    phones[0][2] = 'spn'
                raw = {'tiers': {'words': {'entries': entries}, 'phones': {'entries': phones}}}
                (out / (lab.stem + '.json')).write_text(json.dumps(raw))
        elif command[1] == 'g2p':
            Path(command[4]).write_text(''.join(w + ' AH\n' for w in Path(command[2]).read_text().split()))
        return subprocess.CompletedProcess(command, 0)

    def align(self):
        return mfa.align_reference_chunks(self.chunks, self.clip, self.root / 'out',
                                         mfa_executable=self.exe, dictionary_path=self.dictionary,
                                         acoustic_model=self.acoustic)

    def test_preserves_text_maps_numbers_contractions_and_uses_audio_times(self):
        with patch.object(mfa.subprocess, 'run', side_effect=self.fake_run):
            result = self.align()
        self.assertEqual([s['text'] for s in result], ['No.', 'But I can’t 73.'])
        self.assertAlmostEqual(result[0]['start'], 5.1)
        self.assertAlmostEqual(result[0]['end'], 5.35)
        number = result[1]['wordTimes'][-1]
        self.assertEqual(number['text'], '73.')
        self.assertEqual(number['spokenForms'], ['seventy', 'three'])
        self.assertEqual(len(number['phones']), 2)
        self.assertGreater(number['start'], result[0]['end'])
        self.assertEqual(result[0]['timingQuality'], 'mfa_word_aligned')

    def test_rejects_missing_changed_and_unknown_alignment(self):
        for corruption in ('missing', 'wrong', 'unknown'):
            with self.subTest(corruption=corruption):
                self.corrupt = corruption
                with patch.object(mfa.subprocess, 'run', side_effect=self.fake_run):
                    with self.assertRaises(ValueError):
                        self.align()

    def test_cache_requires_identity_and_unmodified_raw_output(self):
        with patch.object(mfa.subprocess, 'run', side_effect=self.fake_run):
            first = self.align()
            self.align()
            self.assertEqual(sum(c[1] == 'align' for c in self.calls), 1)
            self.acoustic.write_bytes(b'different model')
            self.align()
            self.assertEqual(sum(c[1] == 'align' for c in self.calls), 2)
            manifest = Path(first[0]['mfaManifest'])
            raw = manifest.parent / 'aligned/speaker/chunk_0000.json'
            raw.write_text('{}')
            self.acoustic.write_bytes(b'model')
            with self.assertRaisesRegex(ValueError, 'missing or changed'):
                self.align()

    def test_changed_reference_cannot_reuse_previous_alignment(self):
        with patch.object(mfa.subprocess, 'run', side_effect=self.fake_run):
            self.align()
            self.chunks[0]['text'] = 'But no.'
            result = self.align()
        self.assertEqual(sum(c[1] == 'align' for c in self.calls), 2)
        self.assertEqual(result[0]['text'], 'But no.')

    def test_oov_requires_g2p_and_expansion_is_local(self):
        self.chunks[0]['text'] = 'Embittered.'
        with patch.object(mfa.subprocess, 'run', side_effect=self.fake_run):
            with self.assertRaisesRegex(ValueError, 'missing words'):
                self.align()
            g2p = self.root / 'g2p.zip'
            g2p.write_bytes(b'g2p model')
            result = mfa.align_reference_chunks(self.chunks, self.clip, self.root / 'out',
                                               mfa_executable=self.exe, dictionary_path=self.dictionary,
                                               acoustic_model=self.acoustic, g2p_model=g2p)
        self.assertEqual(result[0]['text'], 'Embittered.')
        self.assertNotIn('embittered', self.dictionary.read_text())
        self.assertFalse(any('download' in c for c in self.calls))

    def test_ambiguous_number_fails_before_alignment(self):
        for text in ('1.5 years.', '2nd chapter.', '$20.', '01 is odd.'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                mfa._reference(text)

    def test_empty_reference_chunk_is_recorded_but_not_aligned(self):
        self.chunks.insert(0, {'id': 1, 'start': 0., 'end': 5., 'text': ''})
        with patch.object(mfa.subprocess, 'run', side_effect=self.fake_run):
            result = self.align()
        manifest = json.loads(Path(result[0]['mfaManifest']).read_text())
        self.assertEqual(manifest['identity']['skippedEmptyReferenceChunks'][0]['id'], 1)
        self.assertEqual(len(manifest['identity']['chunks']), 1)
        self.assertEqual(len(result), 2)

    def test_explicit_spoken_form_preserves_script_and_binds_cache(self):
        self.chunks[0]['text'] = '73:16.'
        self.dictionary.write_text(self.dictionary.read_text() + 'sixteen S\n')
        forms = self.root / 'spoken.json'
        forms.write_text(json.dumps({'73:16.': ['seventy', 'three', 'sixteen']}))
        kwargs = dict(mfa_executable=self.exe, dictionary_path=self.dictionary,
                      acoustic_model=self.acoustic, spoken_forms_path=forms)
        with patch.object(mfa.subprocess, 'run', side_effect=self.fake_run):
            first = mfa.align_reference_chunks(self.chunks, self.clip, self.root / 'out', **kwargs)
            self.assertEqual(first[0]['text'], '73:16.')
            word = first[0]['wordTimes'][0]
            self.assertEqual((word['charStart'], word['charEnd']), (0, 6))
            self.assertEqual(word['spokenForms'], ['seventy', 'three', 'sixteen'])
            forms.write_text(json.dumps({'73:16.': ['seventy', 'three']}))
            second = mfa.align_reference_chunks(self.chunks, self.clip, self.root / 'out', **kwargs)
        self.assertNotEqual(first[0]['mfaManifest'], second[0]['mfaManifest'])
        with self.assertRaises(ValueError):
            mfa._reference('73:16.', {'73:17.': ['three']})
        self.exe.chmod(0o755)
        with patch.object(mfa.shutil, 'which', return_value=str(self.exe)):
            checked = mfa.preflight(self.exe, self.dictionary, self.acoustic, spoken_forms_path=forms)
        self.assertEqual(checked['spoken_forms_sha256'], mfa._sha(forms))

    def test_preflight_rejects_missing_ffmpeg(self):
        self.exe.chmod(0o755)
        with patch.object(mfa.shutil, 'which', side_effect=lambda name: None if name == 'ffmpeg' else str(self.exe)):
            with self.assertRaisesRegex(ValueError, 'ffmpeg is required'):
                mfa.preflight(self.exe, self.dictionary, self.acoustic)

    def test_titles_and_name_initials_preserve_sentence_units(self):
        for title in ('Dr.', 'Mr.', 'Mrs.', 'Ms.', 'St.', 'Rev.', 'Prof.', 'Jr.', 'Sr.', 'J.'):
            text, spoken, mapping = mfa._reference(title + ' Smith spoke. We listened.')
            entries = [[i * .3 + .01, i * .3 + .2, word] for i, word in enumerate(spoken)]
            raw = {'tiers': {'words': {'entries': entries},
                             'phones': {'entries': [[a, b, 'AH'] for a, b, _ in entries]}}}
            with self.subTest(title=title):
                result = mfa._segments(raw, {'id': 0, 'start': 0, 'end': 3}, text, spoken, mapping)
                self.assertEqual([s['text'] for s in result],
                                 [title + ' Smith spoke.', 'We listened.'])
                self.assertEqual(len(result[0]['wordTimes']), 3)

    def test_spoken_forms_schema_rejects_empty_or_nonword_expansions(self):
        forms = self.root / 'spoken.json'
        for value in ([], {'73:16': []}, {'73:16': ['73']}, {'two tokens': ['two']}):
            forms.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                mfa._spoken_forms(forms)

    def test_bad_timing_fails(self):
        for bad in (float('nan'), -1, 100, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mfa._entries({'tiers': {'words': {'entries': [[bad, 1, 'no']]}}}, 'words', 3)


if __name__ == '__main__':
    unittest.main()
