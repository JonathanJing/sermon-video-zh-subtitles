# 和合本经文库与精确取文

同行制作中的直接经文引文，从固定版本取字；讲员的解释、概述和应用仍是证道翻译。经文出处识别与引文边界识别由上游结合英文听写及语音处理，本模块负责按确认的出处取文、拒绝不确定的范围并核验文字。不能因提到一个章节便自动把整章加入证道。

## 固定来源

- 版本：新标点和合本（简体，神版），eBible ID `cmn-cu89s`。这是已核验来源的具体版本；没有声称等同于其他网站或出版社的和合本标点、排版版本。
- [eBible 版本详情与 Public Domain 声明](https://ebible.org/bible/details.php?id=cmn-cu89s)，[官方 VPL 下载](https://ebible.org/Scriptures/cmn-cu89s_vpl.zip)。下载包内的 `cmn-cu89s_about.htm` 也标示 Public Domain，来源更新日期为 2021-10-15。
- 使用仓库已有的 [经文 JSON](../data/scripture/cmn-cu89s.json)，并新增[固定来源清单](../data/scripture/cmn-cu89s.provenance.json)。生产读取不需要联网，也不依赖 ignored 目录中的唯一文件。
- 2026-09-13 实际重新下载并逐条比较：66 卷、1,189 章、31,021 条 VPL 经文记录，与现有 JSON 全部一致。既有索引仅把全角空格及连续空白规范成一个空格；经文用字、标点、方括号内的字均保留。

ZIP SHA-256 为 `8c9969ea5659835c132f9ce93101b948cd04edf298ca507ae50bbe77858d5027`；VPL 文本 SHA-256 为 `f9264d61e7abc7cda2e74ed465b0f99fa64038bcdc7e9af1d4dcc9e80e2db705`。规范 JSON SHA-256 为 `9c43dacae44a16ce5fb56bb42ba3afde9f8facfe1eaf1b9ebba6a9b76c8cb80f`。完整清单还记录原 JSON 文件 hash、空白规范化和取文约束。

来源 VPL 将部分相邻节合写在第一个节号下，例如创世记 24:29 包含 29–30 的文字，却没有独立的 30 号记录。因此 31,021 是**记录数**，不能说成独立覆盖的通常节数。查询缺号或包含缺号的范围会报错，交回来源核对；不自动拆字、复制邻节或省略缺节。本篇使用的启示录 1:1–20 均有独立记录。

## 接入接口

```python
from scripts.cuv_scripture import CuvLibrary, parse_reference, prepare_spoken_input

library = CuvLibrary.from_path()
ref = parse_reference("启示录第一章第八节")
quote = library.lookup(ref)
# quote["canonicalRef"] == "REV 1:8"
# quote["text"] 是核定的显示原文；textSha256 与 source 记录原文及来源身份。
speech = prepare_spoken_input(quote["text"])
```

`parse_reference()` 支持 66 卷中英全名、常用缩写、标准代码，以及 `First Peter chapter two verses nine through ten` 等明确口述。返回不可变 `Reference(book, chapter, start_verse, end_verse)`。`verse nine`、`第九节` 或 `12:9` 仅在传入明确 `context` 时解析；缺上下文、只有章号、跨章范围或逆序范围会拒绝。它不是从任意讲道句子自动找出处的模型。

`lookup("REV 1:17", excerpt="不要惧怕！我是首先的，我是末后的，")` 支持节选；`excerpt` 必须是所选范围中唯一出现的连续原文子串。不能凭“上半节 / a”猜边界，不能提供意译作为经文。返回完整取文、选中文字、字符起止、各节原文、版本和来源 hash。跨章或非连续节须上游拆成分别核验的引用；不能静默扩充范围。

`verify_text(ref, text, excerpt=False)` 检查整节原文；明确节选时传 `excerpt=True`。改变一个字或标点也不通过。`CuvError` 表示来源身份或引用校验未通过，上游应保留待核对状态并停止把它标成合格经文。

`prepare_spoken_input()` 独立返回显示文字和发音输入及各自 hash。它仅去除空白和 `[ ]` 符号，**保留方括号内的字**，例如 `[圣]灵` 读作“圣灵”。不替换“神 / 上帝”，不改写词句，不对显示原文回写。更进一步的专名发音字典必须作为独立、有记录的音频处理，不能把发音字冒充经文原字。这个变换本身不证明合成音频没有漏字或错读。

## 命令与核验

```bash
# 默认读取仓库固定版本，离线核验。
.venv/bin/python scripts/cuv_scripture.py verify
.venv/bin/python scripts/cuv_scripture.py query 'REV.1:8' --spoken-input
.venv/bin/python scripts/cuv_scripture.py query 'verse nine' --context 'REV 1:8'

# 来源 ZIP 只保存到 ignored artifacts；源内容变更会拒绝，不自动升级版本。
.venv/bin/python scripts/cuv_scripture.py build --download
.venv/bin/python scripts/cuv_scripture.py verify \
  --archive artifacts/cuv-scripture/cmn-cu89s_vpl.zip

# 真正的经文与来源检查，不调用模型或重生成音频。
.venv/bin/python -m unittest tests.test_cuv_scripture -v
```

`build` 复用现有索引格式，从 hash 固定的 VPL 重建；结果必须再次匹配固定内容 hash。缺失、错误、不同来源 ZIP 或不同正文都返回非零退出码。它不会覆盖已有但内容不同的目标文件。

这些检查保证所取**文字**来自固定经文库，不证明上游选对了讲员引文范围，也不等于人工听审。重做已发布的中文与配音时，新文字和新音频须保留新的 hash、审核状态和发布记录；旧审核不能自动覆盖新版本。共享系列名称继续遵循[系列名称表](series-terminology.zh.md)。
