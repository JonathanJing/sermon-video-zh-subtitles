"""Source-meaning adjudication: only heard wordings, bound audio, no human approval.

Units are synthetic sentences shaped like the 605 sample around its doubted
unit. Audio is a generated WAV; listeners and the adjudicator are fakes that
record what they were given, so these tests prove the plumbing and the
invariants, not any model's hearing.
"""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import wave

from scripts import sermon_provider_limits as limits
from scripts import sermon_source_text_review as source_review
from scripts import source_meaning_machine_adjudication as machine

WINDOW_START = 63.32
MEDIA_SECONDS = 20


def units(*rows, start=1.0):
    out, cursor = [], start
    for i, text in enumerate(rows):
        out.append({'sourceUnitId': f'u{i + 1}', 'sourceSentenceId': f'0-s{(i // 2) + 1:03d}', 'referenceChunkId': '0',
                    'english': text, 'start': cursor, 'end': cursor + 1.5})
        cursor += 2.0
    return out


UNITS = units('Right now, your life is crazy.',
              "There's a throne, and someone is on it.",
              "You're filled in the middle of a trial.",
              'Listen, there is a throne in heaven, and someone is seated on it.',
              'The world feels crazy.')
DOUBTED = 'u3'
FROZEN = "You're filled in the middle of a trial."
HEARD_OTHER = "you're failing in the middle of a trial"


def segments():
    """Aligned segments: the doubted unit shares its segment with the unit before it."""
    return [{'id': 0, 'referenceChunkId': '0', 'start': 1.0, 'end': 2.5, 'text': UNITS[0]['english']},
            {'id': 1, 'referenceChunkId': '0', 'start': 3.0, 'end': 6.5,
             'text': UNITS[1]['english'] + ' ' + UNITS[2]['english']},
            {'id': 2, 'referenceChunkId': '0', 'start': 7.0, 'end': 10.5,
             'text': UNITS[3]['english'] + ' ' + UNITS[4]['english']}]


def write_media(path: Path) -> dict:
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(machine.SAMPLE_RATE)
        frames = machine.SAMPLE_RATE * MEDIA_SECONDS
        handle.writeframes(struct.pack(f'<{frames}h', *([0] * frames)))
    data = path.read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'sizeBytes': len(data)}


def source(media: dict):
    return {'source': {'sourceId': 'synthetic', 'media': media,
                       'approvedWindow': {'startSeconds': WINDOW_START, 'endSeconds': WINDOW_START + 12}}}


class FakeListener:
    def __init__(self, name, text):
        self.name = self.model = name
        self.text, self.clips = text, []

    def identity(self):
        return {'backend': 'fake-not-evidence', 'model': self.model}

    def transcribe(self, wav):
        self.clips.append(wav)
        return self.text


class FakeCutter:
    def __init__(self):
        self.calls = []

    def __call__(self, media, start, end):
        self.calls.append((media, start, end))
        return b'RIFF' + struct.pack('<ff', start, end)


def answer(decision, heard_by='frozen', corrected=None, note='Translate literally.', reason='weighed'):
    return {'schemaVersion': machine.RESPONSE_SCHEMA, 'decision': decision, 'heardBy': heard_by,
            'correctedText': corrected, 'meaningNote': note, 'reason': reason}


class FakeAdjudicator(machine.SolAdjudicator):
    """The real payload and cache path, with a scripted provider response."""

    def __init__(self, cache, response):
        self.response, self.payloads = response, []

        def caller(_key, payload):
            self.payloads.append(payload)
            return {'id': 'resp-1', 'model': machine.MODEL, 'choices': [
                {'finish_reason': 'stop', 'message': {'content': json.dumps(self.response)}}]}
        super().__init__(api_key='', cache=cache, caller=caller)


class SourceMeaningAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / 'media.wav'
        self.source = source(write_media(self.media))
        self.anchor = {'sourceUnits': UNITS}
        self.out = self.root / 'out'

    def adjudicate(self, listeners, adjudicator=None, cut=None, unit_ids=(DOUBTED,), media=None):
        return machine.adjudicate(self.source, self.anchor, unit_ids=list(unit_ids), media=media,
                                  listeners=listeners, adjudicator=adjudicator, out_dir=self.out,
                                  cut=cut or FakeCutter())

    def test_listeners_hearing_the_frozen_words_confirm_without_a_model_call(self):
        cutter = FakeCutter()
        heard = [FakeListener('a', "There's a throne, and someone is on it. You're filled in the middle of a trial. "
                                   'Listen, there is a throne in heaven'),
                 FakeListener('b', "someone is on it, you're filled in the middle of a trial, listen there is")]
        receipt = self.adjudicate(heard, cut=cutter)
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['decidedBy'], row['correctedText']),
                         ('transcript_confirmed', 'listeners_agree_with_transcript', None))
        self.assertTrue(all(h['agreesWithFrozen'] for h in row['heard']))
        self.assertEqual(row['heard'][1]['unitWindow'], "you're filled in the middle of a trial,")
        self.assertEqual(row['meaningNote'], machine.CONFIRMED_NOTE)
        self.assertIsNone(row['request'])
        self.assertIs(receipt['humanApproval'], False)
        self.assertEqual(receipt['decidedByRole'], machine.ROLE)
        self.assertEqual(receipt['counts'], {'units': 1, 'transcript_confirmed': 1, 'transcript_corrected': 0,
                                             'undetermined': 0})
        # The clip is the unit with one neighbour each side, on the media clock.
        self.assertEqual(cutter.calls, [(None, WINDOW_START + 3.0, WINDOW_START + 8.5)])
        self.assertEqual(row['clip']['sourceUnitIds'], ['u2', 'u3', 'u4'])
        self.assertEqual((row['clip']['mediaStart'], row['clip']['mediaEnd']), (66.32, 71.82))
        self.assertTrue((self.out / 'clips' / 'u3.wav').is_file())
        self.assertTrue((self.out / 'listeners' / 'u3.b.json').is_file())
        self.assertEqual(receipt['media']['sha256'], self.source['source']['media']['sha256'])

    def test_agreeing_listeners_let_the_model_correct_only_to_what_was_heard(self):
        heard = [FakeListener('openai', "someone is on it. You're failing in the middle of a trial. Listen,"),
                 FakeListener('qwen', "and someone is on it you're failing in the middle of a trial listen there")]
        adjudicator = FakeAdjudicator(self.out / 'cache', answer(
            'transcript_corrected', 'openai', "You're failing in the middle of a trial.",
            note='The speaker says the listener is failing during a trial; translate that literally.'))
        receipt = self.adjudicate(heard, adjudicator)
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['heardBy'], row['correctedText'], row['decidedBy']),
                         ('transcript_corrected', 'openai', "You're failing in the middle of a trial.", 'model'))
        self.assertEqual(row['request']['responseId'], 'resp-1')
        payload = adjudicator.payloads[0]
        self.assertEqual(limits.bounded_payload(payload, limits.DEFAULT_REQUEST_LIMITS), payload)
        question = json.loads(payload['messages'][1]['content'])
        self.assertEqual(question['frozenText'], FROZEN)
        self.assertEqual([c['position'] for c in question['context']], ['before', 'before', 'doubted', 'after', 'after'])
        self.assertEqual(question['listeners'][1]['heardForUnit'], "you're failing in the middle of a trial")
        self.assertFalse(question['listeners'][0]['agreesWithFrozen'])
        self.assertEqual(receipt['adjudicator']['model'], machine.MODEL)
        # The same request is served from the cache, not sent again.
        self.adjudicate(heard, adjudicator)
        self.assertEqual(len(adjudicator.payloads), 1)

    def test_a_wording_nobody_heard_is_refused(self):
        heard = [FakeListener('openai', "You're failing in the middle of a trial.")]
        for response, code in (
                (answer('transcript_corrected', 'openai', "You're fulfilled in the middle of a trial."), 'corrected_text_not_heard'),
                (answer('transcript_corrected', 'frozen', FROZEN), 'corrected_by_frozen_words'),
                (answer('transcript_corrected', 'openai', None), 'corrected_text_missing'),
                (answer('transcript_confirmed', 'frozen', "You're failing in the middle of a trial."), 'corrected_text_without_correction'),
                (answer('transcript_confirmed', 'nobody'), 'answer_heard_by'),
                (answer('maybe'), 'answer_decision'),
                (answer('undetermined', note='x' * (machine.MAX_NOTE_CHARS + 1)), 'answer_note')):
            with self.subTest(code=code):
                shutil.rmtree(self.out, ignore_errors=True)
                with self.assertRaisesRegex(machine.SourceAdjudicationError, code):
                    self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', response))

    def test_disagreeing_listeners_may_end_undetermined_with_the_frozen_text_kept(self):
        heard = [FakeListener('openai', "You're failing in the middle of a trial."),
                 FakeListener('qwen', "You're filled in the middle of a trial.")]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'undetermined', note='Translate the frozen English literally; the listeners disagree.')))
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['correctedText']), ('undetermined', None))
        self.assertEqual([h['agreesWithFrozen'] for h in row['heard']], [False, True])
        self.assertIsNone(machine.source_text_review(receipt, self.anchor, segments(), receipt_path=self.media,
                                                     source_audio=self.media, asr_reference=self.media))

    def test_corrected_unit_becomes_a_layer1_review_the_existing_path_applies(self):
        heard = [FakeListener('openai', "You're failing in the middle of a trial.")]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        receipt_path = self.out / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        clip, asr = self.root / 'clip.m4a', self.root / 'asr_reference.json'
        clip.write_bytes(b'window clip bytes')
        asr.write_text(json.dumps({'segments': segments()}), encoding='utf-8')
        review = machine.source_text_review(receipt, self.anchor, segments(), receipt_path=receipt_path,
                                            source_audio=clip, asr_reference=asr)
        self.assertEqual(review['authority'], source_review.MACHINE_AUTHORITY)
        self.assertEqual(review['model'], machine.MODEL)
        self.assertIs(review['humanApproval'], False)
        self.assertEqual(review['evidence'], [{'path': 'receipt.json',
                                               'sha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest()}])
        self.assertEqual([p['segmentId'] for p in review['patches']], [1])
        self.assertEqual(review['patches'][0]['correctedText'],
                         "There's a throne, and someone is on it. You're failing in the middle of a trial.")
        review_path = self.out / 'source-text-review.json'
        review_path.write_text(json.dumps(review), encoding='utf-8')
        corrected, provenance = source_review.apply_review(segments(), review_path, clip, asr)
        self.assertEqual(corrected[1]['text'], review['patches'][0]['correctedText'])
        self.assertEqual(corrected[0]['text'], segments()[0]['text'])
        self.assertEqual(provenance['authority'], source_review.MACHINE_AUTHORITY)
        self.assertEqual(provenance['reviewedBy'], receipt['decidedBy'])

    def test_review_refuses_a_unit_whose_segment_cannot_be_located(self):
        heard = [FakeListener('openai', "You're failing in the middle of a trial.")]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        rows = segments()
        rows[1]['text'] = rows[1]['text'].replace('filled', 'filled,')
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'segment_not_located'):
            machine.source_text_review(receipt, self.anchor, rows, receipt_path=self.media,
                                       source_audio=self.media, asr_reference=self.media)

    def test_bindings_and_refusals(self):
        heard = [FakeListener('a', FROZEN)]
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'unit_unknown'):
            self.adjudicate(heard, unit_ids=['u9'])
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'unit_ids'):
            self.adjudicate(heard, unit_ids=['u3', 'u3'])
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'listeners_required'):
            self.adjudicate([])
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'adjudicator_required'):
            self.adjudicate([FakeListener('a', HEARD_OTHER)])
        other = self.root / 'other.wav'
        other.write_bytes(self.media.read_bytes() + b'\0')
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'media_identity_mismatch'):
            self.adjudicate(heard, media=other)
        receipt = self.adjudicate(heard, media=self.media)
        self.assertEqual(receipt['bindings']['anchor.json'], machine.policies.canonical_sha256(self.anchor))

    def test_window_matching_ignores_presentation_and_picks_the_closest_stretch(self):
        frozen = machine.tokens(FROZEN)
        self.assertEqual(frozen, ["you're", 'filled', 'in', 'the', 'middle', 'of', 'a', 'trial'])
        window = machine.best_window(frozen, 'Someone is on it. You’re FILLED, in the middle of a trial! Listen.')
        self.assertEqual(window['tokens'], frozen)
        self.assertEqual(window['similarity'], 1.0)
        window = machine.best_window(frozen, "someone is on it you're failing in the middle of a trial listen")
        self.assertEqual(window['text'], "you're failing in the middle of a trial")
        self.assertLess(window['similarity'], 1.0)
        self.assertEqual(machine.best_window(frozen, '')['tokens'], [])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is not installed')
    def test_ffmpeg_cuts_a_pcm16_clip_of_the_requested_length(self):
        wav = machine.cut_clip(self.media, 2.0, 5.5)
        with wave.open(str(self._saved(wav)), 'rb') as handle:
            self.assertEqual((handle.getnchannels(), handle.getsampwidth(), handle.getframerate()),
                             (1, 2, machine.SAMPLE_RATE))
            self.assertAlmostEqual(handle.getnframes() / machine.SAMPLE_RATE, 3.5, places=2)

    def _saved(self, data):
        path = self.root / 'cut.wav'
        path.write_bytes(data)
        return path


if __name__ == '__main__':
    unittest.main()
