# 中文证道阅读版质量规范

本文定义中英对照证道阅读版的翻译、编辑、校对和验收标准。阅读版服务于会后连续阅读，不是把逐句字幕简单拼接成 PDF。

## 核心结论

字幕版和阅读版是两种不同的文本产品：

- 字幕版必须跟随时间轴，允许短句和跨 cue 残句。
- 阅读版必须按完整语义组织段落，读者不应感受到字幕切分。
- 更换更强模型只能改变措辞，不能自动解决分段方式错误。
- PDF 排版 QA 只能证明文件没有溢出、缺字或空白页，不能证明中文通顺。

因此，标准流程必须在逐句翻译之后增加独立的“阅读版中文编辑”阶段。

## 2026-07-26 实跑复盘

视频 `0tqIipLfBVQ` 的证道区间为 `00:29:35-01:00:55`。

第一次重新运行 `gpt-5.6-sol / high` 时：

- 英文 299 段中有 107 段发生变化。
- 中文 299 段中有 282 段发生变化。
- 中文字符编辑量很大，但省略号仍为 68 处，与旧版完全相同。
- “你知道”“嗯”“我是说”“好吧”等口语支架仍然打断阅读。

这说明问题不在于模型是否重新措辞，而在于逐段翻译提示要求保留字幕残句。模型把 cue 边界理解为语义缺口，用省略号标记；阅读 PDF 又把这些片段直接拼接，因此保留了字幕痕迹。

加入独立阅读编辑层以后：

- 299 个字幕段重新组合为 39 个完整语义段落。
- 省略号从 68 处降为 0。
- 指定的无意义语气词和口语支架降为 0。
- 中文由 9,410 字符精简为 8,689 字符，减少 7.7%。
- 中英文字符总比例为 0.307。
- 最终 PDF 为 36 页，全部页面通过渲染检查。

## 标准生成流程

```text
英文 ASR
  -> 英文字幕校正
  -> 逐 cue 中文字幕翻译
  -> 按完整英文句子重新划分语义段落
  -> 第一轮中文阅读编辑
  -> 第二轮中英对照校对
  -> 文本质量门禁
  -> 生成中英对照 PDF
  -> PDF 排版 QA
  -> 全页渲染阅读检查
```

### 第一轮：阅读编辑

目标是把字幕文本改写成可连续阅读的中文：

- 以完整英文语义为准，逐句保留事实、论点、引用、幽默和神学含义。
- 把跨 cue 残句连接成完整句子。
- 删除没有语义作用的“嗯”“呃”“你知道”“我是说”“好吧”等口语支架。
- 将有意义的口头过渡改写成简洁的书面连接。
- 不因字幕边界使用省略号。
- 不总结、扩写、添加解释或补充讲员没有说过的内容。

### 第二轮：双语校对

第二轮不能只是重复第一轮提示。校对模型必须重新对照完整英文，检查：

- 是否遗漏或添加实质内容。
- 否定、强调、因果和不确定性是否准确。
- 引语、数字、人名、书卷名和经文位置是否准确。
- `神`、`主`、`祂`、`圣灵`、`三位一体`、`道成肉身`等术语是否统一。
- 段落开头和结尾是否完整。
- 中文是否仍残留字幕式断裂或英文普通词。

## 自动质量门禁

`scripts/build_sermon_reading_edition_with_openai.py` 的最终报告必须为 `pass`。

硬性失败项包括：

| 门禁 | 合格标准 |
|---|---|
| `ellipsis` | 非原文必要停顿造成的省略号为 0 |
| `oral_fillers` | 指定无意义语气词为 0 |
| `dangling_fragments` | 不以逗号、冒号、破折号等悬空结束 |
| `unbalanced_quotes` | 中文引号成对 |
| `missing_terminal_punctuation` | 每个阅读段落完整收尾 |
| `repeated_punctuation` | 无连续中文标点错误 |
| `source_term_coverage` | 英文出现的关键书卷和神学术语在中文中得到正确表达 |
| `unexpected_english_tokens` | 除批准的专名外，不残留普通英文词 |
| `length_ratio_outliers` | 单段中英文长度比例没有明显异常 |

报告还应记录：

- 中英文字符总数和总体比例。
- 平均及最大中文段落长度。
- 省略号总数。
- 含语气词的段落数量。

## PDF 验收

文本门禁通过后才能生成最终 PDF。PDF 仍需单独检查：

1. `.qa.json` 状态为 `pass`。
2. `allPagesChecked` 为 `true`。
3. 无溢出、空白页、缺字方框、超长行或孤立尾页。
4. 中文段落和英文原文位于同一阅读块中。
5. 时间范围可读，视频链接偏移正确。
6. 首页、内容密集页、跨页段落和最后一页必须以原尺寸查看。
7. 全部页面渲染为 PNG 后检查，而不是只看 PDF 文本抽取结果。

## 推荐命令

先从已完成的字幕 pipeline 生成阅读编辑产物：

```bash
.venv/bin/python scripts/build_sermon_reading_edition_with_openai.py \
  --source-pipeline <pipeline_outdir> \
  --outdir <pipeline_outdir>/reading-edition-v2 \
  --provider codex \
  --model gpt-5.6-sol \
  --reasoning-effort high \
  --batch-size 10 \
  --workers 1 \
  --passes 2
```

然后生成最终 PDF：

```bash
.venv/bin/python scripts/render_mobile_pdf_from_srt.py \
  --layout reading \
  --input <pipeline_outdir>/reading-edition-v2/sermon_zh_reading_revised.srt \
  --secondary-input <pipeline_outdir>/reading-edition-v2/sermon_en_reading_revised.srt \
  --out output/pdf/<date>-<video_id>-sermon-zh-en-reading-revised.pdf \
  --title '<sermon title>' \
  --subtitle '<date> 中英对照阅读版（连贯修订）' \
  --source-url '<canonical YouTube watch URL>' \
  --source-offset-seconds <sermon start seconds>
```

如果使用 OpenAI API，把 `--provider codex` 改为 `--provider openai`，并确保运行环境提供 `OPENAI_API_KEY`。

## 人工阅读检查

自动门禁不能代替最终通读。人工检查时重点关注：

- 一口气读完一段时，是否需要猜测被省略的主语或宾语。
- 段落之间是否出现重复、跳跃或突然换题。
- 讲员的口语幽默是否保留，但没有保留无意义停顿。
- 神学陈述是否忠于英文，而不是由编辑自行“修正”讲员观点。
- 引用圣经时是否清楚区分讲员转述和直接引用。
- 祷告、人称和神圣代词是否统一。

只有文本门禁、PDF QA 和人工全页阅读检查都完成后，阅读版才可标记为最终版。
