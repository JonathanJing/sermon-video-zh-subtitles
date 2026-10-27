# 从 PDF 到中文重排：抽取、翻译、重排与合成

本文记录一条可重复的流程：把一本**有文字层的电子版 PDF**（矢量文字 + 图片）拆出文字与版式信息，按页对齐改写成中文，再按原版式重新合成 PDF。流程以《启示录》系列手册中文版（194 页，7 × 10 英寸）的实际制作为例；生成脚本在 `artifacts/reference/revelation-series-guide/zh-edition/`，产物是 `artifacts/reference/revelation-series-guide/revelation-series-guide.zh-Hans.pdf`。

先说明边界：**从 PDF 出发无法做到 100% 复刻原排版。** PDF 只保存绘制结果，不保存 InDesign 的母版、段落样式、绕图、基线和段落规则；中文的字宽、行高、标点又和英文不同，必然要重新断行和重新平衡。要真正“保留原排版”，唯一可靠的办法是拿到 IDML／INDD 或原始 AI／EPS，在源文件里换字。本流程的目标是：**保留页序、版心、字号层级、图文关系、页眉页脚和跨页节奏，把中文排进去并保证不裁切。**

## 0. 先选路线

| 手上有什么 | 走哪条路 | 结果 |
|---|---|---|
| IDML / INDD 源文件 | InDesign 里替换文本、换中文字体、调段落样式、更新目录 | 最接近原版；可继续由设计同工微调 |
| 矢量文字 PDF（能选中文字） | 本流程：抽取 → 翻译 → HTML/CSS 重建 → Chrome 打印 | 版式高度接近，页数可能变 |
| 扫描 PDF（整页图片） | `ocrmypdf` 做 OCR → 本流程重建；或原图垫底 + 文字覆盖 | 先解决文字层，再谈排版 |
| 只有几页、以图为主 | 逐页手工重排（Figma／InDesign／HTML 均可） | 不必上流水线 |

判定文字层：

```python
import pymupdf
doc = pymupdf.open(src)
print("pages", len(doc), "size", doc[0].rect)
for i, page in enumerate(doc[:5]):
    print(i, "chars", len(page.get_text()), "images", len(page.get_images(full=True)),
          "drawings", len(page.get_drawings()))
```

`chars` 长期为 0、`images` 每页 1 张，基本就是扫描件；`chars` 有内容、`drawings` 很多，才是可重建的矢量排版。顺便记录页面尺寸（如 504 × 720 pt = 7 × 10 in）、页数、出血和页脚位置，这些是后面所有版式的基准。

## 1. 抽取文字和版式坐标

不要只复制文字。要同时记录**每一行文字的位置、字体、字号、颜色**，否则重建时只能猜。`page.get_text("dict")` 给出 block → line → span 的层级；`bbox` 是 PyMuPDF 坐标（原点左上，y 向下，单位 pt，与原生 PDF 的左下原点相反）。

```python
import json
rows = []
for i, page in enumerate(doc):
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text:
                continue
            s = line["spans"][0]
            rows.append({
                "page": i,
                "text": text,
                "bbox": [round(v, 1) for v in line["bbox"]],
                "font": s["font"],
                "size": round(s["size"], 2),
                "color": f"#{s['color']:06x}",
            })
json.dump(rows, open("build/lines.json", "w"), ensure_ascii=False, indent=1)
```

同时把每一页渲染成图，作为视觉参照；翻译和重排时以图为准，以坐标数据为辅：

```python
for i, page in enumerate(doc):
    page.get_pixmap(dpi=110).save(f"build/pages/p{i:03d}.png")
```

图片单独导出。注意 CMYK／DeviceN 会报 “unsupported colorspace”，要先转 RGB：

```python
for xref, *_ in page.get_images(full=True):
    pix = pymupdf.Pixmap(doc, xref)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    pix.save(f"assets/img/x{xref}_{pix.width}x{pix.height}.png")
```

**容易踩的坑**

- 多栏／表格的文字顺序会乱：提取顺序按内容流，不按视觉顺序。不要直接拿 `get_text()` 当正文；用 bbox 做列切分，或按页人工校对。
- 页眉、页脚、页码会混进正文；按 y 坐标排除（例如 `bbox[3] > 660` 或 `< 60`）。
- 连字、软连字符、`\xa0` 要清洗；中文引号要统一成 “ ”。
- 图片里如果已经烧进英文（地图、图表、冰山图），抽出图片也改不了字，只能重画或回原图改。

## 2. 建立“页 → 内容”的映射

把原书按页拆成结构化的页记录：每页是什么类型（封面、经文、正文、表格、图版、生活小组、笔记），对应哪段译文，哪些页要合并或拆分。

做法：

1. 翻译按**原书页序**切分，每页一段，保留标题、小标题、引文、表格、脚注、图注。
2. 给每页打 `type` 标签，例如 `cover / toc / letter / essay / scripture / notes / table / feature / lg / notes_blank / divider / appendix`。
3. 记下每页的**容量**：正文页约多少字、经文页约多少字、表格最多几行。后面靠这个做分页。
4. 原书页码和 PDF 页序不是一回事（封面是否编号、跨页是否算两页），单独维护 `printed_page ↔ pdf_index`。

译文本身建议单独存成 JSON 或 Markdown，每页一个 key，不要把译文塞进排版脚本。这样术语校对、替换和重跑互不影响。

## 3. 翻译与改写

- **术语先行**：建一张术语表（书卷名、神学词、系列标题、人名），全篇统一；本仓库用 [系列名称表](series-terminology.zh.md)。
- **经文用公版**：和合本 1919 已进入公有领域，可直接按经节范围取文（本仓库 `cuv-1919-revelation.json`）。不要重译经文，也不要混用不同译本。
- **保留结构标记**：小标题、引文出处（书卷 章:节）、表格表头、图注、脚注编号、页码引用，都要跟着译文走；中文版页码变了，正文里的“见第 162 页”必须改成新页码或改成“见书末附录”。
- **长度预期**：同样内容中文通常比英文短，但中文标点占满宽、行高更大；实际排版长度要按字体试排后再定，不能按字数估算。
- **机器翻译要标注**：未人工审校的译本，在版权页和封底写清楚“机器翻译、非官方、仅供个人使用”，不要伪装成官方译本。

## 4. 重建版式

### 4.1 用 HTML/CSS 定义“一页 = 一个固定盒子”

打印用 CSS 的物理单位，页面尺寸直接写英寸或 pt：

```css
@page { size: 504pt 720pt; margin: 0; }
.page {
  width: 504pt; height: 720pt;
  position: relative; overflow: hidden;
  page-break-after: always;
}
```

每个 `.page` 内部用绝对定位放版心内容（`left/right/top/bottom` 用 pt），页眉、页脚、页码也是绝对定位。跨页的背景图用 `position:absolute; inset:0`，`object-fit: cover`。

一套版式系统至少要有：

- 版心：左右 45 pt、上 45 pt、下 42 pt（按原书量出来改）；
- 字号层级：大标题／章节标题／小标题／正文／图注／页脚；
- 页眉页脚：左书名、右页码，或按章节写 running head；
- 栏数与行高：正文单栏或双栏，经文单栏大字；
- 颜色：纸色、墨色、强调色、线色，从原书取色（见下）。

取原书颜色不要靠眼睛，直接采样：

```python
pix = doc[15].get_pixmap(dpi=72)
print(pix.pixel(250, 350))   # (r, g, b)
```

### 4.2 文字流与固定页的冲突

`overflow: hidden` 会**静默裁掉**放不下的文字。这是整条流程最大的风险：PDF 看起来正常，实际上少了半页。三条防线：

1. 每页内容在生成阶段就按容量切分（经文按节切、正文按块切），不要依赖浏览器自动流；
2. 打印后检查每页文字的最大 y／x 是否越过版心（见第 6 节）；
3. 对关键内容做完整性比对（例如全部经节首句是否都出现在 PDF 文本里）。

如果内容放不下，宁可**加页**，不要缩到 6 pt 硬塞。

### 4.3 图片与图表

- 照片、插画：从 PDF 导出原图，按版心裁切；注意原图可能带英文图注，能裁就裁，不能裁就用中文图注重排（加深色渐变底）。
- 地图、时间轴、对照图：如果原图是矢量且能拿到 AI/EPS，回原文件改字最好；拿不到就用 SVG 重画。重画时保留原图的视觉语言（线宽、圆点、箭头、配色），不要换成另一套风格。
- 图里的英文不要用“贴一块白条 + 中文”覆盖，除非底色是纯色；半透明图、渐变图上一眼就假。

### 4.4 目录与页码：两遍生成

目录在正文之前，但页码要等全文排完才知道。做法：

1. 先把所有页按顺序生成，记录每个章节／每周首页的**实际 PDF 页序**；
2. 用这个页序渲染目录页（目录占固定页数，不能因为填数字而改变分页）；
3. 再整体打印。

目录里同时给出“周标题”和子项“讲道经文／生活小组”，子项页码来自同一张表，避免手抄出错。PDF 书签用同一份锚点生成：

```python
doc.set_toc([[level, title, page_index + 1], ...])
```

## 5. 中文字体与排版

### 5.1 字体

思源宋体／思源黑体（Noto Serif SC / Noto Sans SC）免费、可商用，适合正文和经文。**不要直接把可变字体（variable font）交给 Chrome 打印**：Chrome 会把字形转成 Type3，印前不友好。先用 fontTools 生成静态字重实例：

```bash
fonttools varLib.instancer NotoSerifSC.ttf wght=400 -o Serif-Regular.ttf
fonttools varLib.instancer NotoSansSC.ttf  wght=700 -o Sans-Bold.ttf
```

CSS 里按字重分别 `@font-face`：

```css
@font-face { font-family:"Song"; src:url("Serif-Regular.ttf"); font-weight:400; }
@font-face { font-family:"Song"; src:url("Serif-Bold.ttf");    font-weight:700; }
@font-face { font-family:"Hei";  src:url("Sans-Light.ttf");    font-weight:300; }
```

打印后检查嵌入字体：`page.get_fonts(full=True)` 里正文应是 `Type0` + `CIDFontType2`，而不是 `Type3`。例外是 `-webkit-text-stroke` 描边的文字（例如分隔页的大号空心数字），Chrome 会把它转成一个 Type3 轮廓字体；它是矢量的，印刷没问题，但如果要求全文件零 Type3，就把描边数字改成 SVG。

### 5.2 中文段落规则

```css
.body {
  font-weight: 300; font-size: 9.25pt; line-height: 1.98;
  text-align: justify; text-justify: inter-ideograph;
  line-break: strict;          /* 中文断行禁则：标点不出现在行首/行尾 */
  word-break: normal;
  text-spacing-trim: trim-start; /* 行首标点挤压（Chrome 支持） */
}
```

- 中文不缩进、段间留白，还是首行缩进 2 em，要和原书体例一致；杂志式版式通常不缩进。
- 经文行高给到 1.95–2.0，字号 11.5–13 pt，按页面容量定；标题和正文用同一套栅格。
- 数字、英文缩写用同一字体的拉丁部分即可，不要混排另一套西文字体，容易基线不齐。
- 直引号先统一成中文引号，再排版；`"..."` 与 `“...”` 混用最显眼。

## 6. 合成 PDF

Chrome 无头打印 HTML 是最省事、对 CSS 支持最完整的方式（比 WeasyPrint 更接近浏览器排版）：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --no-sandbox --disable-gpu --disable-crash-reporter \
  --user-data-dir=build/chrome-profile --no-first-run \
  --allow-file-access-from-files --font-render-hinting=none \
  --virtual-time-budget=20000 \
  --no-pdf-header-footer \
  --print-to-pdf=out/book.pdf \
  "file:///绝对路径/build/book.html"
```

要点：

- `--no-pdf-header-footer` 关掉 Chrome 自带的日期／URL 页眉页脚；
- `--allow-file-access-from-files` 允许加载本地字体和图片；
- `--virtual-time-budget` 给字体加载留时间；
- `--no-sandbox` 只在沙箱环境导致 Chrome 崩溃时加，正常桌面不必加；
- 页面尺寸以 CSS `@page` 为准，不要在命令行再写一套 paper size。

打印后用 pymupdf 收尾：写元数据、书签、压缩、替换源文件（pymupdf 不允许直接覆盖已打开的文件，先存临时文件再 `os.replace`）。

```python
doc.set_metadata({
    "title": "……",
    "author": "……",
    "subject": "……",
})
doc.set_toc(toc)
doc.save(out + ".tmp", garbage=4, deflate=True, clean=True)
os.replace(out + ".tmp", out)
```

## 7. 校验清单（每次都要跑）

```python
# 1) 页面尺寸一致
assert {(round(p.rect.width), round(p.rect.height)) for p in doc} == {(504, 720)}

# 2) 没有文字越过版心（页脚除外）
for i, page in enumerate(doc):
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text or "系列手册" in text:   # 空行、页脚
                continue
            x0, y0, x1, y1 = line["bbox"]
            assert x1 <= 470 and y1 <= 690, (i, text[:20], x1, y1)

# 3) 关键文本完整：按去空白后的全文比对
full = re.sub(r"\s+", "", "".join(p.get_text() for p in doc))
missing = [k for k, v in expected_verses.items() if re.sub(r"\s+", "", v)[:12] not in full]

# 4) 目录页码指向的页面确实是对应章节
for folio, needle in toc_expectations:
    assert needle in doc[folio + 1].get_text()

# 5) 字体嵌入：正文页应为 Type0；带 -webkit-text-stroke 的描边字可能被转成 Type3
bad = [(i, f[3]) for i, p in enumerate(doc) for f in p.get_fonts(full=True) if f[2] == "Type3"]
print("Type3 pages:", bad)   # 期望只在描边数字页；若正文页出现，需改用静态字重或 SVG

# 6) 图片分辨率：按放置尺寸换算，正文图 ≥ 300 dpi，全幅底图 ≥ 200 dpi
```

再加人工检查：

- 打印或看 100% 缩放 PDF：标题有没有压图、页脚有没有和正文打架、跨页图片有没有接缝；
- 中英对照通读一遍，重点看术语、经节、数字、人名、页码引用；
- 实际打印一两本，检查字号、页边距、装订线（内白边要留够）。

## 8. 文件组织

```
zh-edition/
  src/text.py        # 源文本：逐页译文、经文、周次结构
  src/front.py       # 卷首与导论页
  src/weeks.py       # 周单元与经文分页
  src/appendix.py    # 附录与版权页
  src/common.py      # 页面壳、转义、块解析
  assets/theme.css   # 版式
  assets/fonts/      # 静态字重
  assets/img/        # 导出的图片与重绘素材
  build/             # 生成的 HTML、PDF、页面图（可删）
  out/               # 最终 PDF
  README.md          # 构建说明
```

生成、检查、发布分开：`build/` 和 `out/` 属于可再生文件，不要提交；最终 PDF 放 `artifacts/`（本仓库约定为不进 Git 的产物目录）。

## 9. 这套流程做不到的事

- **不能保留原 InDesign 的段落规则和母版**。换字后中文的断行、孤行、跨页平衡都要重新调；有些页会显得空，有些页要拆。
- **不能改图片里的英文**。地图、图表必须回原图或重画；照片里的字只能裁或遮。
- **不能替代人工翻译审校**。机翻 + 术语统一只能做初稿。
- **不能替代印前检查**。字体嵌入、颜色空间（RGB → CMYK）、出血、装订线、纸张，都要在设计软件或印厂流程里过一遍。

## 10. 最小可行版本（半天内跑通）

1. 取 PDF 前 10 页，导出文字坐标和页面图；
2. 手写 3 个模板：封面、正文、图版；
3. 翻译 3 页，排进 HTML，Chrome 打印；
4. 用第 7 节的脚本检查裁切、字体、页脚；
5. 跑通后再批量：先做目录和页序表，再逐页套模板。

本仓库的完整实例见 [`zh-edition/`](../artifacts/reference/revelation-series-guide/zh-edition/)；重建命令写在它的 README 里。
