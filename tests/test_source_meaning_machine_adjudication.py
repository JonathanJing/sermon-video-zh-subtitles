"""Source-meaning adjudication: only heard wordings, bound audio, no human approval.

Units are synthetic sentences shaped like the 605 sample around its doubted
unit. Audio is a generated WAV; listeners and the adjudicator are fakes that
record what they were given, so these tests prove the plumbing and the
invariants, not any model's hearing.
"""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest import mock
import wave

from scripts import canonical_layer2_controller as controller
from scripts import machine_qc_audio_transports as transports
from scripts import sermon_provider_limits as limits
from scripts import sermon_sentence_interpretation as contract
from scripts import sermon_source_budget as source_budget
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


def wav_bytes(seconds: float) -> bytes:
    """A silent 16 kHz mono PCM16 clip, as ``cut_clip`` yields."""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(machine.SAMPLE_RATE)
        frames = int(machine.SAMPLE_RATE * seconds)
        handle.writeframes(struct.pack(f'<{frames}h', *([0] * frames)))
    return buffer.getvalue()


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


def as_v1(receipt):
    """The receipt as the last v1 writer (dev at 907c998) signed it, without a budget record."""
    implementation = 'e856a679593682306943eda3a41a1c0301140f1db18ba2c1d6aca8b02074be6c'
    version = machine.V1_IMPLEMENTATIONS[implementation]
    return dict({k: v for k, v in receipt.items() if k != 'budget'}, schemaVersion=machine.SCHEMA_V1, version=version,
                implementationSha256=implementation,
                decidedBy=f'source_meaning_machine_adjudication {version} {implementation[:16]}')


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
        machine.validate_receipt(receipt, anchor=self.anchor, cache=self.out / 'cache')
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
            machine.validate_receipt(forged, anchor=self.anchor, cache=self.out / 'cache-lone')
        forged['listenerIndependence']['sourceAsrModel'] = 'another-asr'
        forged['listenerIndependence']['independentOfSourceAsr'] = ['openai']
        forged['listenerIndependence']['reason'] = 'listener_differs_from_source_asr'
        self.assertEqual(forged['listenerIndependence'], machine.listener_independence(['openai'], 'another-asr'))
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_source_binding_changed'):
            machine.validate_receipt(forged, source=self.source, anchor=self.anchor, cache=self.out / 'cache-lone')

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

        def rebind(changed, schema=review['schemaVersion']):
            receipt_path.write_text(json.dumps(changed), encoding='utf-8')
            sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            review_path.write_text(json.dumps(dict(review, schemaVersion=schema, reviewedBy=changed['decidedBy'],
                                                   evidence=[{'path': 'receipt.json', 'sha256': sha}],
                                                   patches=[dict(review['patches'][0], evidenceSha256=sha)])),
                                   encoding='utf-8')
        rebind(dict(receipt, decidedBy='someone else'))
        with self.assertRaisesRegex(ValueError, 'receipt_signature'):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        # A receipt whose correction is not the one Sol's cached response gave, or that drops its
        # hearings, is refused: each verdict is derived again from the request cache beside the receipt.
        unheard = dict(receipt, units=[dict(receipt['units'][0], correctedText="You're fine in the middle of a trial.")])
        rebind(unheard)
        with self.assertRaisesRegex(ValueError, 'receipt_verdict_not_from_model'):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        moved = self.out / 'cache'
        shutil.move(moved, self.out / 'cache-elsewhere')
        rebind(receipt)
        with self.assertRaisesRegex(ValueError, 'receipt_model_response_missing'):
            source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        # A v1 receipt (written before verdicts were derived again from the cache) is still read by the
        # Layer 1 path under its own rules, without the cache.
        rebind(as_v1(receipt))
        corrected, _ = source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        self.assertEqual(corrected[1]['text'], review['patches'][0]['correctedText'])
        # A machine review the pre-v2 writers labelled v1 stays readable on their own v1 receipt.
        self.assertEqual(review['schemaVersion'], source_review.SCHEMA_V2)
        rebind(as_v1(receipt), schema=source_review.SCHEMA)
        corrected, provenance = source_review.apply_review(segments(), review_path, clip, asr,
                                                           adjudicated_package=package)
        self.assertEqual(corrected[1]['text'], review['patches'][0]['correctedText'])
        self.assertEqual(provenance['schemaVersion'], source_review.SCHEMA)
        # A v1 label on a receipt from a later writer, or on a v2 receipt, is refused.
        later = '95e48ac4649725369526a2e83a500e87303bc17b7231f404a7d736166b6867e7'
        self.assertIn(later, machine.V1_IMPLEMENTATIONS)
        self.assertNotIn(later, source_review.V1_MACHINE_REVIEW_WRITERS)
        later_v1 = dict(as_v1(receipt), version=machine.V1_IMPLEMENTATIONS[later], implementationSha256=later,
                        decidedBy=f'source_meaning_machine_adjudication {machine.V1_IMPLEMENTATIONS[later]} {later[:16]}')
        for changed in (later_v1, receipt):
            rebind(changed, schema=source_review.SCHEMA)
            with self.subTest(receipt=changed['schemaVersion']), \
                    self.assertRaisesRegex(ValueError, 'requires the sermon-source-text-review-v2 contract'):
                source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        rebind(later_v1)
        corrected, _ = source_review.apply_review(segments(), review_path, clip, asr, adjudicated_package=package)
        self.assertEqual(corrected[1]['text'], review['patches'][0]['correctedText'])
        shutil.move(self.out / 'cache-elsewhere', moved)
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
        # Each receipt names the Project its cached request was asked under, and no other.
        cache = self.out / 'cache'
        for receipt in (dev_receipt, prod_receipt):
            machine.validate_receipt(receipt, anchor=self.anchor, cache=cache)
        claimed = dict(prod_receipt, adjudicator=dict(prod_receipt['adjudicator'], route=expected))
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_model_runtime_changed'):
            machine.validate_receipt(claimed, anchor=self.anchor, cache=cache)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_model_runtime_changed'):
            machine.validate_receipt(dict(dev_receipt, adjudicator=dict(dev_receipt['adjudicator'], route=None)),
                                     anchor=self.anchor, cache=cache)
        # A route the launcher could never select (dev with the prod credential) is refused outright.
        mixed = dict(expected, credentialAlias='tongxing-prod-runtime')
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_adjudicator_runtime'):
            machine.validate_receipt(dict(dev_receipt, adjudicator=dict(dev_receipt['adjudicator'], route=mixed)),
                                     anchor=self.anchor, cache=cache)

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

    def test_a_model_verdict_is_derived_again_from_its_cached_response(self):
        heard = [FakeListener('openai', CLIP_HEARD_OTHER), FakeListener('qwen', CLIP_HEARD)]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'undetermined', note='Translate the frozen English literally; the listeners disagree.')))
        cache = self.out / 'cache'
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['decidedBy'], row['heard'][0]['bounded']), ('undetermined', 'model', True))
        summary = machine.validate_receipt(receipt, source=self.source, anchor=self.anchor, cache=cache)
        self.assertEqual(summary['correctedUnits'], [])
        # The request cache is the evidence: a model-decided row is not accepted without it.
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_model_response_missing'):
            machine.validate_receipt(receipt, anchor=self.anchor)
        # A row edited into a correction the bounded listener did hear, but Sol never gave, is refused,
        # as is any edited note or reason: the verdict must be the cached response's.
        edited = json.loads(json.dumps(receipt))
        edited['units'][0].update(decision='transcript_corrected', heardBy='openai', correctedText=HEARD_OTHER)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_verdict_not_from_model'):
            machine.validate_receipt(edited, anchor=self.anchor, cache=cache)
        for key, value in (('meaningNote', 'Render it as a promise of relief.'), ('reason', 'edited')):
            changed = json.loads(json.dumps(receipt))
            changed['units'][0][key] = value
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_verdict_not_from_model'):
                machine.validate_receipt(changed, anchor=self.anchor, cache=cache)
        # The receipt names the one tier its run could use: an unbound run's is the default tier, whole.
        # Another supported tier, even one whose payload is the same (a larger input cap, another wall
        # time), an unsupported one, or (under a budget) a tier other than the approved one is refused.
        self.assertEqual(receipt['adjudicator']['requestLimits'], limits.DEFAULT_REQUEST_LIMITS)
        larger = dict(receipt['adjudicator']['requestLimits'], maxCompletionTokens=8192)
        for changed in (larger, dict(larger, maxCompletionTokens=4096, maxInputTokens=16384),
                        dict(larger, maxCompletionTokens=4096, wallTimeMs=120000),
                        dict(receipt['adjudicator']['requestLimits'], serviceTier='flex')):
            with self.subTest(limits=changed), \
                    self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_adjudicator_runtime'):
                machine.validate_receipt(dict(receipt, adjudicator=dict(receipt['adjudicator'], requestLimits=changed)),
                                         anchor=self.anchor, cache=cache)
        budget = {'schemaVersion': machine.BUDGET_SCHEMA, 'authorizationSha256': 'a' * 64, 'approvalSha256': 'b' * 64,
                  'budgetRoot': str((self.out / machine.BUDGET_DIR).resolve()),
                  'globalBounds': {metric: 1000 for metric in source_budget.METRICS}, 'requestLimits': larger}
        route = {'environment': 'dev', 'projectId': 'proj_devOnly', 'credentialAlias': 'tongxing-dev-runtime'}
        for adjudicator in (receipt['adjudicator'], dict(receipt['adjudicator'], route=route)):
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_adjudicator_runtime'):
                machine.validate_receipt(dict(receipt, budget=budget, adjudicator=adjudicator),
                                         anchor=self.anchor, cache=cache)
        # The budget's own tier, with a payload its cache was not asked under, is refused at the cache.
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_model_runtime_changed'):
            machine.validate_receipt(dict(receipt, budget=budget, adjudicator=dict(
                receipt['adjudicator'], route=route, requestLimits=larger)), anchor=self.anchor, cache=cache)
        # A cached response rewritten to match the edit no longer hashes to what the row names.
        path = Path(row['request']['path'])
        cached = json.loads(path.read_text(encoding='utf-8'))
        cached['response']['choices'][0]['message']['content'] = json.dumps(
            answer('transcript_corrected', 'openai', HEARD_OTHER))
        cached['responseSha256'] = contract.json_sha256(cached['response'])
        path.write_text(json.dumps(cached, sort_keys=True), encoding='utf-8')
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_model_response_changed'):
            machine.validate_receipt(edited, anchor=self.anchor, cache=cache)
        path.unlink()
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_model_response_missing'):
            machine.validate_receipt(receipt, anchor=self.anchor, cache=cache)
        # A v1 receipt predates the request-cache contract and keeps its rules: its model row names a
        # request and is read without the cache, as it was before. It never carried a budget record.
        v1 = as_v1(receipt)
        summary = machine.validate_receipt(v1, source=self.source, anchor=self.anchor)
        self.assertEqual(summary['units'], ['u3'])
        # Only a receipt signed by an implementation that wrote v1 keeps those rules: relabelling this receipt
        # (signed by the current implementation, or by any other) as v1 does not switch off the cache checks.
        relabelled = dict({k: v for k, v in receipt.items() if k != 'budget'}, schemaVersion=machine.SCHEMA_V1)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_v1_implementation_unknown'):
            machine.validate_receipt(relabelled, source=self.source, anchor=self.anchor)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_v1_implementation_unknown'):
            machine.validate_receipt(dict(v1, version='2026-10-08-v1', decidedBy=v1['decidedBy'].replace(
                v1['version'], '2026-10-08-v1')), source=self.source, anchor=self.anchor)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_decision_evidence'):
            machine.validate_receipt(dict(v1, units=[dict(v1['units'][0], request=None)]), anchor=self.anchor)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_schema'):
            machine.validate_receipt(dict(v1, schemaVersion='sermon-source-meaning-machine-adjudication-v3'))

    def test_the_cached_question_must_be_the_one_the_receipt_and_anchor_ask(self):
        heard = [FakeListener('openai', CLIP_HEARD_OTHER), FakeListener('qwen', CLIP_HEARD)]
        receipt = self.adjudicate(heard, FakeAdjudicator(self.out / 'cache', answer(
            'undetermined', note='Translate the frozen English literally; the listeners disagree.')))
        cache = self.out / 'cache'
        machine.validate_receipt(receipt, source=self.source, anchor=self.anchor, cache=cache)
        path = Path(receipt['units'][0]['request']['path'])
        original = path.read_bytes()

        def asked_instead(change):
            """The same unit, frozen text, transcripts and answer, asked with other context or evidence."""
            path.write_bytes(original)
            cached = json.loads(original)
            question = json.loads(cached['request']['payload']['messages'][1]['content'])
            change(question)
            cached['request']['payload']['messages'][1]['content'] = json.dumps(question)
            cached['requestSha256'] = contract.json_sha256(cached['request'])
            path.write_text(json.dumps(cached, sort_keys=True), encoding='utf-8')
            forged = json.loads(json.dumps(receipt))
            forged['units'][0]['request'].update(sha256=contract.sha256(path), requestSha256=cached['requestSha256'])
            return forged
        for name, change in (
                ('context', lambda q: q['context'][0].update(english='Something else was said before.')),
                ('independence', lambda q: q['listenerIndependence'].update(independent=False)),
                ('clip', lambda q: q['clip'].update(seconds=q['clip']['seconds'] + 1)),
                ('heardForUnit', lambda q: q['listeners'][0].update(heardForUnit='a different stretch')),
                ('boundary', lambda q: q['listeners'][0].update(unitBoundedByNeighbours=False))):
            with self.subTest(changed=name):
                forged = asked_instead(change)
                # Without the anchor only the unit, its frozen text and the raw transcripts can be compared.
                machine.validate_receipt(forged, cache=cache)
                with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_model_question_changed'):
                    machine.validate_receipt(forged, anchor=self.anchor, cache=cache)
        path.write_bytes(original)
        # The clip a row names must be the anchor's, and every derived hearing fact is derived again.
        moved = json.loads(json.dumps(receipt))
        moved['units'][0]['clip']['windowStart'] += 0.5
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_unit_not_in_anchor'):
            machine.validate_receipt(moved, anchor=self.anchor, cache=cache)
        edited = json.loads(json.dumps(receipt))
        edited['units'][0]['heard'][0]['similarityToFrozen'] = 0.99
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_unit_hearings'):
            machine.validate_receipt(edited, anchor=self.anchor, cache=cache)

    def test_new_paid_calls_dispatch_only_through_a_bound_budget_authorization(self):
        route = {'SERMON_OPENAI_ENVIRONMENT': 'dev', 'OPENAI_PROJECT_ID': 'proj_devOnly',
                 'SERMON_OPENAI_CREDENTIAL_ALIAS': 'tongxing-dev-runtime', 'OPENAI_API_KEY': 'not-a-real-key'}
        clip = wav_bytes(3.0)
        cache = self.out / 'cache'
        # The binding names the selected OpenAI Project, so it exists only under the launcher.
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'openai_environment_launcher_required'):
            machine.budget_binding(self.source, self.anchor, ['u3'], self.out, model=machine.MODEL, effort=machine.EFFORT)
        with mock.patch.dict(os.environ, route):
            # Unbound: a call cap is not spending authorization. The refusal comes before any
            # transport exists and before either cache records a started call.
            unbound = machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=1)
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_required'):
                unbound.transcribe(clip)
            self.assertEqual(unbound.cache.uncertain(), [])
            judge = machine.SolAdjudicator(api_key='k', cache=cache)
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_required'):
                judge.decide('u3', {'schemaVersion': machine.QUESTION_SCHEMA, 'sourceUnitId': 'u3'})
            self.assertEqual(list(self.out.glob('**/*.started.json')), [])

            binding = machine.budget_binding(self.source, self.anchor, ['u3'], self.out, model=machine.MODEL, effort=machine.EFFORT)
            self.assertEqual(binding['doubtedUnits'], ['u3'])
            self.assertEqual(binding['budgetRoot'], str(self.out.resolve() / machine.BUDGET_DIR))
            self.assertEqual(binding['bindings'], {'source.json': policies.canonical_sha256(self.source),
                                                   'anchor.json': policies.canonical_sha256(self.anchor)})
            self.assertEqual(binding['route'], {'environment': 'dev', 'projectId': 'proj_devOnly',
                                                'credentialAlias': 'tongxing-dev-runtime'})
            self.assertEqual(binding['adjudicator'], {'model': machine.MODEL, 'reasoningEffort': machine.EFFORT})
            bounds = {'requests': 4, 'wallTimeMs': 4 * 300_000, 'costMicrousd': 2_000_000}
            auth_path = self._authorization('budget', binding, bounds)
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_binding_changed'):
                machine.load_budget_authorization(auth_path, binding={**binding, 'doubtedUnits': ['u3', 'u4']})
            # An approval that signed other bounds than the authority carries is not this authorization's.
            other = self._authorization('other', binding, bounds, approved_bounds=dict(bounds, costMicrousd=1))
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_approval_not_bound'):
                machine.load_budget_authorization(other, binding=binding)

            calls = []

            def transport(endpoint, request, content_type, api_key):
                calls.append((endpoint, api_key))
                if endpoint == transports.TRANSCRIBE_URL:
                    self.assertIn(b'name="prompt"', request)
                    return {'text': CLIP_HEARD_OTHER}
                payload = json.loads(request)
                self.assertEqual(payload['max_completion_tokens'], limits.DEFAULT_REQUEST_LIMITS['maxCompletionTokens'])
                return {'id': 'resp-1', 'model': machine.MODEL, 'choices': [{'finish_reason': 'stop', 'message': {
                    'content': json.dumps(answer('undetermined', note='The listeners disagree; keep the frozen text.'))}}]}
            budget = machine.load_budget_authorization(auth_path, binding=binding, transport=transport)
            # The approval pays for the adjudicator it names: another model or effort is another run.
            for model, effort in ((machine.MODEL, 'high'), ('gpt-6-astra', machine.EFFORT)):
                with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_binding_changed'):
                    machine.load_budget_authorization(auth_path, binding=machine.budget_binding(
                        self.source, self.anchor, ['u3'], self.out, model=model, effort=effort), transport=transport)
                with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_binding_changed'):
                    machine.SolAdjudicator(api_key='k', cache=cache, model=model, effort=effort, budget=budget)
            listener = machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=2, budget=budget)
            judge = machine.SolAdjudicator(api_key='k', cache=cache, budget=budget)
            receipt = machine.adjudicate(self.source, self.anchor, unit_ids=['u3'], media=None, listeners=[listener],
                                         adjudicator=judge, out_dir=self.out, cut=lambda *_: clip, budget=budget)
        row = receipt['units'][0]
        self.assertEqual((row['decision'], row['decidedBy'], row['heard'][0]['text']),
                         ('undetermined', 'model', CLIP_HEARD_OTHER))
        self.assertEqual(calls, [(transports.TRANSCRIBE_URL, 'not-a-real-key'), (machine.CHAT_URL, 'k')])
        # Every paid call went through the one ledger under the bound root, reserved before dispatch.
        ledger = json.loads((self.out / machine.BUDGET_DIR / 'source-budget.json').read_text(encoding='utf-8'))
        operations = sorted(ledger['requests'])
        self.assertEqual(operations[0], 'asr.0001')
        self.assertRegex(operations[1], r'judge\.[0-9a-f]{64}')
        self.assertEqual({row['status'] for row in ledger['requests'].values()}, {'returned'})
        self.assertEqual(ledger['requests']['asr.0001']['bounds'], {'requests': 1, 'wallTimeMs': 300_000, 'costMicrousd': 4500})
        self.assertGreater(ledger['requests'][operations[1]]['bounds']['costMicrousd'], 0)
        # Each ledger response names the model the transport accounts for (``identity['model']``), the route
        # and the request.
        saved = [json.loads(p.read_text(encoding='utf-8'))['requestIdentity']
                 for p in sorted((self.out / machine.BUDGET_DIR / 'responses').glob('*.json'))]
        self.assertEqual(sorted(row['model'] for row in saved), sorted([machine.MODEL, 'gpt-transcribe']))
        judge_row = next(row for row in saved if 'payload' in row)
        self.assertEqual((judge_row['route']['projectId'], judge_row['payload']['model']), ('proj_devOnly', machine.MODEL))
        self.assertEqual(json.loads(listener.operations.read_text(encoding='utf-8')),
                         {hashlib.sha256(clip).hexdigest(): 'asr.0001'})
        self.assertEqual(receipt['budget'], machine.budget_identity(budget))
        self.assertEqual(receipt['budget']['authorizationSha256'], hashlib.sha256(auth_path.read_bytes()).hexdigest())
        self.assertNotIn('store', receipt['budget'])
        self.assertEqual(receipt['adjudicator']['requestLimits'], limits.DEFAULT_REQUEST_LIMITS)
        machine.validate_receipt(receipt, source=self.source, anchor=self.anchor, cache=cache)
        # A v2 receipt always records its budget; dropping the record is refused. A v1 receipt was written
        # before the budget contract and carries none; a record that is not the authorization identity this
        # module writes is refused.
        self.assertEqual(receipt['schemaVersion'], machine.SCHEMA)
        stripped = {k: v for k, v in receipt.items() if k != 'budget'}
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_budget'):
            machine.validate_receipt(stripped, anchor=self.anchor, cache=cache)
        machine.validate_receipt(as_v1(receipt), anchor=self.anchor, cache=cache)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_budget'):
            machine.validate_receipt(dict(as_v1(receipt), budget=receipt['budget']), anchor=self.anchor, cache=cache)
        with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_budget'):
            machine.validate_receipt(dict(receipt, budget={'schemaVersion': machine.BUDGET_SCHEMA}), anchor=self.anchor, cache=cache)
        # Every recorded field is checked: a null or malformed hash, root, bound or tier is not the loader's record.
        for edited in ({'authorizationSha256': None}, {'approvalSha256': 'abc'}, {'budgetRoot': 'budget'},
                       {'budgetRoot': str(self.out.resolve())},
                       {'globalBounds': dict(receipt['budget']['globalBounds'], requests=0)}, {'globalBounds': {'requests': 1}},
                       {'requestLimits': dict(limits.DEFAULT_REQUEST_LIMITS, maxCompletionTokens=10**9)}, {'requestLimits': None}):
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'receipt_budget'):
                machine.validate_receipt(dict(receipt, budget={**receipt['budget'], **edited}), anchor=self.anchor, cache=cache)
        # The same run again replays both caches: no transport call, the same receipt rows.
        with mock.patch.dict(os.environ, route):
            again = machine.adjudicate(self.source, self.anchor, unit_ids=['u3'], media=None, adjudicator=machine.SolAdjudicator(
                api_key='k', cache=cache, budget=budget), out_dir=self.out, cut=lambda *_: clip, budget=budget,
                listeners=[machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=0, budget=budget)])
        self.assertEqual(len(calls), 2)
        self.assertEqual(again['units'][0]['heard'], receipt['units'][0]['heard'])
        self.assertTrue(again['units'][0]['request']['cached'])
        # A run that died after the ledger kept the listener's returned text but before its call cache recorded
        # the outcome leaves the cache's started marker. The resumed run binds the ledger's replay to that marker.
        listened = next((cache / 'openai').glob('*/started.json')).parent
        (listened / 'response.json').unlink()
        (listened / 'outcome.json').unlink()
        self.assertEqual(listener.cache.uncertain(), [listened.name])
        with mock.patch.dict(os.environ, route):
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_required'):
                machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=1).transcribe(clip)
            relistened = machine.adjudicate(self.source, self.anchor, unit_ids=['u3'], media=None, adjudicator=machine.SolAdjudicator(
                api_key='k', cache=cache, budget=budget), out_dir=self.out, cut=lambda *_: clip, budget=budget,
                listeners=[machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=0, budget=budget)])
            # The cap counts new paid requests only: a clip the ledger never saw is refused before anything is
            # numbered or reserved, while the replay above cost nothing under the same cap.
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'listener_call_cap_reached'):
                machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=0, budget=budget).transcribe(wav_bytes(1.0))
        self.assertEqual(len(calls), 2)
        self.assertEqual(listener.cache.uncertain(), [])
        self.assertEqual(json.loads(listener.operations.read_text(encoding='utf-8')),
                         {hashlib.sha256(clip).hexdigest(): 'asr.0001'})
        self.assertEqual(relistened['units'][0]['heard'], receipt['units'][0]['heard'])
        machine.validate_receipt(relistened, source=self.source, anchor=self.anchor, cache=cache)
        # A marker is bound only to the ledger's response for its own request; nothing recorded is overwritten.
        started_request = json.loads((listened / 'started.json').read_text(encoding='utf-8'))['request']
        with self.assertRaisesRegex(ValueError, 'started with another request'):
            listener.cache.reconcile(listened.name, {**started_request, 'audioSha256': 'other'}, {'text': 'x'})
        with self.assertRaisesRegex(ValueError, 'different response'):
            listener.cache.reconcile(listened.name, started_request, {'text': 'x'})
        # A run that died after the ledger kept Sol's response but before the cache file was written leaves the
        # cache's started marker. The resumed run binds the ledger's response into the cache without a new call.
        cache_file = Path(row['request']['path'])
        marker = cache_file.with_suffix('.started.json')
        marker.write_text(json.dumps({'requestSha256': row['request']['requestSha256'],
                                      'request': json.loads(cache_file.read_text(encoding='utf-8'))['request'],
                                      'status': 'started_response_unconfirmed'}), encoding='utf-8')
        cache_file.unlink()
        with mock.patch.dict(os.environ, route):
            resumed = machine.adjudicate(self.source, self.anchor, unit_ids=['u3'], media=None, adjudicator=machine.SolAdjudicator(
                api_key='k', cache=cache, budget=budget, max_calls=0), out_dir=self.out, cut=lambda *_: clip, budget=budget,
                listeners=[machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=0, budget=budget)])
        self.assertEqual(len(calls), 2)
        self.assertTrue(cache_file.is_file())
        self.assertFalse(marker.exists() and not cache_file.exists())
        self.assertEqual(resumed['units'][0]['decision'], 'undetermined')
        self.assertFalse(resumed['units'][0]['request']['cached'])
        machine.validate_receipt(resumed, source=self.source, anchor=self.anchor, cache=cache)
        # Without a budget the marker stays an unknown outcome: nothing is sent and the run stops.
        cache_file.unlink()
        marker.write_text(marker.read_text(encoding='utf-8'), encoding='utf-8')
        with mock.patch.dict(os.environ, route):
            with self.assertRaisesRegex(ValueError, 'Unknown L1 request outcome'):
                FakeAdjudicator(cache, answer('undetermined')).decide('u3', json.loads(
                    json.loads(marker.read_text(encoding='utf-8'))['request']['payload']['messages'][1]['content']))
        question = json.loads(json.loads(marker.read_text(encoding='utf-8'))['request']['payload']['messages'][1]['content'])
        # A started marker the ledger holds no response for may come from a run that sent the request directly,
        # before this ledger existed: its outcome is unknown, so it is refused rather than sent again, whatever
        # the cap allows, for Sol and the listener alike. Nothing is numbered or reserved and the marker stays.
        from scripts import english_source_judge_cache as judge_cache
        before = json.loads((self.out / machine.BUDGET_DIR / 'source-budget.json').read_text(encoding='utf-8'))
        with mock.patch.dict(os.environ, route):
            legacy = machine.SolAdjudicator(api_key='k', cache=cache, budget=budget, max_calls=5)
            asked = dict(question, askedBy='an earlier run')
            stage = f'source-meaning-{legacy.route_key}-u3'
            legacy_request = {'schemaVersion': judge_cache.RUN_SCHEMA, 'stage': stage, 'payload': legacy.payload(asked)}
            legacy_marker = cache.resolve() / 'cache' / f'{stage}-{contract.json_sha256(legacy_request)}.started.json'
            legacy_marker.write_text(json.dumps({'requestSha256': contract.json_sha256(legacy_request),
                                                 'request': legacy_request, 'status': 'started_response_unconfirmed'}),
                                     encoding='utf-8')
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'source_marker_outcome_unknown'):
                legacy.decide('u3', asked)
            fresh = wav_bytes(1.0)
            relisten = machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=1, budget=budget)
            key = policies.canonical_sha256({'listener': relisten.name, 'audioSha256': hashlib.sha256(fresh).hexdigest(),
                                             'identity': relisten.identity()})
            (cache / 'openai' / key).mkdir()
            (cache / 'openai' / key / 'started.json').write_text(json.dumps({'request': {
                'audioSha256': hashlib.sha256(fresh).hexdigest(), 'listener': relisten.name}}), encoding='utf-8')
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'source_marker_outcome_unknown'):
                relisten.transcribe(fresh)
        self.assertEqual(len(calls), 2)
        self.assertTrue(legacy_marker.is_file())
        self.assertEqual(relisten.cache.uncertain(), [key])
        self.assertEqual(json.loads(listener.operations.read_text(encoding='utf-8')),
                         {hashlib.sha256(clip).hexdigest(): 'asr.0001'})
        self.assertEqual(json.loads((self.out / machine.BUDGET_DIR / 'source-budget.json').read_text(encoding='utf-8')), before)
        legacy_marker.unlink()
        shutil.rmtree(cache / 'openai' / key)
        # The authorization binds the selected OpenAI Project: under prod the same file is another run's, and
        # the ledger row of a dev answer refuses a prod request before any replay or dispatch.
        prod = {**route, 'SERMON_OPENAI_ENVIRONMENT': 'prod', 'OPENAI_PROJECT_ID': 'proj_prodOnly',
                'SERMON_OPENAI_CREDENTIAL_ALIAS': 'tongxing-prod-runtime'}
        with mock.patch.dict(os.environ, prod):
            prod_binding = machine.budget_binding(self.source, self.anchor, ['u3'], self.out, model=machine.MODEL, effort=machine.EFFORT)
            self.assertEqual(prod_binding['route']['projectId'], 'proj_prodOnly')
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_binding_changed'):
                machine.load_budget_authorization(auth_path, binding=prod_binding, transport=transport)
            with self.assertRaisesRegex(ValueError, 'source_operation_identity_changed'):
                machine.SolAdjudicator(api_key='k', cache=cache, budget=budget).decide('u3', question)
        self.assertEqual(len(calls), 2)
        # The ledger re-reads the authorization, its approval and the code closure before every paid step:
        # a file replaced or code changed after the load refuses the reservation, and nothing is sent.
        approval_path = auth_path.parent / 'approval.json'
        original = {path: path.read_bytes() for path in (auth_path, approval_path)}
        widened, approval = json.loads(auth_path.read_text(encoding='utf-8')), json.loads(approval_path.read_text(encoding='utf-8'))
        for holder in (widened['authority'], approval['binding']):
            holder['globalBounds'] = dict(holder['globalBounds'], requests=40)
        approval_path.write_text(json.dumps(approval), encoding='utf-8')
        widened['authority']['approvalSha256'] = hashlib.sha256(approval_path.read_bytes()).hexdigest()
        auth_path.write_text(json.dumps(widened), encoding='utf-8')
        with mock.patch.dict(os.environ, route):
            with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_changed'):
                machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=1, budget=budget).transcribe(wav_bytes(1.0))
            for path, data in original.items():
                path.write_bytes(data)
            with mock.patch.object(controller, 'code_identity', return_value='f' * 64):
                with self.assertRaisesRegex(machine.SourceAdjudicationError, 'budget_authorization_binding_changed'):
                    machine.OpenAiTranscribeListener(cache=cache / 'openai', max_calls=1, budget=budget).transcribe(wav_bytes(1.0))
        self.assertEqual(len(calls), 2)
        ledger = json.loads((self.out / machine.BUDGET_DIR / 'source-budget.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(ledger['requests']), operations)
        # Exhausted bounds refuse before the transport is reached and leave nothing to reconcile.
        tight_out = self.root / 'tight'
        with mock.patch.dict(os.environ, route):
            tight_binding = machine.budget_binding(self.source, self.anchor, ['u3'], tight_out, model=machine.MODEL, effort=machine.EFFORT)
            tight = machine.load_budget_authorization(
                self._authorization('tight', tight_binding, dict(bounds, costMicrousd=1000)),
                binding=tight_binding, transport=transport)
            short = machine.OpenAiTranscribeListener(cache=tight_out / 'cache' / 'openai', max_calls=1, budget=tight)
            with self.assertRaisesRegex(ValueError, 'source_budget_exhausted'):
                short.transcribe(clip)
            # Sol reserves through the ledger before its cache writes a started marker, so a refused
            # reservation leaves no marker to reconcile either.
            with self.assertRaisesRegex(ValueError, 'source_budget_exhausted'):
                machine.SolAdjudicator(api_key='k', cache=tight_out / 'cache', budget=tight).decide('u3', question)
        self.assertEqual(len(calls), 2)
        self.assertEqual(short.cache.uncertain(), [])
        self.assertEqual(list(tight_out.glob('**/*.started.json')), [])
        # The CLI prints the binding an authorization must carry, without touching the output directory.
        fixture = self.root / 'fixture'
        fixture.mkdir()
        (fixture / 'source.json').write_text(json.dumps(self.source), encoding='utf-8')
        (fixture / 'anchor.json').write_text(json.dumps(self.anchor), encoding='utf-8')
        out = io.StringIO()
        with mock.patch.dict(os.environ, route), redirect_stdout(out):
            self.assertEqual(machine.main([str(fixture), '--media', str(self.media), '--unit', 'u3',
                                           '--out-dir', str(self.root / 'printed'), '--print-budget-binding']), 0)
            printed = machine.budget_binding(self.source, self.anchor, ['u3'], self.root / 'printed', model=machine.MODEL, effort=machine.EFFORT)
        self.assertEqual(json.loads(out.getvalue()), printed)
        self.assertEqual(printed['route']['environment'], 'dev')
        self.assertFalse((self.root / 'printed').exists())

    def _authorization(self, name, binding, bounds, approved_bounds=None):
        """An authorization and its approval receipt, shaped like the Layer 1 source budget's."""
        folder = self.root / name
        folder.mkdir()
        request_limits = dict(limits.DEFAULT_REQUEST_LIMITS)
        approval = {'schemaVersion': machine.BUDGET_APPROVAL_SCHEMA,
                    'binding': {**binding, 'globalBounds': approved_bounds or bounds, 'requestLimits': request_limits},
                    'humanApproval': True, 'decision': 'approved',
                    'operatorEvidence': 'test approval of the doubted-unit re-listen',
                    'reviewedBy': 'operator', 'reviewedAt': '2026-10-08T20:00:00+00:00'}
        (folder / 'approval.json').write_text(json.dumps(approval, indent=2), encoding='utf-8')
        authorization = {'schemaVersion': machine.BUDGET_SCHEMA, 'binding': binding,
                         'authority': {'approvalSha256': hashlib.sha256((folder / 'approval.json').read_bytes()).hexdigest(),
                                       'globalBounds': bounds, 'requestLimits': request_limits},
                         'approvalReceipt': 'approval.json'}
        (folder / 'authorization.json').write_text(json.dumps(authorization, indent=2), encoding='utf-8')
        return folder / 'authorization.json'


if __name__ == '__main__':
    unittest.main()
