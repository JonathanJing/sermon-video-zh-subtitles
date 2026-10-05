"""Read-only, aggregate Codex tool-operation audit; never emits conversation text."""
import argparse, ast, collections, datetime, hashlib, json, pathlib, re

def js_mask(s):
    # Keep executable punctuation and identifiers; blank quoted strings/comments.
    out=list(s);i=0
    while i<len(s):
        if s[i] in '\"\'`':
            q=s[i];j=i+1
            while j<len(s):
                if s[j]=='\\':j+=2;continue
                if s[j]==q:j+=1;break
                j+=1
            out[i:j]=' '*(j-i);i=j
        elif s.startswith('//',i):
            j=s.find('\n',i);j=len(s) if j<0 else j;out[i:j]=' '*(j-i);i=j
        elif s.startswith('/*',i):
            j=s.find('*/',i+2);j=len(s) if j<0 else j+2;out[i:j]=' '*(j-i);i=j
        else:i+=1
    return ''.join(out)

def literal_cmd(s,start):
    m=re.match(r'\s*\(\s*\{',s[start:])
    if not m:return None
    a=start+m.end();masked=js_mask(s[a:]);depth=1;j=0
    for j,c in enumerate(masked):
        if c=='{':depth+=1
        elif c=='}':
            depth-=1
            if depth==0:break
    block=s[a:a+j]
    m=re.search(r'(?:"cmd"|\bcmd)\s*:\s*("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)',block,re.S)
    if not m:return None
    v=m.group(1)
    try:
        if v.startswith('"'):return json.loads(v)
        if v.startswith("'"):return ast.literal_eval(v)
        if '${' not in v:return v[1:-1]
    except (ValueError,SyntaxError):return None
    return None

def command_class(c):
    if re.search(r'\b(?:firebase\s+deploy|gh\s+pr|git\s+(?:push|commit|fetch))\b',c):return 'git_or_publication'
    if re.search(r'\b(?:pytest|unittest)\b|\btest_[\w.-]+\.py\b',c):return 'tests'
    if re.search(r'\b(?:ssh|scp|rsync)\b',c):return 'remote_operation_or_query'
    if re.search(r'read_queue\.py|(?:queue|production|gpu).{0,18}status|nvidia-smi|docker ps|ps -[a-zA-Z]',c):return 'status_query'
    if re.search(r'\b(?:render|run_target_language|produce_target_language|build_target_language|prepare_target_language|review_target_language|screen_target_language|deploy_catalog|seal_locale|prepare_locale|merge_locale)[\w-]*\.py',c):return 'producer_or_release_cli'
    if re.search(r'write_text\(|write_bytes\(|\.write\(|json\.dump\(|\b(?:mkdir|cp|mv|touch|chmod)\b|cat\s*>|open\([^\n]*["\'](?:w|a|wb|ab)["\']',c):return 'local_write_or_mixed'
    if re.search(r'\b(?:rg|cat|sed|head|tail|ls|find|wc|stat|shasum|ffprobe)\b|read_text\(|read_bytes\(|json\.load|--help|git (?:status|diff|log|show|rev-parse)',c):return 'local_inspection_or_query'
    return 'unclassified_command'

def direct_class(name,namespace):
    if name in ('sleep','wait','wait_agent','list_agents','write_stdin'):return 'wait_or_status'
    if name in ('send_message','followup_task','spawn_agent','interrupt_agent'):return 'agent_coordination'
    if name=='request_user_input_async':return 'user_question'
    if name in ('js','js_reset'):return 'ui_operation_or_inspection'
    if name=='exec':return 'orchestration'
    # Collapse internal support machinery; do not export private names/content.
    return 'context_or_other_support'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--sessions-root',type=pathlib.Path,required=True);ap.add_argument('--root-thread-id',required=True);ap.add_argument('--start',required=True);ap.add_argument('--end',required=True);ap.add_argument('--out',type=pathlib.Path,required=True);args=ap.parse_args()
    files=[];meta={}
    # Metadata-only pass establishes exact parent linkage. No unrelated body read.
    for p in args.sessions_root.rglob('*.jsonl'):
        try:
            with p.open() as f:m=json.loads(next(f)).get('payload',{})
            src=m.get('source');spawn=src.get('subagent',{}).get('thread_spawn',{}) if isinstance(src,dict) else {};tid=m.get('id')
            files.append((p,tid));meta[tid]=dict(parent=spawn.get('parent_thread_id'),agent=spawn.get('agent_path','/root'))
        except (ValueError,StopIteration,OSError):continue
    ids={args.root_thread_id}
    while True:
        more={k for k,v in meta.items() if v['parent'] in ids}-ids
        if not more:break
        ids|=more
    byscope={};sourcefiles=[]
    for scope in ('main','all_linked'):
        seen=set();counts=collections.Counter();categories=collections.Counter();nested=collections.Counter();cc=collections.Counter();commands=collections.defaultdict(list);repeated=collections.Counter();spawnfork=collections.Counter();sleep_requested=0;outputchars=collections.Counter();callt={};latencies=collections.defaultdict(list);payloads={};pairoutputs=set();progresslinks={};progressrows=collections.defaultdict(list);func=custom=0
        for p,tid in files:
            if tid not in ids or (scope=='main' and tid!=args.root_thread_id):continue
            contributed=False
            for ln in p.open():
                d=json.loads(ln);t=d.get('timestamp','')
                if not args.start<=t<args.end or d.get('type')!='response_item':continue
                v=d.get('payload',{});typ=v.get('type');callid=v.get('call_id');key=(tid,callid)
                if typ in ('function_call','custom_tool_call'):
                    if key in seen:continue
                    contributed=True;seen.add(key);name=v.get('name','');cat=direct_class(name,v.get('namespace'));categories[cat]+=1;counts[name]+=1;callt[key]=(t,cat)
                    if typ=='function_call':func+=1
                    else:custom+=1
                    raw=v.get('arguments','') if typ=='function_call' else v.get('input','');payloads[key]=hashlib.sha256((name+'\0'+raw).encode()).hexdigest();repeated[payloads[key]]+=1
                    if name=='spawn_agent':
                        try:av=json.loads(raw);spawnfork[av.get('fork_turns','all-default')]+=1
                        except ValueError:spawnfork['unparsed']+=1
                    if name=='sleep':
                        try:sleep_requested+=json.loads(raw).get('duration_ms',0)/1000
                        except ValueError:pass
                    if name=='exec' and typ=='custom_tool_call':
                        mask=js_mask(raw)
                        for m in re.finditer(r'\btools\.([A-Za-z_][A-Za-z_0-9]*)\s*(?=\()',mask):
                            nm=m.group(1);nested[nm]+=1
                            if nm=='exec_command':
                                cmd=literal_cmd(raw,m.end())
                                if cmd is None:cc['unparsed_or_dynamic']+=1
                                else:
                                    cl=command_class(cmd);cc[cl]+=1;h=hashlib.sha256(cmd.encode()).hexdigest();commands[h].append((t,cl))
                                    if 'renders=' in cmd and 'wavs=' in cmd:progresslinks[key]=h
                elif typ in ('function_call_output','custom_tool_call_output') and key in callt and key not in pairoutputs:
                    pairoutputs.add(key);st,cat=callt[key];dur=(datetime.datetime.fromisoformat(t.replace('Z','+00:00'))-datetime.datetime.fromisoformat(st.replace('Z','+00:00'))).total_seconds();latencies[cat].append(dur);outputchars[cat]+=len(str(v.get('output','')))
                    if key in progresslinks:
                        blocks=v.get('output',[]);txt='\n'.join(z.get('text','') for z in blocks) if isinstance(blocks,list) else str(blocks)
                        state={k:int(value) for k,value in re.findall(r'\b(renders|wavs)=(\d+)',txt)}
                        status=re.search(r'\bcontainer=([a-z]+)',txt)
                        if status:state['container']=status.group(1)
                        if state:progressrows[progresslinks[key]].append((t,state))
            if contributed and scope=='all_linked':sourcefiles.append(dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
        cmdrepeats=collections.Counter();longrepeat=[]
        for h,xs in commands.items():
            if len(xs)>1:
                cmdrepeats[xs[0][1]]+=len(xs)-1
                longrepeat.append(dict(commandSha256=h,occurrences=len(xs),category=xs[0][1],first=xs[0][0],last=xs[-1][0]))
        progresssummary=[dict(commandSha256=h,observations=len(v),distinctStates=len({json.dumps(x,sort_keys=True) for t,x in v}),first=v[0],last=v[-1]) for h,v in progressrows.items() if len(v)>=10]
        publicnames={k:v for k,v in counts.items() if direct_class(k,'')!='context_or_other_support'}
        def q95(xs):return sorted(xs)[min(len(xs)-1,int((len(xs)-1)*.95))] if xs else None
        byscope[scope]=dict(progressQuerySamples=progresssummary,outerToolCalls=len(seen),functionCalls=func,customToolCalls=custom,categories=dict(categories),publicToolNames=publicnames,staticNestedCallSites={k:v for k,v in nested.items() if k in ('exec_command','write_stdin','apply_patch','view_image','web__run')},commandClasses=dict(cc),literalCommandCount=sum(len(x) for x in commands.values()),uniqueLiteralCommands=len(commands),exactRepeatedCommandOccurrences=sum(cmdrepeats.values()),repeatedCommandClasses=dict(cmdrepeats),topRepeatedCommandHashes=sorted(longrepeat,key=lambda x:-x['occurrences'])[:15],exactRepeatedOuterCalls=sum(n-1 for n in repeated.values()),spawnForkSettings=dict(spawnfork),sleepRequestedSeconds=sleep_requested,callOutputPairCoverage=dict(paired=len(pairoutputs),calls=len(seen)),toolObservedReturnLatencySeconds={k:dict(samples=len(v),sum=sum(v),p95=q95(v),max=max(v)) for k,v in latencies.items()},toolOutputCharactersByCategory=dict(outputchars))
    # Match prior production window, serialize counts only; no raw commands or messages.
    result=dict(schemaVersion='retrospective-codex-operations-v1',start=args.start,end=args.end,scope='root and exact parent-linked descendants',classification='Heuristic static call-site classification, not executed subprocess count; command bytes are hashed only.',limitations=['Repeated query may be necessary to observe changing state.','Mixed commands use documented precedence; no per-category causal token allocation.','Return latency includes waits and does not measure pure model or tool compute.','sleep duration is requested, not measured elapsed; new input may interrupt.'],scopes=byscope,sources=sourcefiles)
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk not in ['topRepeatedCommandHashes','toolOutputCharactersByCategory','toolObservedReturnLatencySeconds','staticNestedCallSites']} for k,v in byscope.items()},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
