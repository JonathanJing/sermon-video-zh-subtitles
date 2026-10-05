#!/usr/bin/env python3
"""Verify fixed-clip diagnostic audio and report timing/readback issues.

A completed model invocation is never a publication or human approval receipt.
"""
from __future__ import annotations
import argparse
import difflib
import json
from pathlib import Path
import subprocess
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.experiments import replay_fixed_clip_local_models as worker
from scripts.screen_target_language_audio_units import tokens


def assess_rows(groups, recognized, anchors, source_seconds, *, min_similarity=.88):
    worker.require(0 < min_similarity <= 1, 'invalid_similarity_threshold')
    ids=[f'fresh-g{i:03d}' for i in range(1,14)]
    worker.require([r.get('groupId') for r in groups] == ids and
                   [r.get('groupId') for r in recognized] == ids, 'diagnostic_group_coverage_changed')
    rows=[]
    for audio, readback in zip(groups, recognized):
        worker.require(audio['text'] == readback['expectedText'] and
                       audio['audioSha256'] == readback['audioSha256'], 'asr_audio_text_binding_changed')
        units=[anchors[sid] for sid in audio['sourceUnitIds']]
        span=units[-1]['end']-units[0]['start']
        similarity=difflib.SequenceMatcher(a=tokens(audio['text'],'zh-Hans'),
            b=tokens(readback['recognizedText'],'zh-Hans'),autojunk=False).ratio()
        rows.append({'groupId':audio['groupId'],'audioSeconds':audio['audioSeconds'],
            'sourceSpanSeconds':span,'sourceStart':units[0]['start'],'sourceEnd':units[-1]['end'],
            'exceedsSpanSeconds':max(0,audio['audioSeconds']-span),'similarity':similarity,
            'requiresReview':similarity<min_similarity,'expected':audio['text'],
            'recognized':readback['recognizedText']})
    total=sum(r['audioSeconds'] for r in rows)
    overlong=[r['groupId'] for r in rows if r['exceedsSpanSeconds']>.05]
    readback_issues=[r['groupId'] for r in rows if r['requiresReview']]
    blockers=['human_content_approval_missing','canonical_audio_and_sync_not_run']
    if total>source_seconds+.05: blockers.append('diagnostic_audio_exceeds_source_duration')
    if overlong: blockers.append('diagnostic_groups_exceed_source_windows')
    if readback_issues: blockers.append('diagnostic_asr_requires_review')
    return {'schemaVersion':'fixed-clip-local-model-assessment-v1',**worker.FLAGS,
        'status':'diagnostic_only_requires_review','publicationEligible':False,
        'publicationBlockers':blockers,'sourceSeconds':source_seconds,'audioSeconds':total,
        'exceedsSourceSeconds':max(0,total-source_seconds),'minSimilarity':min_similarity,
        'overlongGroups':overlong,'asrBelowThreshold':readback_issues,'groups':rows}


def assess(tts_dir, asr_dir, anchor_path, media, out):
    worker.require(worker.sha(media)==worker.MEDIA_SHA,'fixed_media_sha_changed')
    anchor=worker.read(anchor_path)
    worker.require(worker.digest(anchor)==worker.ANCHOR_SHA,'fixed_anchor_changed')
    tts_path=tts_dir/'manifest.json';asr_path=asr_dir/'manifest.json'
    tts=worker.read(tts_path);asr=worker.read(asr_path)
    worker.require(tts.get('status')==asr.get('status')=='completed_diagnostic' and
        all(m.get(k)==v for m in (tts,asr) for k,v in worker.FLAGS.items()) and
        tts.get('mediaSha256')==asr.get('mediaSha256')==worker.MEDIA_SHA and
        asr.get('ttsManifestSha256')==worker.sha(tts_path),'diagnostic_manifest_binding_changed')
    def duration(path):
        p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],
                         check=True,capture_output=True,text=True,timeout=30)
        return float(json.loads(p.stdout)['format']['duration'])
    source_seconds=duration(media)
    report=assess_rows(tts['groups'],asr['groups'],
        {u['sourceUnitId']:u for u in anchor['sourceUnits']},source_seconds)
    for audio in tts['groups']:
        path=worker.safe_audio(tts_dir,audio)
        worker.require(abs(duration(path)-audio['audioSeconds'])<.002,'audio_duration_receipt_changed')
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],
                       check=True,capture_output=True,timeout=120)
    report.update(fullDecodeGroups=len(tts['groups']),ttsManifestSha256=worker.sha(tts_path),
                  asrManifestSha256=worker.sha(asr_path),anchorSha256=worker.sha(anchor_path))
    worker.require(not out.exists(),'assessment_already_exists_use_new_output')
    out.parent.mkdir(parents=True,exist_ok=True);worker.save(out,report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('tts-dir','asr-dir','anchor','media','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=assess(a.tts_dir,a.asr_dir,a.anchor,a.media,a.out)
    print(json.dumps({k:v for k,v in r.items() if k!='groups'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
