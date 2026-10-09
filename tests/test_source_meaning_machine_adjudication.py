"""Source-meaning adjudication: only heard wordings, bound audio, no human approval.

Units are synthetic sentences shaped like the 605 sample around its doubted
unit. Audio is a generated WAV; listeners and the adjudicator are fakes that
record what they were given, so these tests prove the plumbing and the
invariants, not any model's hearing.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest import mock
import wave

from scripts import sermon_provider_limits as limits
from scripts import sermon_source_text_review as source_review
from scripts import source_meaning_machine_adjudication as machine
from scripts import target_language_policy as policies

WINDOW_START = 63.32
MEDIA_SECONDS = 20
TRANSCRIPT_SHA = 'e' * 64


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
# A listener transcribes the whole clip (u2, u3, u4); these are its outputs for one clip.
CLIP_HEARD = ("There's a throne, and someone is on it. You're filled in the middle of a trial. "
              'Listen, there is a throne in heaven, and someone is seated on it.')
CLIP_HEARD_OTHER = ("there's a throne and someone is on it you're failing in the middle of a trial "
                    'listen there is a throne in heaven and someone is seated on it')


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


def anchor_for(rows):
    return {'sourceUnits': rows, 'input': {'mfaSegmentsSha256': TRANSCRIPT_SHA}}


def source(media: dict, anchor: dict):
    """An English Source Package naming its media, window, transcript and the anchor built on it."""
    return {'source': {'sourceId': 'synthetic', 'media': media,
                       'approvedWindow': {'startSeconds': WINDOW_START, 'endSeconds': WINDOW_START + 12}},
            'transcript': {'artifact': {'sha256': TRANSCRIPT_SHA}},
            'anchors': {'artifact': {'jsonSha256': policies.canonical_sha256(anchor)}}}


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
    """The real payload and cache path, with a scripted provider response (one, or one per unit)."""

    def __init__(self, cache, response, **kwargs):
        self.response, self.payloads = response, []

        def caller(_key, payload):
            self.payloads.append(payload)
            question = json.loads(payload['messages'][1]['content'])
            scripted = self.response[question['sourceUnitId']] if 'schemaVersion' not in self.response else self.response
            return {'id': 'resp-1', 'model': machine.MODEL, 'choices': [
                {'finish_reason': 'stop', 'message': {'content': json.dumps(scripted)}}]}
        super().__init__(api_key='', cache=cache, caller=caller, **kwargs)


class SourceMeaningAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root / 'media.wav'
        self.anchor = anchor_for(UNITS)
        self.source = source(write_media(self.media), self.anchor)
        self.out = self.root / 'out'

    def adjudicate(self, listeners, adjudicator=None, cut=None, unit_ids=(DOUBTED,), media=None,
                   source_package=None, anchor=None):
        return machine.adjudicate(source_package or self.source, anchor or self.anchor, unit_ids=list(unit_ids),
                                  media=media, listeners=listeners, adjudicator=adjudicator, out_dir=self.out,
                                  cut=cut or FakeCutter())

    def test_listeners_hearing_the_frozen_words_confirm_without_a_model_call(self):
        cutter = FakeCutter()
        heard = [FakeListener('a', CLIP_HEARD),
                 FakeListener('b', "and someone is on it, you're filled in the middle of a trial, listen there is a "
                                   'throne in heaven and someone is seated on it')]
        receipt = self.adjudicate(heard, cut=cutter)
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['decidedBy'], row['correctedText']),
                         ('transcript_confirmed', 'listeners_agree_with_transcript', None))
        self.assertTrue(all(h['agreesWithFrozen'] and h['bounded'] for h in row['heard']))
        self.assertEqual(row['heard'][1]['unitWindow'], "you're filled in the middle of a trial,")
        self.assertEqual(row['heard'][1]['boundary'], {'before': 0.625, 'after': 1.0, 'reason': None})
        self.assertEqual(row['meaningNote'], machine.CONFIRMED_NOTE)
        self.assertIsNone(row['request'])
        self.assertEqual(row['unit'], {'start': 5.0, 'end': 6.5, 'referenceChunkId': '0'})
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
                 FakeListener('qwen', CLIP_HEARD_OTHER)]
        # The openai listener heard little of u4, so its window is unbounded and may hold u4's words:
        # a correction taken from it is refused even though the wording was heard.
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'corrected_text_unbounded'):
            self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
                'transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        shutil.rmtree(self.out)
        adjudicator = FakeAdjudicator(self.out / 'cache', answer(
            'transcript_corrected', 'qwen', "You're failing in the middle of a trial.",
            note='The speaker says the listener is failing during a trial; translate that literally.'))
        receipt = self.adjudicate(heard, adjudicator)
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['heardBy'], row['correctedText'], row['decidedBy']),
                         ('transcript_corrected', 'qwen', "You're failing in the middle of a trial.", 'model'))
        self.assertEqual(row['request']['responseId'], 'resp-1')
        self.assertFalse(row['request']['cached'])
        self.assertEqual(row['request']['bounds']['outputTokens'], limits.DEFAULT_REQUEST_LIMITS['maxCompletionTokens'])
        payload = adjudicator.payloads[0]
        self.assertEqual(limits.bounded_payload(payload, limits.DEFAULT_REQUEST_LIMITS), payload)
        question = json.loads(payload['messages'][1]['content'])
        self.assertEqual(question['frozenText'], FROZEN)
        self.assertEqual([c['position'] for c in question['context']], ['before', 'before', 'doubted', 'after', 'after'])
        self.assertEqual(question['listeners'][1]['heardForUnit'], "you're failing in the middle of a trial")
        self.assertFalse(question['listeners'][0]['agreesWithFrozen'])
        self.assertFalse(question['listeners'][0]['unitBoundedByNeighbours'])  # it heard little of u4
        self.assertTrue(question['listeners'][1]['unitBoundedByNeighbours'])
        self.assertEqual(question['listenerIndependence']['reason'], 'two_distinct_listener_models')
        self.assertEqual(receipt['adjudicator']['model'], machine.MODEL)
        self.assertIsNone(receipt['adjudicator']['route'])
        self.assertEqual(receipt['adjudicator']['requestLimits'], limits.DEFAULT_REQUEST_LIMITS)
        # The same request is served from the cache, not sent again, and does not count as a call.
        again = self.adjudicate(heard, adjudicator)
        self.assertEqual(len(adjudicator.payloads), 1)
        self.assertTrue(again['units'][0]['request']['cached'])
        self.assertEqual(adjudicator.calls, 1)

    def test_a_wording_nobody_heard_is_refused(self):
        heard = [FakeListener('openai', CLIP_HEARD_OTHER)]
        for response, code in (
                (answer('transcript_corrected', 'openai', "You're fulfilled in the middle of a trial."), 'corrected_text_not_heard'),
                (answer('transcript_corrected', 'frozen', FROZEN), 'corrected_by_frozen_words'),
                (answer('transcript_corrected', 'openai', None), 'corrected_text_missing'),
                (answer('transcript_confirmed', 'frozen', "You're failing in the middle of a trial."), 'corrected_text_without_correction'),
                (answer('transcript_confirmed', 'nobody'), 'answer_heard_by'),
                # The lone listener heard other words: a confirmation naming it contradicts itself.
                (answer('transcript_confirmed', 'openai'), 'confirmed_by_disagreeing_listener'),
                (answer('maybe'), 'answer_decision'),
                (answer('undetermined', note='x' * (machine.MAX_NOTE_CHARS + 1)), 'answer_note')):
            with self.subTest(code=code):
                shutil.rmtree(self.out, ignore_errors=True)
                with self.assertRaisesRegex(machine.SourceAdjudicationError, code):
                    self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', response))

    def test_rewritten_listener_facts_are_derived_again_and_refused(self):
        heard = [FakeListener('openai', CLIP_HEARD_OTHER), FakeListener('qwen', CLIP_HEARD)]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'undetermined', note='Translate the frozen English literally; the listeners disagree.')))
        machine.validate_receipt(receipt, anchor=self.anchor)
        self.assertTrue(receipt['listenerIndependence']['independent'])

        def confirmed(forge):
            value = json.loads(json.dumps(receipt))
            row = value['units'][0]
            row.update(decision='transcript_confirmed', heardBy='frozen', correctedText=None, request=None,
                       decidedBy='listeners_agree_with_transcript', meaningNote=machine.CONFIRMED_NOTE)
            forge(value, row)
            return value
        # A flipped agreement flag contradicts the tokens the receipt itself carries.
        flipped = confirmed(lambda value, row: row['heard'][0].update(agreesWithFrozen=True))
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_unit_hearings'):
            machine.validate_receipt(flipped)
        # Tokens rewritten to the frozen words contradict what the listener's transcript yields for the unit.
        rewritten = confirmed(lambda value, row: row['heard'][0].update(
            agreesWithFrozen=True, bounded=True, unitTokens=machine.tokens(FROZEN)))
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_unit_hearings'):
            machine.validate_receipt(rewritten, anchor=self.anchor)
        # A lone listener declared independent of the source ASR is derived again from the models named.
        lone = self.adjudicate([FakeListener('openai', CLIP_HEARD_OTHER)], FakeAdjudicator(
            self.out / 'cache-lone', answer('transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        self.assertFalse(lone['listenerIndependence']['independent'])
        forged = json.loads(json.dumps(lone))
        forged['listenerIndependence']['independent'] = True
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_listeners'):
            machine.validate_receipt(forged, anchor=self.anchor)
        forged['listenerIndependence']['sourceAsrModel'] = 'another-asr'
        forged['listenerIndependence']['independentOfSourceAsr'] = ['openai']
        forged['listenerIndependence']['reason'] = 'listener_differs_from_source_asr'
        self.assertEqual(forged['listenerIndependence'], machine.listener_independence(['openai'], 'another-asr'))
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_source_binding_changed'):
            machine.validate_receipt(forged, source=self.source, anchor=self.anchor)

    def test_disagreeing_listeners_may_end_undetermined_with_the_frozen_text_kept(self):
        heard = [FakeListener('openai', CLIP_HEARD_OTHER), FakeListener('qwen', CLIP_HEARD)]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'undetermined', note='Translate the frozen English literally; the listeners disagree.')))
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['correctedText']), ('undetermined', None))
        self.assertEqual([h['agreesWithFrozen'] for h in row['heard']], [False, True])
        self.assertIsNone(machine.source_text_review(receipt, self.anchor, segments(), receipt_name='receipt.json', receipt_sha256='0' * 64,
                                                     source_audio=self.media, asr_reference=self.media))

    def test_an_identical_phrase_in_a_neighbour_cannot_confirm_an_inaudible_unit(self):
        rows = units('Right now, your life is crazy.', FROZEN, FROZEN, 'Listen, there is a throne in heaven.')
        anchor = anchor_for(rows)
        package = source(self.source['source']['media'], anchor)
        heard = [FakeListener('openai', "your life is crazy you're filled in the middle of a trial listen there is a throne in heaven")]
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'adjudicator_required'):
            self.adjudicate(heard, unit_ids=['u3'], source_package=package, anchor=anchor)
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer('undetermined')),
                                  unit_ids=['u3'], source_package=package, anchor=anchor)
        listened = receipt['units'][0]['heard'][0]
        self.assertFalse(listened['bounded'])
        self.assertEqual(listened['boundary']['reason'], 'phrase_repeated_in_clip')
        self.assertEqual(receipt['units'][0]['decision'], 'undetermined')

    def test_corrected_unit_becomes_a_layer1_review_the_existing_path_applies(self):
        heard = [FakeListener('openai', CLIP_HEARD_OTHER)]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        receipt_path = self.out / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        clip, asr = self.root / 'clip.m4a', self.root / 'asr_reference.json'
        clip.write_bytes(b'window clip bytes')
        asr.write_text(json.dumps({'segments': segments()}), encoding='utf-8')
        review = machine.source_text_review(receipt, self.anchor, segments(), receipt_name='receipt.json',
                                            receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
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
        package = {'source': self.source, 'anchor': self.anchor, 'mediaSha256': self.source['source']['media']['sha256']}
        # The Layer 1 path needs the adjudicated package: the receipt is bound to it, not merely well-formed.
        with self.assertRaisesRegex(ValueError, 'requires the adjudicated source package'):
            source_review.apply_review(segments(), review_path, clip, asr)
        corrected, provenance = source_review.apply_review(segments(), review_path, clip, asr,
                                                           adjudicated_package=package)
        self.assertEqual(corrected[1]['text'], review['patches'][0]['correctedText'])
        self.assertEqual(corrected[0]['text'], segments()[0]['text'])
        self.assertEqual(provenance['authority'], source_review.MACHINE_AUTHORITY)
        self.assertEqual(provenance['reviewedBy'], receipt['decidedBy'])
        self.assertEqual(provenance['machineEvidence']['receiptSha256'], review['evidence'][0]['sha256'])
        self.assertEqual(provenance['machineEvidence']['bindings'], receipt['bindings'])
        other_anchor = {**self.anchor, 'sourceUnits': [dict(u, english=u['english'] + ' Really.')
                                                       if u['sourceUnitId'] == 'u3' else u for u in UNITS]}
        with self.assertRaisesRegex(ValueError, 'receipt_anchor_binding_changed'):
            source_review.apply_review(segments(), review_path, clip, asr,
                                       adjudicated_package={**package, 'anchor': other_anchor})
        with self.assertRaisesRegex(ValueError, 'receipt_media_binding_changed'):
            source_review.apply_review(segments(), review_path, clip, asr,
                                       adjudicated_package={**package, 'mediaSha256': 'f' * 64})
        # The review path accepts the machine authority only with the receipt behind it.
        tampered = dict(review, patches=[dict(review['patches'][0],
                                              correctedText="There's a throne, and someone is on it. You're fine.")])
        review_path.write_text(json.dumps(tampered), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, "differs from the receipt's corrections"):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        other = self.out / 'notes.json'
        other.write_text(json.dumps({'anything': True}), encoding='utf-8')
        review_path.write_text(json.dumps(dict(review, evidence=[
            {'path': 'notes.json', 'sha256': hashlib.sha256(other.read_bytes()).hexdigest()}],
            patches=[dict(review['patches'][0], evidenceSha256=hashlib.sha256(other.read_bytes()).hexdigest())])),
            encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'exactly one source-meaning receipt'):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)

        def rebind(changed):
            receipt_path.write_text(json.dumps(changed), encoding='utf-8')
            sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            review_path.write_text(json.dumps(dict(review, reviewedBy=changed['decidedBy'],
                                                   evidence=[{'path': 'receipt.json', 'sha256': sha}],
                                                   patches=[dict(review['patches'][0], evidenceSha256=sha)])),
                                   encoding='utf-8')
        rebind(dict(receipt, decidedBy='someone else'))
        with self.assertRaisesRegex(ValueError, 'receipt_signature'):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        # A synthetic receipt whose correction nobody heard, or that drops its hearings, is refused.
        unheard = dict(receipt, units=[dict(receipt['units'][0], correctedText="You're fine in the middle of a trial.")])
        rebind(unheard)
        with self.assertRaisesRegex(ValueError, 'receipt_correction_not_heard'):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        rebind(dict(receipt, units=[dict(receipt['units'][0], heard=[])]))
        with self.assertRaisesRegex(ValueError, 'receipt_unit_hearings'):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)

    def test_corrections_sharing_a_segment_become_one_patch(self):
        heard_text = ("right now your life is crazy there's a throne and someone is sitting on it you're failing in "
                      'the middle of a trial listen there is a throne in heaven and someone is seated on it')
        heard = [FakeListener('openai', heard_text)]
        adjudicator = FakeAdjudicator(self.out / 'cache', {
            'u2': answer('transcript_corrected', 'openai', "There's a throne, and someone is sitting on it."),
            'u3': answer('transcript_corrected', 'openai', "You're failing in the middle of a trial.")})
        receipt = self.adjudicate(heard, adjudicator, unit_ids=['u2', 'u3'])
        self.assertEqual([r['decision'] for r in receipt['units']], ['transcript_corrected'] * 2)
        receipt_path = self.out / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        clip, asr = self.root / 'clip.m4a', self.root / 'asr_reference.json'
        clip.write_bytes(b'window clip bytes')
        asr.write_text(json.dumps({'segments': segments()}), encoding='utf-8')
        review = machine.source_text_review(receipt, self.anchor, segments(), receipt_name='receipt.json',
                                            receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                                            source_audio=clip, asr_reference=asr)
        self.assertEqual(len(review['patches']), 1)
        self.assertEqual(review['patches'][0]['correctedText'],
                         "There's a throne, and someone is sitting on it. You're failing in the middle of a trial.")
        self.assertIn('u2 heard by openai', review['patches'][0]['reason'])
        self.assertIn('u3 heard by openai', review['patches'][0]['reason'])
        review_path = self.out / 'source-text-review.json'
        review_path.write_text(json.dumps(review), encoding='utf-8')
        package = {'source': self.source, 'anchor': self.anchor}
        corrected, _ = source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        self.assertEqual(corrected[1]['text'], review['patches'][0]['correctedText'])

    def test_every_receipt_correction_must_be_patched(self):
        # u1 and u3 sit in different ASR segments; a review that drops one segment's patch is refused.
        heard_text = ("right now your life is wild there's a throne and someone is on it you're failing in "
                      'the middle of a trial listen there is a throne in heaven and someone is seated on it')
        adjudicator = FakeAdjudicator(self.out / 'cache', {
            'u1': answer('transcript_corrected', 'openai', 'Right now, your life is wild.'),
            'u3': answer('transcript_corrected', 'openai', "You're failing in the middle of a trial.")})
        receipt = self.adjudicate([FakeListener('openai', heard_text)], adjudicator, unit_ids=['u1', 'u3'])
        self.assertEqual([r['decision'] for r in receipt['units']], ['transcript_corrected'] * 2)
        receipt_path = self.out / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        clip, asr = self.root / 'clip.m4a', self.root / 'asr_reference.json'
        clip.write_bytes(b'window clip bytes')
        asr.write_text(json.dumps({'segments': segments()}), encoding='utf-8')
        review = machine.source_text_review(receipt, self.anchor, segments(), receipt_name='receipt.json',
                                            receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                                            source_audio=clip, asr_reference=asr)
        self.assertEqual([p['segmentId'] for p in review['patches']], [0, 1])
        review_path = self.out / 'source-text-review.json'
        package = {'source': self.source, 'anchor': self.anchor}
        review_path.write_text(json.dumps(review), encoding='utf-8')
        corrected, provenance = source_review.apply_review(segments(), review_path, clip, asr,
                                                           adjudicated_package=package)
        self.assertEqual(provenance['correctedSegmentIds'], [0, 1])
        self.assertEqual(corrected[0]['text'], 'Right now, your life is wild.')
        review_path.write_text(json.dumps(dict(review, patches=review['patches'][1:])), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'omits receipt corrections for units: u1'):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)

    def test_review_refuses_a_unit_whose_segment_cannot_be_located(self):
        heard = [FakeListener('openai', CLIP_HEARD_OTHER)]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        rows = segments()
        rows[1]['text'] = rows[1]['text'].replace('filled', 'filled,')
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'segment_not_located'):
            machine.source_text_review(receipt, self.anchor, rows, receipt_name='receipt.json', receipt_sha256='0' * 64,
                                       source_audio=self.media, asr_reference=self.media)

    def test_bindings_and_refusals(self):
        heard = [FakeListener('a', CLIP_HEARD), FakeListener('b', CLIP_HEARD)]
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
        # The anchor must be the one the package names, built on the package's transcript.
        stale = anchor_for(units(*[u['english'] for u in UNITS], start=2.0))
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'anchor_not_bound_to_source'):
            self.adjudicate(heard, anchor=stale)
        rebuilt = {**self.anchor, 'input': {'mfaSegmentsSha256': 'f' * 64}}
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'anchor_transcript_binding_changed'):
            self.adjudicate(heard, anchor=rebuilt, source_package=source(self.source['source']['media'], rebuilt))
        receipt = self.adjudicate(heard, media=self.media)
        self.assertEqual(receipt['bindings']['anchor.json'], policies.canonical_sha256(self.anchor))
        self.assertEqual(receipt['bindings']['anchor.json'], self.source['anchors']['artifact']['jsonSha256'])

    def test_adjudicator_model_and_call_cap_are_enforced_before_dispatch(self):
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'unsupported_adjudicator_model'):
            machine.SolAdjudicator(api_key='', cache=self.out, model='gpt-6-sol', caller=lambda *_: {})
        self.assertNotIn('gpt-6-sol', machine.ADJUDICATOR_MODELS)
        self.assertIn(machine.MODEL, machine.ADJUDICATOR_MODELS)
        capped = FakeAdjudicator(self.out / 'cache', answer('undetermined'), max_calls=0)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'adjudicator_call_cap_reached'):
            self.adjudicate([FakeListener('openai', CLIP_HEARD_OTHER)], capped)
        self.assertEqual(capped.payloads, [])

    def test_a_lone_listener_that_may_be_the_source_asr_cannot_confirm_without_the_adjudicator(self):
        heard = [FakeListener('gpt-transcribe', CLIP_HEARD)]
        # The 605 package records its ASR model as unknown: one listener proves nothing.
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'adjudicator_required'):
            self.adjudicate(heard)
        same = dict(self.source, transcript={'artifact': {'sha256': TRANSCRIPT_SHA},
                                             'provenance': {'kind': 'asr', 'model': 'gpt-transcribe'}})
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'adjudicator_required'):
            self.adjudicate(heard, source_package=same)
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer('transcript_confirmed')),
                                  source_package=same)
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['decidedBy']), ('transcript_confirmed', 'model'))
        self.assertEqual(receipt['listenerIndependence'],
                         {'sourceAsrModel': 'gpt-transcribe', 'listenerModels': ['gpt-transcribe'],
                          'independentOfSourceAsr': [], 'independent': False,
                          'reason': 'single_listener_not_independent_of_source_asr'})
        # A listener known to differ from the source ASR is independent on its own.
        shutil.rmtree(self.out)
        other = dict(self.source, transcript={'artifact': {'sha256': TRANSCRIPT_SHA},
                                              'provenance': {'kind': 'asr', 'model': 'whisper-large-v3'}})
        receipt = self.adjudicate(heard, source_package=other)
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['decidedBy']), ('transcript_confirmed', 'listeners_agree_with_transcript'))
        self.assertIn('listener_differs_from_source_asr', row['reason'])
        self.assertEqual(receipt['listenerIndependence']['independentOfSourceAsr'], ['gpt-transcribe'])

    def test_paid_identities_and_caches_carry_the_selected_openai_project(self):
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'openai_environment_launcher_required'):
            machine.OpenAiTranscribeListener(cache=self.out / 'openai', max_calls=1)
        route = {'SERMON_OPENAI_ENVIRONMENT': 'dev', 'OPENAI_PROJECT_ID': 'proj_devOnly',
                 'SERMON_OPENAI_CREDENTIAL_ALIAS': 'tongxing-dev-runtime', 'OPENAI_API_KEY': 'not-a-real-key'}
        with mock.patch.dict(os.environ, route):
            listener = machine.OpenAiTranscribeListener(cache=self.out / 'openai', max_calls=1)
            dev = FakeAdjudicator(self.out / 'cache', answer('undetermined'))
            dev_receipt = self.adjudicate([FakeListener('openai', CLIP_HEARD_OTHER)], dev)
        expected = {'environment': 'dev', 'projectId': 'proj_devOnly', 'credentialAlias': 'tongxing-dev-runtime'}
        self.assertEqual(listener.identity()['route'], expected)
        self.assertNotIn('not-a-real-key', json.dumps(listener.identity()))
        self.assertEqual((dev.route, dev.route_key), (expected, 'dev-proj_devOnly'))
        self.assertIn('source-meaning-dev-proj_devOnly-u3', dev_receipt['units'][0]['request']['path'])
        self.assertEqual(dev_receipt['adjudicator']['route'], expected)
        # The same question under prod is a new request, never the dev answer from the cache.
        with mock.patch.dict(os.environ, {**route, 'SERMON_OPENAI_ENVIRONMENT': 'prod',
                                          'OPENAI_PROJECT_ID': 'proj_prodOnly',
                                          'SERMON_OPENAI_CREDENTIAL_ALIAS': 'tongxing-prod-runtime'}):
            prod = FakeAdjudicator(self.out / 'cache', answer('undetermined'))
            prod_receipt = self.adjudicate([FakeListener('openai', CLIP_HEARD_OTHER)], prod)
        self.assertEqual((len(dev.payloads), len(prod.payloads)), (1, 1))
        self.assertFalse(prod_receipt['units'][0]['request']['cached'])
        self.assertNotEqual(dev_receipt['units'][0]['request']['path'], prod_receipt['units'][0]['request']['path'])

    def test_meaning_notes_bind_the_kept_units_for_the_layer2_repair_brief(self):
        heard = [FakeListener('a', CLIP_HEARD), FakeListener('b', CLIP_HEARD)]
        receipt = self.adjudicate(heard)
        encoded = machine._encode(receipt)
        notes = machine.meaning_notes(receipt, receipt_sha256=hashlib.sha256(encoded).hexdigest())
        self.assertEqual(notes['schemaVersion'], machine.NOTES_SCHEMA)
        self.assertEqual(notes['bindings'], receipt['bindings'])
        self.assertIs(notes['humanApproval'], False)
        self.assertEqual([(u['sourceUnitId'], u['decision'], u['meaningNote']) for u in notes['units']],
                         [('u3', 'transcript_confirmed', machine.CONFIRMED_NOTE)])
        path = self.out / 'meaning-notes.json'
        machine._write_new(path, notes)
        # The notes are a projection of the receipt: without it beside them (the CLI writes it last) nothing loads.
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'meaning_notes_receipt_missing'):
            machine.load_meaning_notes(path, source=self.source, anchor=self.anchor)
        machine._write_new(self.out / 'receipt.json', receipt)
        loaded = machine.load_meaning_notes(path, source=self.source, anchor=self.anchor)
        self.assertEqual(list(loaded), ['u3'])
        self.assertEqual(machine.repair_instruction(loaded, ['u2', 'u3']),
                         f'Source unit u3 (transcript confirmed by machine audio adjudication): {machine.CONFIRMED_NOTE}')
        self.assertEqual(machine.repair_instruction(loaded, ['u1', 'u2']), '')
        # A receipt with other bytes than the notes name, or a note the receipt did not decide, is refused.
        elsewhere = self.out / 'elsewhere'
        machine._write_new(elsewhere / 'receipt.json', dict(receipt, reviewedAt='2026-10-09T00:00:00+00:00'))
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'meaning_notes_receipt_changed'):
            machine.load_meaning_notes(path, source=self.source, anchor=self.anchor,
                                       receipt_path=elsewhere / 'receipt.json')
        forged = dict(notes, units=[dict(notes['units'][0], meaningNote='Render it as a promise of relief.')])
        machine._write_new(self.out / 'forged-notes.json', forged)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'meaning_notes_unit_changed'):
            machine.load_meaning_notes(self.out / 'forged-notes.json', source=self.source, anchor=self.anchor)
        stale = dict(notes, units=[dict(notes['units'][0], decision='undetermined')])
        machine._write_new(self.out / 'stale-notes.json', stale)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'meaning_notes_unit_changed'):
            machine.load_meaning_notes(self.out / 'stale-notes.json', source=self.source, anchor=self.anchor)
        # Notes for other Layer 1 inputs are refused before any receipt is read, and a notes file rebound
        # to a changed anchor no longer matches the receipt it names.
        rebuilt = {**self.anchor, 'input': {'mfaSegmentsSha256': 'f' * 64}}
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'meaning_notes_binding_changed'):
            machine.load_meaning_notes(path, source=self.source, anchor=rebuilt)
        changed = {**self.anchor, 'sourceUnits': [dict(u, english=u['english'] + ' Really.') if u['sourceUnitId'] == 'u3'
                                                  else u for u in UNITS]}
        tampered = dict(notes, bindings={**notes['bindings'], 'anchor.json': policies.canonical_sha256(changed)})
        other = self.out / 'tampered-notes.json'
        machine._write_new(other, tampered)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_anchor_binding_changed'):
            machine.load_meaning_notes(other, source=self.source, anchor=changed)
        # A run that corrected every doubted unit has no note to pass on.
        shutil.rmtree(self.out)
        corrected = self.adjudicate([FakeListener('openai', CLIP_HEARD_OTHER)], FakeAdjudicator(
            self.out / 'cache', answer('transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        self.assertIsNone(machine.meaning_notes(corrected, receipt_sha256='0' * 64))

    def test_the_review_binds_the_receipt_bytes_the_cli_writes_afterwards(self):
        receipt = self.adjudicate([FakeListener('openai', CLIP_HEARD_OTHER)], FakeAdjudicator(
            self.out / 'cache', answer('transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        clip, asr = self.root / 'clip.m4a', self.root / 'asr_reference.json'
        clip.write_bytes(b'window clip bytes')
        asr.write_text(json.dumps({'segments': segments()}), encoding='utf-8')
        file_sha = hashlib.sha256(machine._encode(receipt)).hexdigest()
        review = machine.source_text_review(receipt, self.anchor, segments(), receipt_name='receipt.json',
                                            receipt_sha256=file_sha, source_audio=clip, asr_reference=asr)
        self.assertFalse((self.out / 'receipt.json').exists())  # built before the completion marker exists
        notes = machine.meaning_notes(receipt, receipt_sha256=file_sha)
        # The sidecars are written and flushed before the receipt: a failure at the receipt leaves them
        # beside no completion marker, and the next attempt discards and derives them again.
        real_write = machine._write_new

        def fail_at_receipt(path, value):
            if path.name == 'receipt.json':
                raise OSError('disk full')
            real_write(path, value)
        with mock.patch.object(machine, '_write_new', side_effect=fail_at_receipt):
            with self.assertRaises(OSError):
                machine.write_outputs(self.out, receipt, review, notes)
        self.assertTrue((self.out / 'source-text-review.json').is_file())
        self.assertFalse((self.out / 'receipt.json').exists())
        self.assertEqual(machine.resumable_out_dir(self.out), self.out)
        self.assertFalse((self.out / 'source-text-review.json').exists())
        written = machine.write_outputs(self.out, receipt, review, notes)
        self.assertEqual(written['review'], str((self.out / 'source-text-review.json').resolve()))
        self.assertIsNone(written['meaningNotes'])  # every doubted unit was corrected
        self.assertEqual(hashlib.sha256((self.out / 'receipt.json').read_bytes()).hexdigest(), file_sha)
        self.assertEqual(review['evidence'], [{'path': 'receipt.json', 'sha256': file_sha}])
        with self.assertRaises(FileExistsError):
            machine._write_new(self.out / 'receipt.json', receipt)
        with self.assertRaises(SystemExit):
            machine.resumable_out_dir(self.out)  # a finished directory, sidecars included, is never touched
        self.assertTrue((self.out / 'source-text-review.json').is_file())

    def test_a_crash_while_writing_the_receipt_leaves_no_completion_marker(self):
        receipt = self.adjudicate([FakeListener('openai', CLIP_HEARD_OTHER)], FakeAdjudicator(
            self.out / 'cache', answer('transcript_corrected', 'openai', "You're failing in the middle of a trial.")))
        partial = self.out / '.receipt.json.partial'

        def killed(_fd):
            raise OSError('killed before the bytes reached disk')
        with mock.patch.object(machine.os, 'fsync', side_effect=killed):
            with self.assertRaises(OSError):
                machine.write_outputs(self.out, receipt, None, None)
        # The name a resume checks for never exists half-written; only the unpublished bytes do.
        self.assertFalse((self.out / 'receipt.json').exists())
        self.assertTrue(partial.is_file())
        self.assertEqual(machine.resumable_out_dir(self.out), self.out)
        self.assertFalse(partial.exists())
        machine.write_outputs(self.out, receipt, None, None)
        self.assertEqual(hashlib.sha256((self.out / 'receipt.json').read_bytes()).hexdigest(),
                         hashlib.sha256(machine._encode(receipt)).hexdigest())
        self.assertFalse(partial.exists())
        # Publication never replaces an existing receipt, and leaves no partial file behind the refusal.
        with self.assertRaises(FileExistsError):
            machine._write_new(self.out / 'receipt.json', dict(receipt, reviewedAt='2026-10-09T00:00:00+00:00'))
        self.assertFalse(partial.exists())
        self.assertEqual(hashlib.sha256((self.out / 'receipt.json').read_bytes()).hexdigest(),
                         hashlib.sha256(machine._encode(receipt)).hexdigest())

    def test_locate_unit_is_bounded_by_the_neighbours_and_ignores_presentation(self):
        frozen = machine.tokens(FROZEN)
        self.assertEqual(frozen, ["you're", 'filled', 'in', 'the', 'middle', 'of', 'a', 'trial'])
        before, after = machine.tokens(UNITS[1]['english']), machine.tokens(UNITS[3]['english'])
        found = machine.locate_unit(before, frozen, after,
                                    "There's a throne, and someone is on it. You’re FILLED, in the middle of a trial! "
                                    'Listen, there is a throne in heaven, and someone is seated on it.')
        self.assertEqual((found['tokens'], found['similarity'], found['bounded']), (frozen, 1.0, True))
        found = machine.locate_unit(before, frozen, after, CLIP_HEARD_OTHER)
        self.assertEqual(found['text'], "you're failing in the middle of a trial")
        self.assertLess(found['similarity'], 1.0)
        # An extra word heard at the boundary belongs to the doubted stretch, so it is not confirmed silently.
        found = machine.locate_unit(before, frozen, after, CLIP_HEARD.replace("You're", "Right, you're"))
        self.assertEqual(found['tokens'][:2], ['right', "you're"])
        # A unit at the clip edge is bounded by the edge.
        found = machine.locate_unit([], frozen, after, CLIP_HEARD.split('. ', 1)[1])
        self.assertEqual((found['tokens'], found['bounded'], found['boundary']['before']), (frozen, True, None))
        # Neighbours the listener barely heard cannot bound the stretch.
        found = machine.locate_unit(before, frozen, after, FROZEN)
        self.assertEqual((found['tokens'], found['bounded'], found['boundary']['reason']),
                         (frozen, False, 'neighbour_not_heard'))
        self.assertEqual(machine.locate_unit(before, frozen, after, '')['boundary']['reason'], 'nothing_heard')

    def test_qwen_listener_identity_binds_weights_runtime_and_settings(self):
        model_dir = self.root / 'qwen'
        model_dir.mkdir()
        (model_dir / 'model.safetensors').write_bytes(b'weights')
        probes = []
        session = {'sessionId': 's1', 'jobId': 'j1', 'owner': 'me', 'bootId': 'b1'}

        def probe(path):
            probes.append(path)
            return {'backend': 'qwen-asr-local', 'torchVersion': '2.9.0', 'qwenAsrVersion': '0.1.0',
                    'modelMetadataSha256s': {'config.json': 'a' * 64}}
        listener = machine.QwenListener(model_dir, cache=self.out / 'qwen', identity_probe=probe,
                                        session_verifier=lambda: dict(session, secret='x'))
        self.assertEqual(listener.identity()['host'], 'spark_exclusive_session')
        # The weights load only once a live Spark exclusive session owns this process.
        from scripts.spark_exclusive_session import SessionError

        def refused():
            raise SessionError('model_session_requires_bound_live_parent')
        same_runtime = lambda path: dict(listener.runtime)  # noqa: E731  (a second probe would be recorded)
        unowned = machine.QwenListener(model_dir, cache=self.out / 'qwen', identity_probe=same_runtime,
                                       session_verifier=refused)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'qwen_requires_bound_spark_exclusive_session'):
            unowned.transcribe(b'RIFF')
        self.assertIsNone(unowned._model)
        owned = machine.QwenListener(model_dir, cache=self.out / 'qwen', identity_probe=same_runtime,
                                     session_verifier=lambda: dict(session, secret='x'))
        owned._admit()
        self.assertEqual(owned.session_receipt, session)
        self.assertNotIn('session', owned.identity())  # a session is not part of the cache identity
        identity = listener.identity()
        self.assertEqual(probes, [model_dir.resolve()])
        self.assertEqual(identity['runtime']['qwenAsrVersion'], '0.1.0')
        self.assertEqual(identity['settings'], machine.QWEN_SETTINGS)
        self.assertEqual(identity['modelRevision'], f'model.safetensors:sha256:{hashlib.sha256(b"weights").hexdigest()}')
        runs = []
        listener._admit()
        listener._run = lambda wav: runs.append(wav) or 'heard once'
        self.assertEqual(listener.transcribe(b'clip'), 'heard once')
        self.assertEqual(listener.transcribe(b'clip'), 'heard once')
        self.assertEqual(len(runs), 1)
        self.assertEqual(listener.sessions, [session])
        # A fresh process resuming from the cache owns no session; the entry restores the one that generated
        # the transcript, so the receipt still records the bound compute identity instead of null.
        resumed = machine.QwenListener(model_dir, cache=self.out / 'qwen', identity_probe=same_runtime,
                                       session_verifier=refused)
        self.assertEqual(resumed.transcribe(b'clip'), 'heard once')
        self.assertEqual((resumed.session_receipt, resumed.sessions, resumed._model), (session, [session], None))
        self.assertEqual(len(runs), 1)
        # Clips generated in a later session join the cached one; both sessions stay on record.
        later = {'sessionId': 's2', 'jobId': 'j2', 'owner': 'me', 'bootId': 'b2'}
        continued = machine.QwenListener(model_dir, cache=self.out / 'qwen', identity_probe=same_runtime,
                                         session_verifier=lambda: later)
        continued._admit()
        continued._run = lambda wav: runs.append(wav) or 'heard later'
        self.assertEqual((continued.transcribe(b'clip'), continued.transcribe(b'clip two')), ('heard once', 'heard later'))
        self.assertEqual((continued.session_receipt, continued.sessions), (later, [session, later]))
        # A different runtime (package upgrade, changed model metadata) is another listener: no cache reuse.
        upgraded = machine.QwenListener(model_dir, cache=self.out / 'qwen', identity_probe=lambda p: {
            **probe(p), 'qwenAsrVersion': '0.2.0'}, session_verifier=lambda: later)
        upgraded._admit()
        upgraded._run = lambda wav: runs.append(wav) or 'heard again'
        self.assertEqual(upgraded.transcribe(b'clip'), 'heard again')
        self.assertEqual(len(runs), 3)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'qwen_runtime_identity'):
            machine.QwenListener(model_dir, cache=self.out / 'qwen', identity_probe=lambda p: {'backend': 'other'})

    def test_out_dir_resumes_an_incomplete_attempt_but_never_a_finished_one(self):
        self.assertEqual(machine.resumable_out_dir(self.out), self.out)
        (self.out / 'cache').mkdir(parents=True)
        self.assertEqual(machine.resumable_out_dir(self.out), self.out)
        (self.out / 'receipt.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(SystemExit, 'already holds a receipt'):
            machine.resumable_out_dir(self.out)
        with self.assertRaisesRegex(SystemExit, 'not a directory'):
            machine.resumable_out_dir(self.media)

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
