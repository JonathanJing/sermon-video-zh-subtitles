#!/usr/bin/env python3
"""Render maintained flow specifications as editable, accessible SVG."""
from __future__ import annotations
import argparse
import html
import json
import math
from pathlib import Path

from readme_diagram_renderer import README_DIAGRAMS, render as render_readme_diagram, render_firebase_release

PALETTE = {
    'input': ('#46799B', '#EAF1F6', '输入 / INPUT'),
    'process': ('#267D72', '#EAF3EF', '执行 / PROCESS'),
    'agent': ('#766594', '#F0EDF5', '模型 / CONTEXT'),
    'gate': ('#AA7930', '#FAF2E5', '门槛 / GATE'),
    'output': ('#267D72', '#EAF3EF', '交付 / OUTPUT'),
    'archive': ('#6D7980', '#EDF0F0', '记录 / EVIDENCE'),
    'experiment': ('#A25B50', '#F6ECE8', '实验 / NOT VALIDATED'),
}
LAYER_PALETTE = [
    ('#2E78C7', '#EAF3FC'),
    ('#7450B2', '#F1ECFA'),
    ('#C96E08', '#FFF3E3'),
    ('#23805A', '#E8F5EF'),
]
FONT = '"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",Arial,sans-serif'
def esc(value): return html.escape(str(value), quote=True)
def units(value): return sum(1.0 if ord(c) > 255 else .56 for c in value)
def wrap(value, capacity):
    words = value.split(' ')
    lines, line = [], ''
    for word in words:
        pending = (' ' if line else '') + word
        if units(line + pending) <= capacity:
            line += pending
            continue
        if line: lines.append(line); line = ''
        if units(word) <= capacity: line = word; continue
        for char in word:
            if units(line + char) > capacity:
                lines.append(line); line = ''
            line += char
    if line: lines.append(line)
    return lines

class SVG:
    def __init__(self, spec):
        self.spec=spec; self.w=1600; self.h=spec.get('height',1280); self.parts=[]
        self.nodes={n['id']:n for n in spec.get('nodes',[])}
    def add(self,s): self.parts.append(s)
    def text(self,x,y,value,size=22,color='#243E47',weight=400,anchor='start',box=None,**extra):
        attributes=' '.join(f'{esc(k.replace("_","-"))}="{esc(v)}"' for k,v in extra.items())
        data=f' data-box="{",".join(str(v) for v in box)}"' if box else ''
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{data} {attributes}>{esc(value)}</text>')
    def rect(self,x,y,w,h,fill='#FFFFFF',stroke='none',rx=18,**attrs):
        rest=' '.join(f'{k.replace("_","-")}="{esc(v)}"' for k,v in attrs.items())
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" {rest}/>')
    def band(self,b):
        self.rect(b['x'],b['y'],b['w'],b['h'],b.get('fill','#EEEFEA'),rx=24)
        self.text(b['x']+22,b['y']+32,b['label'],18,'#60737A',600)
    def card(self,n):
        x,y,w,h=n['box']; role=n.get('role','process');c,tint,label=PALETTE[role]
        if self.spec.get('historical'): c,tint,label=PALETTE['archive'];label='历史 / HISTORICAL'
        self.add(f'<g id="node-{esc(n["id"])}" data-node="{esc(n["id"])}">')
        self.rect(x,y+4,w,h,'#E7E8E2',rx=18)
        self.rect(x,y,w,h,'#FFFFFF','#DAE0DC',stroke_width=1.25,stroke_dasharray='7 5' if role=='experiment' or self.spec.get('historical') else 'none')
        self.rect(x+1,y+18,4,h-36,c,rx=2)
        self.rect(x+24,y+21,35,28,tint,rx=8)
        self.text(x+41.5,y+41,n.get('step',str(n['id'])),16,c,700,'middle',box=(x+24,y+21,35,28))
        self.text(x+73,y+41,n.get('label',label),15,c,600,box=(x+68,y+18,w-88,35))
        title_lines=wrap(n['title'],(w-48)/25)
        ty=y+82
        for line in title_lines:
            self.text(x+24,ty,line,25,'#19343D',650,box=(x+20,y+55,w-40,h-68));ty+=32
        ty+=8
        for item in n.get('lines',[]):
            for line in wrap(item,(w-48)/21):
                self.text(x+24,ty,line,21,'#52676E',400,box=(x+20,y+55,w-40,h-68));ty+=29
        self.add('</g>')
    def edge(self,e):
        pts=e.get('points')
        if not pts:
            a=self.nodes[e['from']]['box'];b=self.nodes[e['to']]['box'];ax,ay,aw,ah=a;bx,by,bw,bh=b
            if abs(ay-by)<4:
                pts=[(ax+aw,ay+ah/2),(bx,by+bh/2)] if bx>ax else [(ax,ay+ah/2),(bx+bw,by+bh/2)]
            elif abs(ax+aw/2-bx-bw/2)<4:
                pts=[(ax+aw/2,ay+ah),(bx+bw/2,by)] if by>ay else [(ax+aw/2,ay),(bx+bw/2,by+bh)]
            else:
                start=(ax+aw/2,ay+ah if by>ay else ay);end=(bx+bw/2,by if by>ay else by+bh);mid=(start[1]+end[1])/2
                pts=[start,(start[0],mid),(end[0],mid),end]
        dashed=e.get('dashed',False) or self.spec.get('historical',False)
        color=e.get('color','#817397' if dashed else '#648A86')
        path='M'+' L'.join(f'{p[0]} {p[1]}' for p in pts)
        self.add(f'<path data-edge="{esc(e.get("from",""))}:{esc(e.get("to",""))}" d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="{"7 6" if dashed else "none"}" marker-end="url(#arrow)"/>')
        if e.get('label'):
            default=((pts[0][0]+pts[-1][0])/2,(pts[0][1]+pts[-1][1])/2-10)
            width=units(e['label'])*17+18
            if len(pts)==2 and pts[0][1]==pts[1][1] and width>abs(pts[0][0]-pts[1][0])-8 and e.get('from') in self.nodes:
                default=(default[0],self.nodes[e['from']]['box'][1]-20)
            lx,ly=e.get('labelAt',default)
            self.rect(lx-width/2,ly-22,width,30,'#F5F4EF',rx=6)
            self.text(lx,ly,e['label'],17,color,500,'middle')
    def header(self):
        p=self.spec;self.rect(0,0,self.w,self.h,'#F5F4EF',rx=0)
        self.rect(64,57,44,5,'#267D72',rx=2)
        self.text(124,69,p['english'],17,'#64787A',600,letter_spacing='2')
        self.text(64,127,p['title'],44,'#19343D',650)
        self.text(64,172,p['subtitle'],22,'#60737A')
        self.text(1536,69,p.get('indexLabel',f'{p["index"]:02d} / 11'),18,'#82918F',500,'end')
        self.add('<path d="M64 197H1536" stroke="#D8DEDA" stroke-width="1.3"/>')
    def footer(self):
        y=self.h-129
        self.rect(64,y,1472,78,'#E9EEE8',rx=16)
        for i,line in enumerate(self.spec['footer'][:2]):self.text(84,y+29+i*29,line,20,'#4C635F')
        design_reference=self.spec.get('designReference', 'GPT Image 2.5 Sunburst')
        self.text(64,self.h-22,f"内容校准 {self.spec.get('calibratedAt', '2026-09-11')} · 设计参考 {design_reference} · 原生可编辑 SVG",15,'#7B8B88')
        self.text(1536,self.h-22,'实线：主路径   虚线：条件 / 实验 / 历史',15,'#7B8B88',400,'end')
    def four_layer(self):
        card_y, card_w, card_h, gap = 238, 350, 876, 24
        xs = [64 + i * (card_w + gap) for i in range(4)]
        section_layout = [
            ('输入 / INPUT', 'input', 154, 132),
            ('流程 / PROCESS', 'process', 292, 190),
            ('模型与工具 / MODELS + TOOLS', 'models', 488, 188),
            ('输出与门禁 / OUTPUT + GATE', 'output', 682, 164),
        ]

        for index, (layer, x) in enumerate(zip(self.spec['layers'], xs)):
            accent, tint = LAYER_PALETTE[index]
            self.rect(x, card_y + 5, card_w, card_h, '#E0E5E2', rx=20)
            self.rect(x, card_y, card_w, card_h, '#FFFFFF', '#D5DFDB', rx=20, stroke_width=1.25)
            self.rect(x, card_y, card_w, 126, accent, rx=20)
            self.rect(x, card_y + 103, card_w, 23, accent, rx=0)
            self.rect(x + 20, card_y + 21, 48, 48, '#FFFFFF', rx=24)
            self.text(x + 44, card_y + 54, str(index + 1), 24, accent, 750, 'middle')
            self.text(x + 82, card_y + 44, f'Layer {index + 1}', 17, '#FFFFFF', 700)
            for line_index, line in enumerate(wrap(layer['title'], 15)):
                self.text(x + 82, card_y + 76 + line_index * 25, line, 21, '#FFFFFF', 650)
            self.text(x + 20, card_y + 112, layer['english'], 14, '#EAF4FF', 500)

            for label, key, y_offset, height in section_layout:
                section_y = card_y + y_offset
                self.rect(x + 16, section_y, card_w - 32, height, tint, rx=12)
                self.text(x + 31, section_y + 25, label, 14, accent, 700)
                line_y = section_y + 52
                for item in layer[key]:
                    item_lines = wrap(item, 25)
                    for item_index, line in enumerate(item_lines):
                        prefix = '• ' if item_index == 0 else '  '
                        self.text(x + 31, line_y, prefix + line, 15, '#304951', 430)
                        line_y += 21
                    line_y += 3

        for index in range(3):
            x1 = xs[index] + card_w + 3
            x2 = xs[index + 1] - 5
            y = card_y + 441
            self.add(f'<path d="M{x1} {y}H{x2}" stroke="#607B76" stroke-width="3" marker-end="url(#arrow)"/>')

        strip_y = 1148
        self.rect(64, strip_y, 1472, 122, '#EDF2F0', '#D5DFDB', rx=18, stroke_width=1.1)
        self.text(88, strip_y + 35, '一个共享英文主干；每种目标语言独立完成 Layer 2 → 3 → 4', 20, '#19343D', 650)
        self.text(88, strip_y + 68, 'English Source Package 只生成一次；中文不是韩语或西班牙语的中转源。', 16, '#52676E')
        pills = [('zh-Hans', '#FCECF0', '#A54059'), ('ko', '#E9F2FF', '#2E69A7'), ('es', '#EAF6EE', '#23724F')]
        for i, (label, fill, color) in enumerate(pills):
            px = 1022 + i * 158
            self.rect(px, strip_y + 33, 136, 52, fill, color, rx=26, stroke_width=1)
            self.text(px + 68, strip_y + 66, label, 18, color, 700, 'middle')

        live_y = 1296
        self.rect(64, live_y, 720, 92, '#F7F1E8', '#D8C49B', rx=16, stroke_width=1.1, stroke_dasharray='7 5')
        self.text(86, live_y + 33, '独立旁路：Sunday live / live_session', 18, '#8B6429', 700)
        self.text(86, live_y + 62, '现场不生成四个包；录音若会后持久化，重新从 Layer 1 开始。', 16, '#5D665E')
        self.rect(816, live_y, 720, 92, '#F0EDF5', '#C5B9D7', rx=16, stroke_width=1.1)
        self.text(838, live_y + 33, '跨层编排：GPT-6 Astra Supervisor + 受限确定性工具', 18, '#655184', 700)
        self.text(838, live_y + 62, 'Agent 只编排和重读证据；不能自授人工批准，也不能把 legacy complete 升级。', 16, '#5D665E')
    def render(self):
        p=self.spec
        self.add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="title desc">')
        self.add(f'<title id="title">{esc(p["title"])}</title><desc id="desc">{esc(p["subtitle"]+" "+" ".join(p["footer"]))}</desc>')
        self.add(f'<style>text{{font-family:{FONT};}} text{{font-variant-ligatures:none}}</style>')
        self.add('<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M1 1 L7 4 L1 7" fill="none" stroke="context-stroke" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>')
        self.header()
        for b in p.get('bands',[]):self.band(b)
        if p.get('kind')=='sequence': self.sequence()
        elif p.get('kind')=='four-layer': self.four_layer()
        else:
            for e in p.get('edges',[]):self.edge(e)
            for n in p['nodes']:self.card(n)
        self.footer();self.add('</svg>')
        return '\n'.join(self.parts)+'\n'
    def sequence(self):
        # Eight chronological phases; model/storage results always route via Gateway.
        xs=[255,560,865,1170,1475];labels=['Browser','Gateway','ASR','Translation','Disk']
        for i in range(len(self.spec['stages'])):
            if i%2==0:self.rect(64,295+i*141,1472,135,'#EBEEE8',rx=12)
        for x,label in zip(xs,labels):
            self.rect(x-99,218,198,56,'#FFFFFF','#D8DEDA',rx=14);self.text(x,253,label,23,'#19343D',600,'middle')
            self.add(f'<path d="M{x} 279V{self.h-157}" stroke="#C9D5CF" stroke-width="1.5" stroke-dasharray="4 7"/>')
        stages=self.spec['stages']
        for i,stage in enumerate(stages):
            y=305+i*141
            self.text(85,y+29,f'{i+1:02d}',20,'#267D72',700)
            for j,line in enumerate(wrap(stage['name'],6)):
                self.text(85,y+60+25*j,line,19,'#19343D',600,box=(72,y+32,151,95))
            for j,event in enumerate(stage['events']):
                sy=y+43+j*39;start=xs[event[0]];end=xs[event[1]]
                if start==end:
                    pts=[(start,sy),(start+40,sy),(start+40,sy+19),(start,sy+19)]
                else:pts=[(start,sy),(end,sy)]
                self.edge({'points':pts,'color':'#7A6892' if event[0]==3 or event[1]==3 else '#648A86','dashed':event[3] if len(event)>3 else False})
                tx=(start+end)/2;self.text(tx,sy-9,event[2],18,'#344E57',500,'middle',box=(min(start,end)-18,sy-34,abs(end-start)+36,31))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--spec',type=Path,required=True);parser.add_argument('--out-dir',type=Path,required=True);args=parser.parse_args();args.out_dir.mkdir(parents=True,exist_ok=True)
    specs=json.loads(args.spec.read_text())
    for i,spec in enumerate(specs,1):
        spec['index']=i
        svg = render_readme_diagram(spec) if spec['name'] in README_DIAGRAMS else SVG(spec).render()
        (args.out_dir/(spec['name']+'.svg')).write_text(svg)
    (args.out_dir/'firebase-release-flow.svg').write_text(render_firebase_release())
    print(f'Rendered {len(specs) + 1} native SVG diagrams')
if __name__=='__main__':main()
