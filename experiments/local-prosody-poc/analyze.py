"""Offline comparison; agreement is not accuracy and invalid outputs are excluded."""
import html
import json
from run import ROOT, OUT

def boundaries(record):
    if record['validation_errors']:
        return None
    return {s['end_word'] for s in record['analysis']['sentences'][:-1]}

def compare(left,right):
    a,b=boundaries(left),boundaries(right)
    if a is None or b is None:return {'status':'excluded_invalid_output'}
    return {'status':'comparable','jaccard':len(a&b)/len(a|b) if a|b else 1.0,'only_left':sorted(a-b),'only_right':sorted(b-a)}

def main():
    results={name:json.loads((OUT/(name+'.json')).read_text()) for name in ['A-text','B-text','A-text-repeat','A-aligned','B-aligned']}
    comparisons={}
    for a,b in [('A-text','A-text-repeat'),('A-text','A-aligned'),('B-text','B-aligned')]:
        comparisons[a+' vs '+b]=compare(results[a],results[b])
    for clip in ['A','B']:
        gemini=json.loads((ROOT/'artifacts/gemini-prosody-poc/20260917'/(clip+'-text.json')).read_text())
        comparisons[clip+' local text vs Gemini text']=compare(results[clip+'-text'],gemini)
    summary={'schema_version':1,'review_state':'experimental_unreviewed','comparisons':comparisons,'cases':{n:{'sentence_count':len(r['analysis']['sentences']),'validation_errors':r['validation_errors'],'latency_seconds':r['latency_seconds']} for n,r in results.items()},'limitations':['No human gold','Alignment intervals are estimates, not speech/emotion verification','Only two clips from one speaker','Exact-zero rejection is not general VAD','Text and gap conditions do not receive raw audio']}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    sections=[]
    for name,r in results.items():
        clip=name[0];alignment=json.loads((OUT/'alignment'/(clip+'.json')).read_text());words=r['words'];timed=alignment['words']
        rows=[]
        for s in r['analysis']['sentences']:
            a,b=s['start_word'],s['end_word']
            punctuation=s.get('punctuation')
            text=' '.join(words[a:b+1])+(punctuation if punctuation in ('.','?','!','...',',',';',':') else '')
            stamp=timed[a]['start'] if 0<=a<len(timed) else 0
            rows.append('<p><button onclick="const a=document.getElementById(\''+name+'\');a.currentTime='+str(stamp)+';a.play()">回听 '+str(stamp)+'s</button> '+html.escape(text)+'<br><small>'+html.escape(s.get('evidence',''))+'</small></p>')
        src='../../gemini-prosody-poc/20260917/'+clip+'.wav'
        sections.append('<section><h2>'+name+'</h2><b>'+html.escape(str(r['validation_errors']) if r['validation_errors'] else '结构通过；仍需听音评审')+'</b><audio id="'+name+'" controls src="'+src+'"></audio>'+''.join(rows)+'</section>')
    (OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>本地断句对照</title><style>body{font:17px system-ui;max-width:1000px;margin:35px auto;line-height:1.7;background:#f5f5f3}section{background:white;padding:24px;margin:20px 0}audio{display:block;width:100%}small{color:#555}pre{white-space:pre-wrap}</style><h1>本地模型断句研究</h1><p>Qwen3.8-27B 文字 / 文字＋Qwen3-ForcedAligner 词间间隔。候选结果，非生产字幕；回听位置为模型对齐估计。带错误的输出仅供诊断。</p><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>'+''.join(sections))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
