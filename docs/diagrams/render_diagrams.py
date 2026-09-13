#!/usr/bin/env python3
"""Render maintained flow specifications as editable, accessible SVG."""
from __future__ import annotations
import argparse
import html
import json
import math
from pathlib import Path

PALETTE = {
    'input': ('#46799B', '#EAF1F6', '输入 / INPUT'),
    'process': ('#267D72', '#EAF3EF', '执行 / PROCESS'),
    'agent': ('#766594', '#F0EDF5', '模型 / CONTEXT'),
    'gate': ('#AA7930', '#FAF2E5', '门槛 / GATE'),
    'output': ('#267D72', '#EAF3EF', '交付 / OUTPUT'),
    'archive': ('#6D7980', '#EDF0F0', '记录 / EVIDENCE'),
    'experiment': ('#A25B50', '#F6ECE8', '实验 / NOT VALIDATED'),
}
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
        self.nodes={n['id']:n for n in spec['nodes']}
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
        self.text(1536,69,f'{p["index"]:02d} / 11',18,'#82918F',500,'end')
        self.add('<path d="M64 197H1536" stroke="#D8DEDA" stroke-width="1.3"/>')
    def footer(self):
        y=self.h-129
        self.rect(64,y,1472,78,'#E9EEE8',rx=16)
        for i,line in enumerate(self.spec['footer'][:2]):self.text(84,y+29+i*29,line,20,'#4C635F')
        self.text(64,self.h-22,'内容校准 2026-09-11 · 设计参考 GPT Image 2.5 Sunburst · 原生可编辑 SVG',15,'#7B8B88')
        self.text(1536,self.h-22,'实线：主路径   虚线：条件 / 实验 / 历史',15,'#7B8B88',400,'end')
    def render(self):
        p=self.spec
        self.add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="title desc">')
        self.add(f'<title id="title">{esc(p["title"])}</title><desc id="desc">{esc(p["subtitle"]+" "+" ".join(p["footer"]))}</desc>')
        self.add(f'<style>text{{font-family:{FONT};}} text{{font-variant-ligatures:none}}</style>')
        self.add('<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M1 1 L7 4 L1 7" fill="none" stroke="context-stroke" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>')
        self.header()
        for b in p.get('bands',[]):self.band(b)
        if p.get('kind')=='sequence': self.sequence()
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
        spec['index']=i;(args.out_dir/(spec['name']+'.svg')).write_text(SVG(spec).render())
    print(f'Rendered {len(specs)} native SVG diagrams')
if __name__=='__main__':main()
