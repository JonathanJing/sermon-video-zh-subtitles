"""Render the diagrams embedded in the root READMEs as native SVG.

The existing diagram-specs.json remains the source for content and geometry.
This renderer changes only the presentation of the seven generated README assets.
"""

from __future__ import annotations

import html


README_DIAGRAMS = {
    "four-layer-production-workflow",
    "project-map",
    "solution-journey",
    "saturday-chinese-voice-workflow",
    "saturday-post-live-workflow",
    "sunday-live-workflow",
    "local-live-architecture",
}

FONT = "-apple-system,BlinkMacSystemFont,'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif"
ROLE = {
    "input": ("#326fb4", "#eaf2fc", "来源 / INPUT"),
    "process": ("#18877c", "#e6f6f2", "执行 / PROCESS"),
    "agent": ("#7460b7", "#f0edfa", "模型 / REVIEW"),
    "gate": ("#ad751c", "#fff3de", "门槛 / GATE"),
    "output": ("#198665", "#e7f7ee", "交付 / OUTPUT"),
    "archive": ("#657a90", "#edf2f7", "记录 / EVIDENCE"),
    "experiment": ("#b95d54", "#fff0ec", "实验 / POC"),
}
LAYERS = [
    ("#326fb4", "#eaf2fc"),
    ("#7460b7", "#f0edfa"),
    ("#c68224", "#fff3e4"),
    ("#198665", "#e7f7ee"),
]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def units(value: str) -> float:
    return sum(1 if ord(char) > 255 else 0.54 for char in value)


def wrap(value: str, capacity: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in value.split(" "):
        pending = (" " if current else "") + word
        if units(current + pending) <= capacity:
            current += pending
            continue
        if current:
            lines.append(current)
            current = ""
        if units(word) <= capacity:
            current = word
            continue
        for char in word:
            if units(current + char) > capacity:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return lines


class Drawing:
    def __init__(self, spec: dict):
        self.spec = spec
        self.width = 1600
        self.height = spec.get("height", 1280)
        self.nodes = {node["id"]: node for node in spec.get("nodes", [])}
        self.parts: list[str] = []

    def add(self, value: str) -> None:
        self.parts.append(value)

    def rect(self, x, y, width, height, *, fill="#ffffff", stroke="none", radius=18, extra="") -> None:
        self.add(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="{radius}" fill="{fill}" stroke="{stroke}" {extra}/>'
        )

    def text(self, x, y, value, *, size=20, color="#17314e", weight=400, anchor="start", extra="") -> None:
        self.add(
            f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}" {extra}>{esc(value)}</text>'
        )

    def start(self) -> None:
        self.add(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" role="img" aria-labelledby="title description">'
        )
        self.add(f'<title id="title">{esc(self.spec["title"])}</title>')
        self.add(
            f'<desc id="description">{esc(self.spec["subtitle"] + "。" + "；".join(self.spec["footer"]))}</desc>'
        )
        self.add(
            '<defs>'
            '<linearGradient id="canvas" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#f7faff"/><stop offset="1" stop-color="#edf5f6"/>'
            '</linearGradient>'
            '<filter id="card-shadow" x="-15%" y="-25%" width="130%" height="155%">'
            '<feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#173452" flood-opacity="0.10"/>'
            '</filter>'
            '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
            '<path d="M0 0 L10 5 L0 10 Z" fill="#718da5"/></marker>'
            '</defs>'
        )
        self.add(f'<style>text{{font-family:{FONT};font-variant-ligatures:none}}</style>')
        self.rect(0, 0, self.width, self.height, fill="url(#canvas)", radius=0)
        self.add('<circle cx="1510" cy="25" r="260" fill="#dcebed" opacity="0.4"/>')
        self.add(f'<circle cx="40" cy="{self.height}" r="260" fill="#e2e9fa" opacity="0.45"/>')

    def header(self) -> None:
        self.text(64, 65, f'SERMON WORKFLOWS  /  {self.spec["english"]}', size=18, color="#51749a", weight=700, extra='letter-spacing="2"')
        self.text(64, 127, self.spec["title"], size=44, weight=750)
        self.text(65, 170, self.spec["subtitle"], size=21, color="#5b748e")
        self.rect(1398, 44, 138, 42, fill="#ffffff", stroke="#d3e0eb", radius=21)
        self.text(1467, 72, 'README 图', size=16, color="#6a8198", weight=650, anchor="middle")

    def band(self, band: dict) -> None:
        self.rect(band["x"], band["y"], band["w"], band["h"], fill=band.get("fill", "#eef3f7"), radius=24, extra='opacity="0.72"')
        self.text(band["x"] + 24, band["y"] + 35, band["label"], size=18, color="#526b82", weight=700)

    def node(self, node: dict) -> None:
        x, y, width, height = node["box"]
        accent, tint, role = ROLE[node.get("role", "process")]
        self.add(f'<g id="node-{esc(node["id"])}" data-node="{esc(node["id"])}">')
        self.rect(x, y, width, height, stroke="#d4e0ea", radius=22, extra='filter="url(#card-shadow)"')
        self.rect(x, y, width, 9, fill=accent, radius=4)
        self.rect(x + 22, y + 25, 48, 34, fill=tint, radius=12)
        self.text(x + 46, y + 48, node.get("step", ""), size=17, color=accent, weight=750, anchor="middle")
        self.text(x + 84, y + 48, role, size=16, color=accent, weight=700)

        title_lines = wrap(node["title"], (width - 48) / 26)
        title_size = 26 if len(title_lines) == 1 else 24
        for index, line in enumerate(title_lines):
            self.text(x + 24, y + 91 + index * 29, line, size=title_size, weight=700)
        divider_y = y + 111 + (len(title_lines) - 1) * 27
        self.add(f'<path d="M{x + 24} {divider_y}H{x + width - 24}" stroke="#e6edf3"/>')

        body_lines: list[str] = []
        for line in node.get("lines", []):
            body_lines.extend(wrap(line, (width - 48) / 18.5))
        body_size = 18 if len(body_lines) <= 4 else 16.5
        line_gap = 24 if len(body_lines) <= 4 else 20
        start_y = divider_y + 33
        for index, line in enumerate(body_lines):
            self.text(x + 24, start_y + index * line_gap, line, size=body_size, color="#5b748c")
        self.add('</g>')

    def edge(self, edge: dict) -> None:
        points = edge.get("points")
        if not points:
            ax, ay, aw, ah = self.nodes[edge["from"]]["box"]
            bx, by, bw, bh = self.nodes[edge["to"]]["box"]
            if abs(ay - by) < 4:
                points = [(ax + aw, ay + ah / 2), (bx, by + bh / 2)] if bx > ax else [(ax, ay + ah / 2), (bx + bw, by + bh / 2)]
            elif abs(ax + aw / 2 - bx - bw / 2) < 4:
                points = [(ax + aw / 2, ay + ah), (bx + bw / 2, by)] if by > ay else [(ax + aw / 2, ay), (bx + bw / 2, by + bh)]
            else:
                start = (ax + aw / 2, ay + ah if by > ay else ay)
                end = (bx + bw / 2, by if by > ay else by + bh)
                middle = (start[1] + end[1]) / 2
                points = [start, (start[0], middle), (end[0], middle), end]

        dashed = edge.get("dashed", False)
        path = "M" + " L".join(f'{x} {y}' for x, y in points)
        self.add(
            f'<path data-edge="{esc(edge.get("from", ""))}:{esc(edge.get("to", ""))}" '
            f'd="{path}" fill="none" stroke="{"#a47c74" if dashed else "#718da5"}" '
            f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" '
            f'stroke-dasharray="{"8 8" if dashed else "none"}" marker-end="url(#arrow)"/>'
        )
        if edge.get("label"):
            label = edge["label"]
            default = ((points[0][0] + points[-1][0]) / 2, (points[0][1] + points[-1][1]) / 2 - 10)
            label_width = units(label) * 16 + 24
            if len(points) == 2 and points[0][1] == points[1][1] and label_width > abs(points[0][0] - points[1][0]) - 8:
                source = self.nodes.get(edge.get("from"))
                if source:
                    default = (default[0], source["box"][1] - 18)
            lx, ly = edge.get("labelAt", default)
            self.rect(lx - label_width / 2, ly - 23, label_width, 31, fill="#ffffff", stroke="#dfe7ed", radius=11)
            self.text(lx, ly - 2, label, size=16, color="#627c93", weight=650, anchor="middle")

    def footer(self) -> None:
        y = self.height - 132
        self.rect(64, y, 1472, 96, fill="#1d4061", radius=20)
        lines: list[str] = []
        for item in self.spec["footer"]:
            lines.extend(wrap(item, 88))
        for index, line in enumerate(lines[:3]):
            self.text(88, y + 31 + index * 27, line, size=18, color="#e7f1f8", weight=500)
        self.text(64, self.height - 12, f'内容依据：{self.spec.get("calibratedAt", "2026-09-11")} 校准的图稿；本图仅表达职责和门槛', size=14, color="#7890a2")
        self.text(1536, self.height - 12, '实线：主路径    虚线：条件 / 实验 / 返修', size=14, color="#7890a2", anchor="end")

    def four_layers(self) -> None:
        top = 238
        card_width = 350
        xs = [64 + i * 374 for i in range(4)]
        sections = [
            ("输入 / INPUT", "input", 390, 124),
            ("流程 / PROCESS", "process", 526, 190),
            ("模型与工具 / MODELS + TOOLS", "models", 728, 194),
            ("输出与门槛 / OUTPUT + GATE", "output", 934, 155),
        ]
        for index, layer in enumerate(self.spec["layers"]):
            x = xs[index]
            accent, tint = LAYERS[index]
            self.rect(x, top, card_width, 876, stroke="#d4e0ea", radius=22, extra='filter="url(#card-shadow)"')
            self.rect(x, top, card_width, 10, fill=accent, radius=4)
            self.rect(x + 21, top + 24, 43, 43, fill=tint, radius=21)
            self.text(x + 42.5, top + 53, str(index + 1), size=22, color=accent, weight=750, anchor="middle")
            self.text(x + 77, top + 52, f'LAYER {index + 1}', size=16, color=accent, weight=750)
            title_lines = wrap(layer["title"], 13)
            for line_index, line in enumerate(title_lines):
                self.text(x + 22, top + 100 + line_index * 27, line, size=25, weight=700)
            self.text(x + 22, top + 139, layer["english"], size=13, color="#71879b")

            for heading, key, section_y, section_height in sections:
                self.rect(x + 16, section_y, card_width - 32, section_height, fill=tint, radius=13)
                self.text(x + 30, section_y + 26, heading, size=14, color=accent, weight=750)
                content_lines: list[str] = []
                for item in layer[key]:
                    wrapped = wrap(item, 29)
                    content_lines.extend(["• " + wrapped[0]] + ["  " + part for part in wrapped[1:]])
                gap = 20 if len(content_lines) > 5 else 23
                font = 15 if len(content_lines) > 6 else 16
                for line_index, line in enumerate(content_lines):
                    self.text(x + 30, section_y + 53 + line_index * gap, line, size=font, color="#35516a")

        for index in range(3):
            left = xs[index] + card_width + 2
            right = xs[index + 1] - 6
            self.add(f'<path d="M{left} 679 H{right}" stroke="#718da5" stroke-width="3" marker-end="url(#arrow)"/>')

        self.rect(64, 1148, 1472, 122, fill="#e7f0f3", stroke="#cfdee8", radius=20)
        self.text(89, 1187, "一套共享英文；每种目标语言分别完成文字、音频和交付", size=22, weight=700)
        self.text(89, 1222, "中文不是韩语或西班牙语的中转源；上游变更按来源与 locale 精确失效。", size=17, color="#5b748c")
        for idx, (label, fill, color) in enumerate([
            ("zh-Hans", "#fcecf0", "#a54059"), ("ko", "#e9f2ff", "#2e69a7"), ("es", "#eaf6ee", "#23724f")
        ]):
            x = 1020 + idx * 160
            self.rect(x, 1187, 138, 49, fill=fill, stroke=color, radius=24)
            self.text(x + 69, 1219, label, size=18, color=color, weight=700, anchor="middle")

        self.rect(64, 1296, 720, 92, fill="#fff5e7", stroke="#e0cba8", radius=17, extra='stroke-dasharray="8 6"')
        self.text(87, 1331, "独立旁路：Sunday live / live_session", size=19, color="#966820", weight=700)
        self.text(87, 1364, "会后录音若要持久发布，重新从 Layer 1 开始。", size=17, color="#697687")
        self.rect(816, 1296, 720, 92, fill="#f0edfa", stroke="#d2c9e7", radius=17)
        self.text(839, 1331, "跨层编排：Supervisor + 确定性工具", size=19, color="#6d5aa9", weight=700)
        self.text(839, 1364, "Agent 不自授人工批准；legacy complete 不等于四层发布。", size=17, color="#697687")

    def render(self) -> str:
        self.start()
        self.header()
        if self.spec.get("kind") == "four-layer":
            self.four_layers()
        else:
            for band in self.spec.get("bands", []):
                self.band(band)
            for edge in self.spec.get("edges", []):
                self.edge(edge)
            for node in self.spec["nodes"]:
                self.node(node)
        self.footer()
        self.add('</svg>')
        return '\n'.join(self.parts) + '\n'


def render(spec: dict) -> str:
    if spec["name"] not in README_DIAGRAMS:
        raise ValueError(f'Not a README diagram: {spec["name"]}')
    return Drawing(spec).render()


def render_firebase_release() -> str:
    """Draw the README's release boundary, which is not in the older node specs."""
    spec = {
        "title": "从四层制作到 Firebase 正式发布",
        "english": "RELEASE BOUNDARIES",
        "subtitle": "内容批准、代码合并、正式部署和现场验收各有独立证据",
        "footer": [
            "Dev 两段三语片段不自动进入正式站；2026-09-25 正式站仅旧九周中文，未发布内容语言禁用。",
            "合并 main 不等于发布；HTTP / SHA / Range、实体设备和真实现场分别记录状态。",
        ],
        "height": 1100,
        "index": 0,
        "calibratedAt": "2026-09-25",
    }
    drawing = Drawing(spec)
    drawing.start()
    drawing.header()

    def card(x, y, width, height, accent, tint, tag, title, lines, *, dashed=False):
        stroke = '#e0c8ab' if dashed else '#d4e0ea'
        extra = 'stroke-dasharray="8 6"' if dashed else 'filter="url(#card-shadow)"'
        drawing.rect(x, y, width, height, fill=tint if dashed else '#ffffff', stroke=stroke, radius=19, extra=extra)
        drawing.rect(x, y, width, 8, fill=accent, radius=4)
        drawing.text(x + 21, y + 43, tag, size=15, color=accent, weight=750)
        drawing.text(x + 21, y + 82, title, size=22, weight=700)
        drawing.add(f'<path d="M{x + 21} {y + 101} H{x + width - 21}" stroke="#e5edf3"/>')
        for index, line in enumerate(lines):
            drawing.text(x + 21, y + 128 + index * 25, line, size=16, color='#617a92')

    def arrow(x1, x2, y, *, dashed=False):
        drawing.add(
            f'<path d="M{x1} {y} H{x2}" fill="none" stroke="{ "#a47c74" if dashed else "#718da5" }" '
            f'stroke-width="3" stroke-dasharray="{ "8 8" if dashed else "none" }" marker-end="url(#arrow)"/>'
        )

    drawing.rect(48, 205, 1504, 287, fill='#e8f0f5', radius=25, extra='opacity="0.74"')
    drawing.text(69, 243, 'A · 内容生产与 Dev 审核', size=19, color='#4e6f90', weight=700)
    first_row = [64, 364, 664, 964, 1264]
    first_cards = [
        ('#326fb4', '#eaf2fc', 'LAYER 1', '共享英文', ['授权来源与人工范围', '英文、词时轴与 hash', '冻结共享锚点']),
        ('#7460b7', '#f0edfa', 'LAYER 2', '各语言文字', ['从英文直译与独立复核', '每语言独立批准', '保留 revision']),
        ('#c68224', '#fff3e4', 'LAYER 3', '音频与同步', ['授权声音与实测时长', '回转写仅作筛查', '完整听审另行留证']),
        ('#198665', '#e7f7ee', 'LAYER 4', '发布候选', ['页面资产按 locale 绑定', '下载、播放独立核验', '不自动进入正式站']),
        ('#326f8e', '#e9f2f6', 'DEV PREVIEW', 'Firebase Dev', ['两段三语 POC 在此', '浏览器预览与验证', '不等于正式发布']),
    ]
    for index in range(4):
        arrow(first_row[index] + 272, first_row[index + 1] - 7, 359)
    for x, data in zip(first_row, first_cards):
        card(x, 264, 272, 190, *data)

    drawing.text(64, 537, 'B · 代码晋升', size=19, color='#4e6f90', weight=700)
    drawing.rect(64, 557, 706, 126, stroke='#d4e0ea', radius=19, extra='filter="url(#card-shadow)"')
    drawing.rect(64, 557, 706, 8, fill='#7460b7', radius=4)
    drawing.text(89, 608, 'dev → PR / required checks → main', size=24, weight=700)
    drawing.text(89, 650, 'main 合入后，再通过 sync PR 回同步 dev', size=18, color='#617a92')
    drawing.rect(806, 557, 730, 126, fill='#f0edfa', stroke='#d2c8e8', radius=19)
    drawing.text(832, 608, '代码合并 ≠ 内容发布', size=24, color='#6d5aa9', weight=700)
    drawing.text(832, 650, '新周次仍须发布计划、资产批准和部署收据', size=18, color='#617a92')

    drawing.text(64, 729, 'C · 正式内容发布与后续验收', size=19, color='#4e6f90', weight=700)
    last_row = [64, 440, 816, 1192]
    for index in range(3):
        arrow(last_row[index] + 340, last_row[index + 1] - 7, 839, dashed=index == 2)
    card(64, 750, 340, 180, '#198665', '#e7f7ee', 'RELEASE SCOPE', '本次内容范围', ['旧九周中文保持发布', '未发布内容语言禁用'])
    card(440, 750, 340, 180, '#326fb4', '#eaf2fc', 'PRODUCTION', 'main 构建 + 发布计划', ['Firebase Production 部署', '保留原媒体与历史入口'])
    card(816, 750, 340, 180, '#198665', '#e7f7ee', 'ONLINE CHECKS', '线上文件核验', ['HTTP / SHA / MP3 Range', '目录、深链与下载检查'])
    card(1192, 750, 344, 180, '#ad751c', '#fff5e9', 'SEPARATE ACCEPTANCE', '设备与现场', ['实体设备与真实现场', '当前仍需另行验收'], dashed=True)

    drawing.footer()
    drawing.add('</svg>')
    return '\n'.join(drawing.parts) + '\n'
