"""Read-only scoring and listening view for acoustic ablations."""
import html
import json
from acoustic_trial import OUT, ROOT

def main():
    cases={}
    blocks=[]
    for clip in ['A','B']:
        aligned=json.loads((ROOT/'artifacts/local-prosody-poc/20260919/alignment'/(clip+'.json')).read_text())['words']
        for condition in ['text','gap','acoustic']:
            name=clip+'-'+condition;p=OUT/(name+'.json')
            if not p.exists():continue
            d=json.loads(p.read_text());a=d['analysis'] or {};boundaries=a.get('boundaries',[])
            cases[name]={'errors':d['validation_errors'],'sentence_boundaries':[b['after_word'] for b in boundaries if b['kind']=='sentence'],'phrase_boundaries':[b['after_word'] for b in boundaries if b['kind']=='phrase'],'emphasis':a.get('emphasis',[]),'latency_seconds':d['latency_seconds']}
            if condition=='acoustic':
                measured=json.loads((OUT/'features'/(clip+'.json')).read_text())['words']
                cases[name]['emphasis_measurements']=[{'word_index':b['word_index'],'word':d['words'][b['word_index']],**{k:measured[b['word_index']][k] for k in ['voiced_frame_count','voiced_fraction','relative_pitch_semitones','relative_rms_db','duration_relative_local_median']}} for b in a.get('emphasis',[]) if 0<=b['word_index']<len(measured)]
            mapping={b['after_word']:b for b in boundaries};emphasis={b['word_index'] for b in a.get('emphasis',[])}
            tokens=[]
            for i,w in enumerate(d['words']):
                text=html.escape(w);b=mapping.get(i)
                if i in emphasis:text='<strong>'+text+'</strong>'
                tooltip='word '+str(i)+'; estimated start '+str(aligned[i]['start'])+'s'
                if condition=='acoustic':tooltip+='; '+json.dumps({k:measured[i][k] for k in ['voiced_frame_count','voiced_fraction','f0_slope_semitones','relative_pitch_semitones','relative_rms_db','duration_relative_local_median']},ensure_ascii=False)
                tokens.append('<span title="'+html.escape(tooltip,quote=True)+'" onclick="let a=document.getElementById(\''+name+'\');a.currentTime='+str(aligned[i]['start'])+';a.play()">'+text+'</span>')
                if b:tokens.append('<mark title="'+html.escape(b['evidence'],quote=True)+'">'+(' ● ' if b['kind']=='sentence' else ' | ')+'</mark>')
            blocks.append('<section><h2>'+name+'</h2><p>'+html.escape(str(d['validation_errors']) or '')+'</p><audio id="'+name+'" controls src="../../gemini-prosody-poc/20260917/'+clip+'.wav"></audio><p>'+ ' '.join(tokens)+'</p><details><summary>候选依据</summary><pre>'+html.escape(json.dumps(a,ensure_ascii=False,indent=2))+'</pre></details></section>')
    comparisons={}
    for clip in ['A','B']:
        for other in ['gap','acoustic']:
            left=cases.get(clip+'-text');right=cases.get(clip+'-'+other)
            if not left or not right:continue
            key=clip+' text vs '+other
            if left['errors'] or right['errors']:comparisons[key]={'status':'excluded_invalid'};continue
            x=set(left['sentence_boundaries']);y=set(right['sentence_boundaries']);comparisons[key]={'jaccard':len(x&y)/len(x|y) if x|y else 1,'added':sorted(y-x),'removed':sorted(x-y)}
    summary={'schema_version':1,'review_state':'experimental_unreviewed','cases':cases,'comparisons':comparisons,'limitations':['No human-labelled gold','Full-clip future context; no streaming claim','Pitch/energy features are estimates, not human emotion labels','Larger prompt changes latency; no general performance benchmark']}
    audit_path=OUT/'evidence-audit.json'
    if audit_path.exists():summary['numeric_evidence_audit']=json.loads(audit_path.read_text())
    omni_paths=sorted((OUT/'omni').rglob('*.result.json')) if (OUT/'omni').exists() else []
    summary['omni_result_files']=[str(p.relative_to(OUT)) for p in omni_paths]
    final_omni=OUT/'omni/final-summary.json'
    if final_omni.exists():summary['omni_final']=json.loads(final_omni.read_text())
    recovered=sorted((OUT/'omni/v2').glob('*.parsed_eos_result.json'))
    if recovered:
        blocks.append('<section><h2>Omni停止标记修正</h2><p>v2运行器漏用结束token，导致结束后重复。按首个EOS离线恢复：真实A保持148词但0句界；静音保持148词却输出16句界，负控失败。下面raw中的截断不能全部归因于模型。</p>'+''.join('<p><a href="'+str(p.relative_to(OUT))+'">'+html.escape(p.name)+'</a></p>' for p in recovered)+'</section>')
    for path in omni_paths:
        result=json.loads(path.read_text());relative=str(path.relative_to(OUT))
        blocks.append('<section><h2>Omni直接听音：'+html.escape(relative)+'</h2><p>独立模型及提示词探针，不与前三组作公平性能排名。完整原始结果保留。</p><a href="'+html.escape(relative,quote=True)+'">查看完整结果 JSON</a><pre>'+html.escape(json.dumps(result,ensure_ascii=False,indent=2)[:5000])+'</pre></section>')
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>声学断句消融</title><style>body{max-width:1050px;margin:36px auto;font:18px system-ui;line-height:1.9;background:#f5f5f3}section{background:white;padding:24px;margin:24px 0}span{cursor:pointer}span:hover{background:#def}audio{width:100%}pre{white-space:pre-wrap}strong{color:#b24}mark{background:#ffe7a2}</style><h1>声学断句消融实验</h1><p>● 完整句界；| 句内停顿；红色粗体为重音候选。点击单词按估计对齐时间回听。全部为未人工核验的候选；错误结果仅供诊断。</p><p>数值复核发现：A中deeply的“重读后回落”和destiny后的“存在停顿”缺乏所提供测量支持。结构通过不等于解释正确。</p>'+''.join(blocks))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
