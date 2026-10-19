#!/usr/bin/env python3
"""Build complete matched-clip candidates; partial assets never become public v2."""
import argparse
import array
import math
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from render_speaker_clip_demos import validate_scripts

PREFIX = '/voice-demos/speaker-clips-v2/'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576), b''): h.update(b)
    return h.hexdigest()


def probe(path):
    d=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name','-of','json',str(path)]))
    return float(d['format']['duration']), {x['codec_type'] for x in d['streams']}


def record(path, out, speaker):
    duration, _=probe(path)
    return {'path': PREFIX+str(path.relative_to(out)), 'sha256':sha(path), 'bytes':path.stat().st_size,
            'durationSeconds':duration, 'sourceClipId':speaker['clipId']}


def audio_correspondence(original, video):
    """RMS shape check catches wrong source timelines; it is machine evidence only."""
    def envelope(path):
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vn','-ar','2000','-ac','1','-f','s16le','-'])
        pcm=array.array('h');pcm.frombytes(raw)
        return [math.sqrt(sum(x*x for x in pcm[i:i+80])/len(pcm[i:i+80])) for i in range(0,len(pcm),80)]
    def pearson(a,b):
        n=min(len(a),len(b));a=a[:n];b=b[:n]
        if n<20:return 0.0
        ma=sum(a)/n;mb=sum(b)/n
        denominator=math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
        return sum((x-ma)*(y-mb) for x,y in zip(a,b))/denominator if denominator else 0.0
    a=envelope(original);b=envelope(video)
    score,offset=max((pearson(a[max(0,i):],b[max(0,-i):]),i*.04) for i in range(-5,6))
    return {'method':'mono_2khz_40ms_rms_pearson_offset_200ms','correlation':score,
            'bestOffsetSeconds':offset,'status':'machine_correspondence_pass' if score>=.75 else 'requires_review'}


def encode_audio(source, target, binding):
    receipt_path=target.with_suffix('.encoding.json')
    expected={'sourceAudioSha256':sha(source),**binding}
    if target.exists():
        if not receipt_path.exists():raise ValueError('Encoded audio cache has no binding receipt')
        receipt=json.loads(receipt_path.read_text())
        if any(receipt.get(k)!=v for k,v in expected.items()) or receipt.get('audioSha256')!=sha(target):
            raise ValueError('Encoded audio cache differs from current source')
    else:
        subprocess.run(['ffmpeg','-v','error','-n','-i',str(source),'-ar','44100','-ac','1','-b:a','128k',str(target)],check=True)
        subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],check=True)
        receipt_path.write_text(json.dumps({**expected,'audioSha256':sha(target),'fullDecode':'pass'},indent=2)+'\n')
    return target


def checked_video_receipt(speaker, videos):
    receipt_path=videos/(speaker['speakerId']+'-download.json')
    if not receipt_path.exists():raise ValueError('Downloaded video has no source receipt')
    receipt=json.loads(receipt_path.read_text());source=speaker['source']
    if receipt.get('exitCode')!=0 or any(receipt.get('source',{}).get(k)!=source[k] for k in ['url','startSeconds','endSeconds']):
        raise ValueError('Video cache source interval differs')
    path=videos/(speaker['speakerId']+'.mp4')
    if receipt.get('sha256')!=sha(path):raise ValueError('Video cache hash differs')
    return receipt


def build(scripts, references, renders, videos, out):
    validate_scripts(scripts)
    if (out/'catalog.json').exists():raise ValueError('Completed candidate is immutable; use a new output directory')
    out.mkdir(parents=True,exist_ok=True)
    report={'schemaVersion':'sermon-speaker-clip-demo-preparation-v2','status':'incomplete','speakers':[]}
    speakers=[]
    for s in scripts['speakers']:
        sid=s['speakerId']; dest=out/sid;dest.mkdir(exist_ok=True); missing=[]
        original=references/(sid+'.wav'); video=videos/(sid+'.mp4')
        entry={'speakerId':sid,'displayName':s['displayName'],'clipId':s['clipId'],'source':s['source'],'samples':[]}
        if original.is_file():
            if sha(original)!=s['original']['referenceAudioSha256']:raise ValueError('Original reference hash differs')
            target=dest/'en-original.mp3'; encode_audio(original,target,{'sourceClipId':s['clipId'],'englishTextSha256':s['source']['englishTextSha256']})
            entry['original']={**record(target,out,s),**s['original'],'sha256':sha(target),'locale':'en','englishTextSha256':s['source']['englishTextSha256'],'fullDecode':'pass'}
        else:missing.append('original')
        if video.is_file():
            checked_video_receipt(s,videos)
            subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],check=True)
            dur,kinds=probe(video)
            if 'video' not in kinds or abs(dur-(s['source']['endSeconds']-s['source']['startSeconds']))>.5:
                raise ValueError('Video stream or interval differs: '+sid)
            target=dest/'en-video.mp4';shutil.copyfile(video,target);entry['video']=record(target,out,s)
            if original.is_file():
                check=audio_correspondence(original,video);entry['video']['audioCorrespondence']=check
                if check['status']!='machine_correspondence_pass':missing.append('video_source_correspondence')
            if 'original' in entry and abs(entry['original']['durationSeconds']-dur)>.5:
                raise ValueError('Original and video duration differs: '+sid)
        else:missing.append('video')
        for x in s['samples']:
            wav=renders/sid/'audio'/sid/(x['locale']+'.wav');receipt=wav.with_suffix('.json')
            if not wav.is_file() or not receipt.is_file():missing.append(x['locale']);continue
            r=json.loads(receipt.read_text())
            if r['audioSha256']!=sha(wav) or r['textSha256']!=x['textSha256'] or r['speakerId']!=sid or r['targetLocale']!=x['locale']:raise ValueError('Generated audio binding differs')
            mp3=dest/(x['locale']+'.mp3')
            encode_audio(wav,mp3,{'sourceClipId':s['clipId'],'englishTextSha256':s['source']['englishTextSha256'],'textSha256':x['textSha256'],'generationReceiptSha256':sha(receipt)})
            subprocess.run(['ffmpeg','-v','error','-i',str(mp3),'-f','null','-'],check=True)
            entry['samples'].append({**record(mp3,out,s),**x,'englishTextSha256':s['source']['englishTextSha256'],
                'humanListeningStatus':'pending','generationReceiptSha256':sha(receipt),'checkpointSha256':r['checkpointSha256'],'fullDecode':'pass'})
        report['speakers'].append({'speakerId':sid,'missing':missing,'availableAssets':entry})
        if not missing:speakers.append(entry)
    if len(speakers)==6:
        catalog={'schemaVersion':'sermon-speaker-clip-demo-catalog-v2','status':'audition_demo',
            'sourceScope':'source_clip_translation_audition_not_sermon_release','humanListeningStatus':'pending',
            'speakerCount':6,'sampleCount':18,'speakers':speakers,
            'machineScreeningStatus':'audio_asr_not_run','translationReviewStatus':'machine_candidate_human_review_pending'}
        (out/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n');report['status']='complete_candidate_not_deployed'
    (out/'preparation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def download_video(speaker, videos):
    videos.mkdir(parents=True,exist_ok=True)
    target=videos/(speaker['speakerId']+'.mp4')
    if target.exists():
        checked_video_receipt(speaker,videos); return target
    source=speaker['source']
    command=['yt-dlp','--no-playlist','--socket-timeout','15','--retries','1',
        '--download-sections',f"*{source['startSeconds']}-{source['endSeconds']}",
        '--force-keyframes-at-cuts','-f','best[height<=480][ext=mp4]/bestvideo[height<=480]+bestaudio',
        '--merge-output-format','mp4','-o',str(target),source['url']]
    with (videos/(speaker['speakerId']+'-download.log')).open('w') as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    receipt={'source':source,'command':command,'exitCode':result.returncode,
             'ytDlpVersion':subprocess.check_output(['yt-dlp','--version'],text=True).strip()}
    if result.returncode==0 and target.exists():
        duration,kinds=probe(target);receipt.update(sha256=sha(target),durationSeconds=duration,streams=sorted(kinds))
    (videos/(speaker['speakerId']+'-download.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    return target


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['scripts','references','renders','videos','out']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--download-videos',action='store_true')
    a=p.parse_args()
    if a.download_videos:
        for s in json.loads(a.scripts.read_text())['speakers']:download_video(s,a.videos)
    report=build(json.loads(a.scripts.read_text()),a.references,a.renders,a.videos,a.out)
    print(json.dumps({'status':report['status'],'missing':{x['speakerId']:x['missing'] for x in report['speakers']}}))

if __name__=='__main__':main()
