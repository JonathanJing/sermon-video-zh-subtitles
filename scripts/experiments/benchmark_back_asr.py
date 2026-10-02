#!/usr/bin/env python3
"""Resident back-ASR batch timing and machine screening of diagnostic TTS waves.

This consumes warm-1 audio from each TTS condition; it produces no formal job,
approval, or release package. The API does not expose a termination reason.
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import statistics
import time

LANGUAGES={'zh-Hans':'Chinese','ko':'Korean','es':'Spanish'}
MODEL_REVISION='5eb144179a02acc5e5ba31e748d22b0cf3e303b0'

def validate_inputs(result, inputs, model_path):
 assert model_path.resolve().name==MODEL_REVISION, 'ASR model must use the pinned snapshot'
 assert (model_path/'config.json').is_file() and any(model_path.glob('*.safetensors')), 'Incomplete ASR snapshot'
 cases=inputs['cases']
 assert len(cases)==8 and len({r['caseId'] for r in cases})==8, 'Expected eight distinct frozen cases'
 expected={}
 for locale in LANGUAGES:
  assert sorted(r['lengthClass'] for r in cases if r['targetLocale']==locale and r['lengthClass'] in ('short','long'))==['long','short'], 'Expected exactly one short and one long case'
  ids=[r['caseId'] for r in cases if r['targetLocale']==locale and r['lengthClass'] in ('short','long')]
  assert len(ids)==2, 'Expected short and long case for each locale'
  for size in (1,2):expected[f'{locale}-b{size}']=ids
 for size in (4,8):expected[f'mixed-b{size}']=[r['caseId'] for r in cases]
 trials=[t for t in result['trials'] if t['repetition']=='warm-1']
 assert len(trials)==8 and {t['condition'] for t in trials}==set(expected), 'Missing or duplicate TTS condition'
 for trial in trials:
  assert [u['identity']['caseId'] for u in trial['units']]==expected[trial['condition']], 'Incomplete or reordered TTS condition'
 return trials

def sha(path):
 d=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):d.update(chunk)
 return d.hexdigest()

def save(path,value):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--tts-result',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True)
 p.add_argument('--model-path',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
 p.add_argument('--repeats',type=int,choices=[1,2,3],default=3)
 a=p.parse_args(); x=json.loads(a.tts_result.read_text());inputs=json.loads(a.inputs.read_text())
 assert x['status']=='complete_diagnostic' and x['inputManifestSha256']==sha(a.inputs)
 assert not a.out.exists(), 'Preserve prior attempts; use a new output directory'
 trials=validate_inputs(x,inputs,a.model_path)
 cases={r['caseId']:r for r in inputs['cases']}; requests=[]
 for trial in trials:
  for unit in trial['units']:
   case=cases[unit['identity']['caseId']];path=a.tts_result.parent/unit['audioPath']
   assert path.resolve().is_relative_to(a.tts_result.parent.resolve()) and sha(path)==unit['audioSha256']
   assert unit['identity']['textSha256']==case['textSha256'] and unit['sampleRate']==24000
   requests.append({'caseId':case['caseId'],'condition':trial['condition'],'locale':case['targetLocale'],
    'expected':case['text'],'audioPath':str(path),'audioSha256':unit['audioSha256'],
    'audioSeconds':unit['durationSeconds']})
 assert len(requests)==28 and len({(r['caseId'],r['condition']) for r in requests})==28
 a.out.mkdir(parents=True)
 report={'schemaVersion':'diagnostic-back-asr-performance-v1','status':'running','releaseEligible':False,
  'humanListening':'not_run','model':'Qwen/Qwen3-ASR-0.6B',
  'modelRevision':MODEL_REVISION,
  'ttsResultSha256':sha(a.tts_result),'inputManifestSha256':sha(a.inputs),'requests':requests,
  'benchmarkSha256':sha(__file__),'trials':[],'termination':'API return and coverage only; no EOS claim'}
 save(a.out/'started.json',report)
 started=time.perf_counter()
 report['modelFilesSha256']={str(f.relative_to(a.model_path)):sha(f) for f in sorted(a.model_path.rglob('*')) if f.is_file()}
 report['modelHashSeconds']=time.perf_counter()-started
 started=time.perf_counter()
 import torch,soundfile as sf
 from qwen_asr import Qwen3ASRModel
 from scripts.screen_target_language_audio_units import tokens
 report['runtimeImportSeconds']=time.perf_counter()-started
 assert torch.cuda.is_available(),'CUDA required; no CPU fallback'
 report['torchVersion']=torch.__version__
 started=time.perf_counter()
 model=Qwen3ASRModel.from_pretrained(str(a.model_path),dtype=torch.bfloat16,device_map='cuda:0',
  max_inference_batch_size=8,max_new_tokens=2048)
 torch.cuda.synchronize();report['modelLoadSeconds']=time.perf_counter()-started
 started=time.perf_counter();audio=[sf.read(row['audioPath'],dtype='float32') for row in requests]
 assert all(w.ndim==1 and sr==24000 for w,sr in audio)
 report['inputDecodeSeconds']=time.perf_counter()-started
 for size in [1,4,8]:
  for repeat in range(a.repeats+1):
   trial={'batchSize':size,'repetition':'warmup' if repeat==0 else f'warm-{repeat}',
    'rows':[],'inferenceSeconds':0.0};torch.cuda.reset_peak_memory_stats();trial_start=time.perf_counter()
   for index in range(0,len(requests),size):
    selected=requests[index:index+size];torch.cuda.synchronize();begin=time.perf_counter()
    values=model.transcribe(audio=audio[index:index+size],language=[LANGUAGES[r['locale']] for r in selected])
    torch.cuda.synchronize();trial['inferenceSeconds']+=time.perf_counter()-begin
    assert len(values)==len(selected),'ASR output cardinality differs'
    for request,value in zip(selected,values):
     assert isinstance(value.text,str),'ASR did not return text'
     expected,actual=tokens(request['expected'],request['locale']),tokens(value.text,request['locale'])
     score=difflib.SequenceMatcher(None,expected,actual,autojunk=False).ratio()
     passed=score>=.88 and (len(expected)>=4 or expected==actual)
     trial['rows'].append({'caseId':request['caseId'],'condition':request['condition'],
      'recognized':value.text,'similarity':score,'status':'pass' if passed else 'requires_review',
      'audioSha256':request['audioSha256']})
   assert len(trial['rows'])==len(requests)
   assert all(sha(r['audioPath'])==r['audioSha256'] for r in requests),'Frozen audio changed'
   trial['wallSeconds']=time.perf_counter()-trial_start
   trial['audioSeconds']=sum(r['audioSeconds'] for r in requests)
   trial['rtf']=trial['inferenceSeconds']/trial['audioSeconds']
   trial['cudaPeakAllocatedBytes']=torch.cuda.max_memory_allocated()
   report['trials'].append(trial);save(a.out/'result.partial.json',report)
   print(json.dumps({'batchSize':size,'repetition':trial['repetition'],'inferenceSeconds':trial['inferenceSeconds'],
    'requiresReview':sum(r['status']=='requires_review' for r in trial['rows'])}),flush=True)
 report['summary']={str(size):{'medianInferenceSeconds':statistics.median(t['inferenceSeconds'] for t in report['trials'] if t['batchSize']==size and t['repetition']!='warmup'),
  'medianRTF':statistics.median(t['rtf'] for t in report['trials'] if t['batchSize']==size and t['repetition']!='warmup')}
  for size in [1,4,8]}
 report['status']='complete_diagnostic';save(a.out/'result.json',report)

if __name__=='__main__':main()
