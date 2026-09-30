"""Offline byte fixtures only: no source files, subprocess, transport or models."""
import hashlib
import io
import json
import struct
import unittest
import wave
from email import policy
from email.parser import BytesParser

from scripts import sermon_transcription_request as subject


def wav(frames=1600, rate=16000, channels=1, width=2):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(channels); stream.setsampwidth(width); stream.setframerate(rate)
        stream.writeframes(bytes(frames*channels*width))
    return output.getvalue()


def build(raw):
    return subject.build_request(raw, hashlib.sha256(raw).hexdigest())


def riff_size(raw):
    value = bytearray(raw); struct.pack_into('<I', value, 4, len(value)-8)
    return bytes(value)


class TranscriptionRequestTests(unittest.TestCase):
    def test_actual_pcm_count_and_deterministic_multipart_bind_exact_bytes(self):
        raw = wav(); value = build(raw)
        self.assertEqual(value, build(raw))
        self.assertEqual(value['identity']['model'], 'gpt-transcribe')
        self.assertEqual(value['identity']['inputDurationSeconds'], .1)
        self.assertEqual(value['identity']['audio']['decodedFrameCount'], 1600)
        self.assertEqual(value['identity']['audio']['decodedDurationSeconds'], .1)
        self.assertEqual(value['identity']['audio']['sampleRateHz'], 16000)
        self.assertEqual(value['identity']['audio']['byteCount'], len(raw))
        self.assertEqual(value['identity']['requestBodySha256'], hashlib.sha256(value['body']).hexdigest())
        digest = hashlib.sha256(json.dumps(value['identity'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(value['identitySha256'], digest)
        parsed = BytesParser(policy=policy.default).parsebytes(
            ('Content-Type: '+value['contentType']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+value['body'])
        parts = list(parsed.iter_parts())
        self.assertEqual([p.get_param('name', header='Content-Disposition') for p in parts],
                         ['model','language','response_format','file'])
        self.assertEqual([p.get_payload(decode=True) for p in parts[:3]], [b'gpt-transcribe',b'en',b'json'])
        self.assertEqual(parts[-1].get_filename(), 'clip.wav')
        self.assertEqual(parts[-1].get_payload(decode=True), raw)
        self.assertEqual(parts[-1].get_content_type(), 'audio/wav')
        self.assertNotIn('prompt', value['identity']['api'])

    def test_audio_only_budget_uses_whole_minute_ceiling_and_no_token_zeros(self):
        for frames, minutes in ((1,1),(60*16000,1),(60*16000+1,2),(180*16000,3)):
            with self.subTest(frames=frames):
                value = build(wav(frames=frames))
                self.assertEqual(value['reservedBillableMinutes'], minutes)
                self.assertEqual(value['budgetBounds'], {'requests':1,'wallTimeMs':300000,'costMicrousd':minutes*4500})
                self.assertEqual(value['responseMaxBytes'],204800)
                self.assertIsNone(value['tokenUsage']['inputTokens'])
                self.assertIsNone(value['tokenUsage']['outputTokens'])
                self.assertIsNone(value['tokenUsage']['cachedInputTokens'])
        self.assertEqual(build(wav(frames=180*16000))['budgetBounds']['costMicrousd'], 13500)

    def test_more_than_180_seconds_rejects_one_extra_decoded_frame(self):
        with self.assertRaisesRegex(ValueError,'duration_exceeded'):
            build(wav(frames=180*16000+1))

    def test_stereo_frame_count_is_not_sample_count_or_declared_duration(self):
        raw = wav(frames=800,rate=8000,channels=2,width=3)
        value = build(raw)
        self.assertEqual(value['identity']['audio']['channels'],2)
        self.assertEqual(value['identity']['audio']['sampleWidthBytes'],3)
        self.assertEqual(value['identity']['audio']['decodedFrameCount'],800)
        self.assertEqual(value['identity']['audio']['decodedDurationSeconds'],.1)

    def test_max_25_mib_is_full_file_size_including_chunks(self):
        # Large harmless RIFF JUNK metadata still counts against upload size.
        base = wav(); padding = subject.MAX_AUDIO_BYTES-len(base)-8
        at_limit = riff_size(base+b'JUNK'+struct.pack('<I',padding)+bytes(padding))
        self.assertEqual(len(at_limit),subject.MAX_AUDIO_BYTES)
        self.assertEqual(build(at_limit)['identity']['audio']['byteCount'],subject.MAX_AUDIO_BYTES)
        with self.assertRaisesRegex(ValueError,'size_invalid'):
            build(riff_size(at_limit+b'xx'))

    def test_wrong_hash_or_nonbytes_input_is_never_accepted(self):
        raw = wav()
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):
            subject.build_request(raw,'0'*64)
        for digest in (None, 'A'*64, 'a'*63, 'a'*64+'\n', True):
            with self.assertRaises(ValueError): subject.build_request(raw,digest)
        for invalid in (bytearray(raw), None, 'wav', b''):
            with self.assertRaises(ValueError): subject.build_request(invalid,'0'*64)

    def test_truncated_data_cannot_pass_by_rewriting_only_riff_size(self):
        raw = wav()
        for changed in (raw[:-1], riff_size(raw[:-2]), riff_size(raw[:44])):
            with self.subTest(length=len(changed)), self.assertRaises(ValueError): build(changed)

    def test_extra_frames_or_unparsed_trailing_bytes_are_rejected(self):
        raw = wav()
        for changed in (raw+b'\0\0',riff_size(raw+b'\0\0'),riff_size(raw+b'data'+struct.pack('<I',2)+b'\0\0')):
            with self.assertRaises(ValueError): build(changed)
        # Shrinking only declared data leaves unexplained frame bytes.
        changed = bytearray(raw); struct.pack_into('<I',changed,40,len(raw)-46)
        with self.assertRaises(ValueError): build(bytes(changed))

    def test_pcm_format_and_byte_rate_are_coherent(self):
        raw = wav()
        for offset, pattern, value in ((20,'<H',3),(20,'<H',0xfffe),(22,'<H',0),(24,'<I',0),
                                       (28,'<I',1),(32,'<H',1),(34,'<H',12)):
            changed = bytearray(raw); struct.pack_into(pattern,changed,offset,value)
            with self.subTest(offset=offset,value=value), self.assertRaises(ValueError): build(bytes(changed))

    def test_partial_frames_empty_audio_and_inconsistent_fact_are_rejected(self):
        with self.assertRaises(ValueError): build(wav(frames=0))
        raw = bytearray(wav()); raw.pop(); struct.pack_into('<I',raw,40,len(raw)-44)
        with self.assertRaises(ValueError): build(riff_size(raw))
        raw = wav()+b'fact'+struct.pack('<II',4,1599)
        with self.assertRaisesRegex(ValueError,'frame_fact_mismatch'): build(riff_size(raw))
        valid = wav()+b'fact'+struct.pack('<II',4,1600)
        self.assertEqual(build(riff_size(valid))['identity']['audio']['decodedFrameCount'],1600)

    def test_duplicate_fmt_and_riff_length_mismatch_are_rejected(self):
        raw = wav()
        with self.assertRaises(ValueError): build(riff_size(raw+raw[12:36]))
        changed = bytearray(raw); struct.pack_into('<I',changed,4,len(raw))
        with self.assertRaisesRegex(ValueError,'riff_size_mismatch'): build(bytes(changed))
        changed = bytearray(raw); changed[:4]=b'RF64'
        with self.assertRaisesRegex(ValueError,'requires_pcm_wav'): build(bytes(changed))

    def test_absent_provider_duration_remains_unknown_despite_known_input(self):
        value = subject.usage_cost_evidence({'text':'private synthetic transcript'},180)
        self.assertEqual(value['inputAudioDurationSeconds'],180)
        self.assertEqual(value['inputDurationReservationCostMicrousd'],13500)
        self.assertEqual(value['inputDurationEstimatedCostMicrousd'],13500)
        self.assertIsNone(value['providerAudioDurationSeconds'])
        self.assertIsNone(value['costMicrousd'])
        self.assertEqual(value['costStatus'],'unknown')
        self.assertEqual(value['providerDurationStatus'],'not_reported')
        self.assertFalse(value['invoiceVerified'])
        self.assertNotIn('private synthetic transcript',json.dumps(value))
        self.assertIsNone(value['inputTokens']);self.assertIsNone(value['outputTokens'])
        self.assertEqual(value['priceSource'],'https://developers.openai.com/api/docs/models/gpt-transcribe')

    def test_reported_provider_duration_priced_separately_and_not_an_invoice(self):
        for response in ({'duration':60.000001},{'usage':{'type':'duration','seconds':60.000001}},
                         {'duration':60.000001,'usage':{'type':'duration','seconds':60.000001}}):
            value=subject.usage_cost_evidence(response,60)
            self.assertEqual(value['providerAudioDurationSeconds'],60.000001)
            self.assertEqual(value['costMicrousd'],4501)
            self.assertEqual(value['inputDurationEstimatedCostMicrousd'],4500)
            self.assertEqual(value['costStatus'],'estimated_from_provider_duration')
            self.assertFalse(value['invoiceVerified'])

    def test_missing_invalid_or_conflicting_provider_duration_is_not_zero(self):
        for response in (None, [], {'model':'whisper-1','duration':1}, {'duration':None}, {'duration':0},
                         {'duration':-1}, {'duration':True}, {'duration':'1'}, {'duration':float('nan')},
                         {'duration':float('inf')}, {'duration':10**1000},
                         {'usage':{'type':'duration'}},
                         {'duration':1,'usage':{'type':'duration','seconds':2}}):
            with self.subTest(response=response):
                value=subject.usage_cost_evidence(response,1)
                self.assertIsNone(value['providerAudioDurationSeconds']);self.assertIsNone(value['costMicrousd'])
        value=subject.usage_cost_evidence({'duration':1,'usage':{'type':'duration','seconds':2}},1)
        self.assertEqual(value['providerDurationStatus'],'conflicting_reported_duration')

    def test_invalid_input_duration_is_rejected_not_replaced_by_provider_duration(self):
        for value in (None,True,'1',0,-1,180.0001,float('nan'),float('inf'),10**1000):
            with self.subTest(value=value),self.assertRaises(ValueError):
                subject.usage_cost_evidence({'duration':1},value)


if __name__ == '__main__': unittest.main()
