import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from render_speaker_clip_demos import validate_scripts, validate_manifest
from build_speaker_clip_demos import build, encode_audio, checked_video_receipt, sha

class SpeakerClipsTests(unittest.TestCase):
    def setUp(self):
        self.s=json.loads((Path(__file__).resolve().parents[1]/'experiments/sermon-dubbing-poc/speaker-clip-demo-scripts-v2.json').read_text())
    def test_frozen_sources_and_translations_are_bound(self):
        validate_scripts(self.s)
        eric=next(x for x in self.s['speakers'] if x['speakerId']=='eric_geiger')
        self.assertEqual(eric['source']['startSeconds'],1148.4)
        self.assertEqual(eric['source']['archivedSourceVideoStartSeconds'],1751.2)
        self.assertEqual(eric['source']['endSeconds'],1161.36)
    def test_foreign_translation_rejected(self):
        s=copy.deepcopy(self.s);s['speakers'][0]['samples'][0]['sourceEnglishTextSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Cross-bound'):validate_scripts(s)
    def test_modified_transcript_rejected(self):
        s=copy.deepcopy(self.s);s['speakers'][0]['original']['text']='new words'
        with self.assertRaisesRegex(ValueError,'English hash'):validate_scripts(s)
    def test_incomplete_assets_cannot_be_published_catalog(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);report=build(self.s,p/'references',p/'renders',p/'videos',p/'out')
            self.assertEqual(report['status'],'incomplete')
            self.assertFalse((p/'out/catalog.json').exists())
            self.assertEqual(len(report['speakers']),6)

    def test_stale_encoded_audio_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);original=p/'source.wav';original.write_bytes(b'new wave')
            target=p/'sample.mp3';target.write_bytes(b'cached audio')
            target.with_suffix('.encoding.json').write_text(json.dumps({'sourceAudioSha256':'0'*64,'audioSha256':sha(target)}))
            with self.assertRaisesRegex(ValueError,'cache differs'):encode_audio(original,target,{})
    def test_video_cache_with_foreign_interval_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);speaker=self.s['speakers'][0];video=p/(speaker['speakerId']+'.mp4');video.write_bytes(b'video')
            source=copy.deepcopy(speaker['source']);source['startSeconds']+=1
            (p/(speaker['speakerId']+'-download.json')).write_text(json.dumps({'exitCode':0,'source':source,'sha256':sha(video)}))
            with self.assertRaisesRegex(ValueError,'interval differs'):checked_video_receipt(speaker,p)

    def test_completed_candidate_is_immutable(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);out=p/'out';out.mkdir();(out/'catalog.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'immutable'):build(self.s,p/'refs',p/'renders',p/'videos',out)
            self.assertEqual((out/'catalog.json').read_text(),'{}')

    def test_foreign_generation_manifest_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'identity differs'):
            validate_manifest({'registryJsonSha256':'0'*64}, {'schemaVersion':'registry'}, {'locales':[]})

if __name__=='__main__':unittest.main()
