# `gpt-transcribe` 阅读版 PDF 生产审核（2026-07-31）

## 审核结论

结论：**PASS，可以继续作为阅读版 PDF 的生产默认流程。**

本次使用已获批准上传的公开讲道音频，按生产入口完整执行：

1. 从完整视频音频中截取已确认的证道窗口 `00:29:35`–`01:00:55`；
2. 使用 `gpt-transcribe`、上下文 prompt、keywords 和 `languages=["en"]` 生成英文参考稿；
3. 使用 `gpt-5.6` 生成中文初稿；
4. 使用 `gpt-5.6-sol`、`high` reasoning、两遍编辑生成中英阅读版；
5. 通过阅读质量门禁和 PDF QA 后渲染最终 PDF；
6. 渲染并人工检查全部 38 页。

阅读模式全程未调用 `whisper-1`。`summary.json` 中：

- `referenceAsr = gpt-transcribe`
- `timingAsr = null`
- `englishCorrection = null`
- `outputMode = reading`
- `timingPrecision = synthetic_reading_layout_only`

因此，这份产物的时间标签只用于阅读版段落定位，不得作为同步字幕时间轴使用。

## 转录来源与完整性

| 检查项 | 结果 |
|---|---:|
| 音频长度 | 1,880 秒 |
| `gpt-transcribe` 请求数 | 1 |
| 检测语言 | `en` |
| 英文单词数 | 5,547 |
| 新旧英文转录词序列相似度 | 0.9900 |
| 初始阅读段落 | 45 |
| 最终阅读块 | 39 |
| 英文空段 | 0 |
| 中文空段 | 0 |
| 段落重叠 | 0 |
| 翻译 ID 不匹配 | 0 |

请求 provenance 已记录：

- `audioSha256 = 4684d57b0f86667896e7e3419ca916a6905ad2dbdc14062b455228f93c707879`
- `promptSha256 = 86e2fb57ce05dfe549d4c20787a2d05cb21bc88dafb00b576f35b0fb73e8a5bc`
- `keywordsSha256 = 5dd5bb187802265fae4a981f784e1b00ffecfcaed7b1675fdea7350ec2687cce`
- `languages = ["en"]`

抽查确认 `Philippians`、`Jesus`、`Trinity`、`incarnation`、`Holy Spirit`、`Oura` 和 `John Stott` 等关键内容进入最终中英阅读版。

## 审核中发现并修复的问题

第一次运行被阅读质量门禁阻止，报告显示第 11 块存在一个 `oral_fillers`：

> 你知道这说明什么吗？这说明我昨晚睡得很好。

这是有语义作用的完整提问，并非“你知道，……”式口语填充词。旧检测表达式会匹配所有“你知道”前缀，属于 QA 误报。

修复内容：

- 只有“你知道”或“你知道吗”在该短语处结束、后接停顿符号或空白时，才计入口语填充词；
- “你知道这说明什么吗？”这类后接宾语或完整疑问内容的句子不再误报；
- 阅读质量报告新增 `qualityRuleVersion = sermon-reading-edition-quality-v2`；
- 增加回归测试，保留对真正口语填充词的 fail-closed 检查。

修复后重新运行，阅读质量报告为 `pass`：

- 省略号：0
- 口语填充词：0
- 残句：0
- 引号不平衡：0
- 缺少结尾标点：0
- 重复标点：0
- 术语覆盖错误：0
- 非预期英文词：0
- 中英长度比例异常：0

## PDF 审核

| 检查项 | 结果 |
|---|---:|
| PDF 页数 | 38 |
| 页面尺寸 | 390 × 844 pt |
| 文件大小 | 478,695 bytes |
| PDF SHA-256 | `6fe94720f09742aac19dff829bb892fdd3bc202a08b58968f508d8ed99521ee2` |
| 空白页 | 0 |
| 页面溢出 | 0 |
| 字形缺失标记 | 0 |
| 长行风险 | 0 |
| 孤行风险 | 0 |
| PDF QA | `pass` |

人工检查了全部 38 页：

- 封面、标题、日期、时间标签、页眉、页脚和页码正常；
- 中文字体完整，没有方框、乱码或缺字；
- 中英段落对应清楚，没有文本重叠或裁切；
- 页面 38 正常包含最后一段正文与结束祷告；
- 没有空白页、异常分页或正文侵入页脚。

本地审核产物：

`artifacts/model-evals/2026-07-31-gpt-transcribe-reading-pdf-audit/work-root/2026-07-26/0tqIipLfBVQ/pipeline/sermon_zh_en_reading.pdf`

`artifacts/` 按仓库策略保持忽略，不把完整音频、逐字稿或 PDF 二进制提交到 Git。

## 生产判断

- 阅读版 PDF：继续默认使用 `gpt-transcribe`，不调用 Whisper。
- 同步字幕：只有显式选择 `output-mode=subtitles` 时，才使用 `whisper-1` 的时间轴。
- 证道起止：可以由完整音频时间线检查流程提供候选窗口，但仍保留人工确认边界。
- 发布门禁：继续要求英文/中文内容 QA、两遍阅读版编辑、PDF QA 和完整页面视觉审核。
