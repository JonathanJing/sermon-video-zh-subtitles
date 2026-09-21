#!/usr/bin/env python3
"""Build a phone-friendly review page for the full-sermon sidecar."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--judge", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sidecar = json.loads(args.sidecar.read_text(encoding="utf-8"))
    judgments = {}
    if args.judge and args.judge.is_file():
        judge = json.loads(args.judge.read_text(encoding="utf-8"))
        judgments = {item["sentenceId"]: item for item in judge.get("sentenceJudgments", [])}
    sentences = sidecar["sentences"]
    cards = []
    for window in manifest["windows"]:
        items = [item for item in sentences if item.get("geminiWindowId") == window["windowId"]]
        rows = []
        for item in items:
            judgment = judgments.get(item["sentenceId"], {})
            verdict = judgment.get("verdict", "待 GPT-6")
            gemini_type = item.get("geminiType") or ""
            rows.append(
                f'<tr data-sentence-id="{item["sentenceId"]}" '
                f'data-start="{item["startSeconds"]:.6f}" data-end="{item["endSeconds"]:.6f}" '
                f'data-window-start="{window["relativeStartSeconds"]:.6f}" '
                f'data-gemini-type="{html.escape(gemini_type)}">'
                f'<td><button class="play-sentence" type="button">▶︎</button> '
                f'{item["startSeconds"]:.2f}–{item["endSeconds"]:.2f}</td>'
                f'<td>{html.escape(gemini_type or "未覆盖")}</td>'
                f'<td>{html.escape(verdict)}</td><td class="sentence-text">{html.escape(item["text"])}</td>'
                f'<td class="human-review"><button class="accept-gemini" type="button" '
                f'{"" if gemini_type else "disabled"}>接受</button>'
                '<select class="human-type" aria-label="人工类别">'
                '<option value="">未审</option><option value="sermon_explanation">讲解</option>'
                '<option value="scripture_reading">读经</option><option value="transition">过渡</option>'
                '<option value="other">其他</option><option value="mixed_requires_split">混合／需拆分</option>'
                '<option value="inaudible">无法判断</option></select>'
                '<input class="human-note" type="text" placeholder="备注（可选）"></td></tr>')
        video = "../" + window["paths"]["video"]
        sheet = "../" + window["paths"]["contactSheet"]
        cards.append(f'''<section id="{window['windowId']}">
<h2>{window['windowId']} · {window['relativeStartSeconds']:.0f}–{window['relativeEndSeconds']:.0f}s</h2>
<video controls preload="none" playsinline src="{html.escape(video)}"></video>
<img loading="lazy" src="{html.escape(sheet)}" alt="contact sheet">
<label class="window-check"><input class="window-listened" type="checkbox" data-window-id="{window['windowId']}"> 已完整听过这个窗口</label>
<div class="table-wrap"><table><thead><tr><th>时间</th><th>Gemini</th><th>GPT-6</th><th>英文句子</th><th>人工 Gold</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>''')
    source = sidecar["source"]
    sidecar_hash = sha256(args.sidecar)
    judge_hash = sha256(args.judge) if args.judge and args.judge.is_file() else None
    page = f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全篇 Gemini sidecar 听审</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;background:#f4f5f7;color:#17202a}}
header{{position:sticky;top:0;background:#102a43;color:white;padding:12px 16px;z-index:2}}
main{{max-width:900px;margin:auto;padding:12px}}section{{background:white;border-radius:14px;padding:12px;margin:12px 0;box-shadow:0 2px 10px #0001}}
video,img{{width:100%;border-radius:8px;margin:6px 0}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:7px;border-top:1px solid #dde3ea;text-align:left;vertical-align:top}}th:first-child,td:first-child{{white-space:nowrap}}
.meta{{font-size:13px;opacity:.9}}.toolbar{{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-top:8px}}
.toolbar input{{max-width:150px}}button,select,input{{font:inherit;padding:6px;border:1px solid #9fb3c8;border-radius:7px;background:white}}
button{{color:#102a43;font-weight:600}}.table-wrap{{overflow-x:auto}}.human-review{{min-width:240px}}
.human-review select{{width:105px}}.human-note{{width:110px}}.reviewed{{background:#effcf6}}.needs-work{{background:#fff8e6}}
.window-check{{display:block;padding:8px 0;font-weight:600}}.play-sentence{{padding:3px 7px}}
@media(max-width:620px){{th:nth-child(3),td:nth-child(3){{display:none}}table{{min-width:760px}}header{{position:relative}}}}
</style></head><body><header><strong>全篇 Gemini sidecar 听审</strong>
<div class="meta" id="progress">411 句候选 · 39 窗口 · 尚未形成完整人工 Gold</div>
<div class="toolbar"><input id="reviewer" placeholder="审阅者（可选）"><button id="export" type="button">下载审阅 JSON</button>
<button id="copy" type="button">复制 JSON</button><button id="import-button" type="button">导入 JSON</button>
<input id="import-file" type="file" accept="application/json" hidden></div></header>
<main>{''.join(cards)}</main><script>
const BINDING={json.dumps({
    "source": source,
    "sidecar": {"path": str(args.sidecar.resolve()), "sha256": sidecar_hash},
    "judge": {"path": str(args.judge.resolve()), "sha256": judge_hash} if args.judge else None,
    "sentenceCount": len(sentences), "windowCount": len(manifest["windows"]),
}, ensure_ascii=False)};
const KEY='sermon-human-gold:'+BINDING.sidecar.sha256;
let state={{schemaVersion:'sermon-omni-human-gold-review-v1',reviewer:'',windows:{{}},decisions:{{}}}};
try{{const saved=localStorage.getItem(KEY);if(saved)state=JSON.parse(saved);}}catch(e){{}}
const canonical=new Set(['sermon_explanation','scripture_reading','transition','other']);
function save(){{state.reviewer=document.querySelector('#reviewer').value.trim();localStorage.setItem(KEY,JSON.stringify(state));update();}}
function update(){{
  const decisions=Object.values(state.decisions); const reviewed=decisions.filter(x=>x.humanType).length;
  const canonicalCount=decisions.filter(x=>canonical.has(x.humanType)).length;
  const heard=Object.values(state.windows).filter(x=>x.listened).length;
  const complete=reviewed===BINDING.sentenceCount&&canonicalCount===reviewed&&heard===BINDING.windowCount;
  document.querySelector('#progress').textContent=`${{reviewed}}/${{BINDING.sentenceCount}} 句已审 · ${{heard}}/${{BINDING.windowCount}} 窗已听 · ${{complete?'完整人工 Gold 候选':'尚未完整'}}`;
  document.querySelectorAll('tr[data-sentence-id]').forEach(row=>{{const d=state.decisions[row.dataset.sentenceId];row.classList.toggle('reviewed',!!d?.humanType&&canonical.has(d.humanType));row.classList.toggle('needs-work',!!d?.humanType&&!canonical.has(d.humanType));}});
}}
function restore(){{
  document.querySelector('#reviewer').value=state.reviewer||'';
  document.querySelectorAll('tr[data-sentence-id]').forEach(row=>{{const d=state.decisions[row.dataset.sentenceId]||{{}};row.querySelector('.human-type').value=d.humanType||'';row.querySelector('.human-note').value=d.note||'';}});
  document.querySelectorAll('.window-listened').forEach(box=>box.checked=!!state.windows[box.dataset.windowId]?.listened);update();
}}
function record(row){{const type=row.querySelector('.human-type').value;const note=row.querySelector('.human-note').value.trim();state.decisions[row.dataset.sentenceId]={{humanType:type,note,reviewedAt:new Date().toISOString()}};save();}}
document.querySelectorAll('.human-type,.human-note').forEach(el=>el.addEventListener('change',()=>record(el.closest('tr'))));
document.querySelectorAll('.accept-gemini').forEach(button=>button.addEventListener('click',()=>{{const row=button.closest('tr');row.querySelector('.human-type').value=row.dataset.geminiType;record(row);}}));
document.querySelectorAll('.window-listened').forEach(box=>box.addEventListener('change',()=>{{state.windows[box.dataset.windowId]={{listened:box.checked,reviewedAt:new Date().toISOString()}};save();}}));
document.querySelector('#reviewer').addEventListener('change',save);
document.querySelectorAll('.play-sentence').forEach(button=>button.addEventListener('click',()=>{{
  const row=button.closest('tr'),section=row.closest('section'),video=section.querySelector('video');
  const start=Math.max(0,Number(row.dataset.start)-Number(row.dataset.windowStart)-.5);
  const stop=Math.max(start+.3,Number(row.dataset.end)-Number(row.dataset.windowStart)+.5);
  const begin=()=>{{video.currentTime=start;video.play();const watcher=()=>{{if(video.currentTime>=stop){{video.pause();video.removeEventListener('timeupdate',watcher);}}}};video.addEventListener('timeupdate',watcher);}};
  if(video.readyState>=1)begin();else{{video.addEventListener('loadedmetadata',begin,{{once:true}});video.load();}}
}}));
function exportValue(){{
 const decisions=Object.entries(state.decisions).map(([sentenceId,value])=>({{sentenceId,...value}}));
 const windows=Object.entries(state.windows).map(([windowId,value])=>({{windowId,...value}}));
 const reviewed=decisions.filter(x=>x.humanType).length, heard=windows.filter(x=>x.listened).length;
 const humanGold=reviewed===BINDING.sentenceCount&&decisions.every(x=>canonical.has(x.humanType))&&heard===BINDING.windowCount;
 return {{...state,binding:BINDING,exportedAt:new Date().toISOString(),reviewState:humanGold?'complete_operator_listening_review':'operator_review_in_progress',humanGold,releaseEligible:false,decisions,windows}};
}}
document.querySelector('#export').addEventListener('click',()=>{{const blob=new Blob([JSON.stringify(exportValue(),null,2)+'\\n'],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='20260920-sermon-human-gold-review.json';a.click();URL.revokeObjectURL(a.href);}});
document.querySelector('#copy').addEventListener('click',async()=>{{await navigator.clipboard.writeText(JSON.stringify(exportValue(),null,2));alert('已复制审阅 JSON');}});
document.querySelector('#import-button').addEventListener('click',()=>document.querySelector('#import-file').click());
document.querySelector('#import-file').addEventListener('change',async e=>{{const value=JSON.parse(await e.target.files[0].text());if(value.binding?.sidecar?.sha256!==BINDING.sidecar.sha256){{alert('sidecar 哈希不匹配，拒绝导入');return;}}state={{schemaVersion:value.schemaVersion,reviewer:value.reviewer||'',windows:Object.fromEntries((value.windows||[]).map(x=>[x.windowId,x])),decisions:Object.fromEntries((value.decisions||[]).map(x=>[x.sentenceId,x]))}};save();restore();}});
restore();
</script></body></html>'''
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(json.dumps({"out": str(args.out), "windows": len(cards)}))


if __name__ == "__main__":
    main()
