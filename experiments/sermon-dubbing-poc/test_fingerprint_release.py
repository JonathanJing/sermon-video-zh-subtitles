"""Source/track-bound non-audio fingerprint publication regressions."""
import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from deploy_firebase import verify_release, FINGERPRINT_UI
import weekly_release as release
from test_weekly_release import release_fixture, refresh_manifest, week, write_json, ORIGIN

class FingerprintReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        p,a=week('2026-09-13','source'); p.update(id='2026-09-13-same_video-source-'+'a'*16,sourceRoute='same_video',sourceId='source-'+'a'*16,sourceStartSeconds=1793,sourceEndSeconds=1795)
        self.index=dict(schemaVersion='sermon-landmark-index-v1',algorithmVersion='spectral-landmarks-v1',sampleRate=8000,hopSize=256,fftSize=1024,sourceSha256='a'*64,trackSha256=p['tracks'][0]['sha256'],pageId=p['id'],sourceStartSeconds=1793,sourceEndSeconds=1795,window={'startSeconds':1793,'endSeconds':1795},durationSeconds=2,landmarkCount=3,postings={'123':[1,4,8]})
        self.p=p;self.a=a;self.path=release_fixture(self.root/'candidate',[(p,a)]);self.write_index(self.index)
        for f in FINGERPRINT_UI: (self.path/'public'/f).write_text('// inert test runtime')
        refresh_manifest(self.path)
    def write_index(self,index):
        public=self.path/'public';(public/'fingerprints').mkdir(exist_ok=True)
        for f in (public/'fingerprints').glob('*'):f.unlink()
        data=json.dumps(index).encode();h=hashlib.sha256(data).hexdigest();name='fingerprints/'+h[:16]+'-landmarks.json';(public/name).write_bytes(data)
        b={k:index[k] for k in ['algorithmVersion','sourceSha256','trackSha256','pageId','sourceStartSeconds','sourceEndSeconds']};b.update(schemaVersion='sermon-audio-fingerprint-binding-v1',captureSeconds=10,indexUrl='/'+name,indexSha256=h)
        cat=json.loads((public/'weekly.json').read_text());cat['weeks'][0]['audioFingerprint']=b;write_json(public/'weekly.json',cat);refresh_manifest(self.path)
    def reject(self):
        for fn in (verify_release,release.read_release):
            with self.subTest(fn=fn.__name__),self.assertRaises(ValueError):fn(self.path)
    def test_valid_and_future_merge_preserves_index(self):
        release.read_release(self.path);old=week('2026-09-06','old');base=release_fixture(self.root/'base',[old])
        for f in FINGERPRINT_UI:(base/'public'/f).write_text('// established runtime')
        refresh_manifest(base);reg=self.root/'registry';release.bootstrap(reg,base,ORIGIN);release.prepare(reg,self.path,self.root/'merged')
        _,cat=release.read_release(self.root/'merged');new=next(w for w in cat['weeks'] if w['id']==self.p['id']);self.assertTrue((self.root/'merged/public'/new['audioFingerprint']['indexUrl'][1:]).is_file())
    def test_wrong_source_track_window_and_page_rejected_even_rehashed(self):
        for k,v in [('sourceSha256','b'*64),('trackSha256','b'*64),('pageId','wrong'),('sourceStartSeconds',1792),('sourceEndSeconds',1796)]:
            with self.subTest(field=k):
                index=copy.deepcopy(self.index);index[k]=v;self.write_index(index);self.reject()
    def test_no_raw_audio_or_private_extra_fields(self):
        x=copy.deepcopy(self.index);x['rawAudio']='private base64';self.write_index(x);self.reject()
    def test_only_numeric_ordered_postings(self):
        for times in [['raw'],[3,2],[1,1],[-1],[1000],[True],[]]:
            with self.subTest(times=times):
                x=copy.deepcopy(self.index);x['postings']['123']=times;self.write_index(x);self.reject()
    def test_external_or_unbound_index_rejected(self):
        q=self.path/'public/weekly.json';cat=json.loads(q.read_text());cat['weeks'][0]['audioFingerprint']['indexUrl']='https://example.com/secret.json';write_json(q,cat);refresh_manifest(self.path);self.reject()
        self.write_index(self.index);cat=json.loads(q.read_text());del cat['weeks'][0]['audioFingerprint'];write_json(q,cat);refresh_manifest(self.path);self.reject()
    def test_tampered_and_missing_runtime_rejected(self):
        p=next((self.path/'public/fingerprints').glob('*'));p.write_text('{}');self.reject()
        self.write_index(self.index);(self.path/'public/fingerprint-worker.mjs').unlink();refresh_manifest(self.path);self.reject()

    def test_direct_deploy_rejects_unsupported_catalog_schema(self):
        path = self.path/'public/weekly.json'
        catalog = json.loads(path.read_text())
        for schema in ('unsupported-v99', None):
            with self.subTest(schema=schema):
                catalog['schemaVersion'] = schema
                write_json(path, catalog)
                refresh_manifest(self.path)
                with self.assertRaisesRegex(ValueError, 'catalog schema'):
                    verify_release(self.path)

    def test_direct_deploy_rebinds_track_path_url_and_manifest(self):
        path = self.path/'public/weekly.json'
        original = json.loads(path.read_text())
        for change in ('missing', 'url', 'manifest_hash', 'manifest_bytes', 'empty', 'symlink'):
            with self.subTest(change=change):
                catalog = copy.deepcopy(original)
                track = catalog['weeks'][0]['tracks'][0]
                audio = self.path/'public/media'/track['file']
                content = audio.read_bytes()
                try:
                    if change == 'missing':
                        track['file'] = track['sha256'][:16] + '-missing.mp3'
                        track['audioUrl'] = '/media/' + track['file']
                    elif change == 'url':
                        track['audioUrl'] = '/media/missing.mp3'
                    elif change == 'empty':
                        audio.write_bytes(b'')
                    elif change == 'symlink':
                        target = self.root/'outside.mp3'
                        target.write_bytes(content)
                        audio.unlink()
                        audio.symlink_to(target)
                    write_json(path, catalog)
                    refresh_manifest(self.path)
                    if change in ('manifest_hash', 'manifest_bytes'):
                        report_path = self.path/'build-report.json'
                        report = json.loads(report_path.read_text())
                        item = next(f for f in report['files'] if f['path'] == 'media/' + track['file'])
                        item['sha256' if change == 'manifest_hash' else 'bytes'] = 'b'*64 if change == 'manifest_hash' else 0
                        write_json(report_path, report)
                    with self.assertRaisesRegex(ValueError, 'Fingerprint track'):
                        verify_release(self.path)
                finally:
                    if audio.is_symlink():
                        audio.unlink()
                    audio.write_bytes(content)
                    write_json(path, original)
                    refresh_manifest(self.path)
        verify_release(self.path)

if __name__=='__main__':unittest.main()
