# Gemini 全篇 sidecar ＋ GPT-6 裁判实测（2026-09-20）

## 结论

Gemini sidecar 对“主要仍在讲解”有实用价值，但目前不够可靠，不能自动控制字幕、
翻译或中文播放速度。适合保留为隐形审阅提示：告诉操作员哪里可能进入读经、切换主题、
出现停顿或模型没有覆盖；所有边界仍需词时间约束和人工听审。

GPT-6 对 411 个句子候选逐句裁判后，机器证据支持 321 句（78.1%），明确反驳 29 句
（7.1%），待审 61 句（14.8%）。这是机器裁判支持率，不是准确率。裁判没有音频输入，
所以没有把任何结果升级成人工 Gold 或发布资格。

## 冻结输入

- 源：`2026-09-20-resi`，完整讲道 1,940 秒，完整视频偏移 1,789 秒。
- 源视频 SHA-256：`728f864e92ea08dbce249249369016e0fee47950ec4e6dcb60cd6d83185e8caf`。
- 39 个真实音视频窗口：约 60 秒一窗，相邻重叠约 10 秒。
- 完整候选词时间：5,478 词；62 个阅读块。边界为机器对齐并经模型复核，不是人工 Gold。
- 句子：从阅读版标点切分，再映射到候选词时间。411 句中 393 句达到词匹配门槛，
  18 句保留 `timingStatus=uncertain`。
- 独立声学摘要：`ffmpeg silencedetect noise=-35dB:d=0.25`，239 个低能量／静音区间；
  只能支持“存在声学间隔”，不能证明修辞意图。

主要冻结产物：

- `full-corpus-manifest.json`：`1cd19e5600db49d4a5f7bd69aeb91412c89071ab494365b095728ec7241b4014`
- `full-sidecar.json`：`7f9cf1fbd662ec0b583059ff9d798276838d4f6100f97f37c74d9550c2891d71`
- `gpt6-judge-input.json`：`f0ac21e03b156ce3ea2507e4876340be0c62c190efdd20840500dae1b2759d75`
- `gpt6-judge.json`：`4dca91646996422d42b2e1d3696ed74b0affabe9929674b2bf4e7f5cd4348975`

## Gemini 全篇执行

模型为 `gemini-3.8-live-extended-thinking`。Live 输入按 100 ms 发送 16 kHz PCM，
视频按 1 FPS 抽帧送入模型。最终 39/39 窗口都有满足全篇合同的结果：音频、视频均
`matched`；transcript 35 窗 `matched`、4 窗 `partial`。

- 选中 29 个主 attempt、10 个 retry；其中一个主响应从保留内容无损重解析。
- 1300 秒窗口需要 `retry2`；850 秒窗口因提供了 transcript 却自报 `not_provided`
  而追加重试。原始失败、响应和 attempt 都保留。
- 选中结果累计模型延迟 2,819.725 秒；中位数 65.991 秒，最大 166.218 秒。
- 窗口级原始事件：讲解 65、读经 19、过渡 18、其他 4；停顿候选 164。
- 映射到 owner window 后：362 句讲解、15 句读经、9 句过渡、8 句其他，另有
  17 句没有事件覆盖。相邻同类句子合并为 36 个候选事件。

重叠窗口不会互相投票：每句只取句子中心最接近的 owner window。少数长句跨出 owner
window 末端，GPT-6 将其记为窗口证据覆盖风险，而不是擅自改边界。

## GPT-6 盲裁

GPT-6 Astra 只读取盲化候选：句子、候选类别、候选词时间、真实 contact sheet 和独立
声学摘要。Gemini 的模型名、置信度、自述理由和原始响应全部隐藏。四批共实际查看
39 张 contact sheet，411 个 sentenceId 一对一覆盖，合并校验无遗漏、无重复。

| Gemini 句子候选 | 支持 | 反驳 | 待审 | 合计 |
|---|---:|---:|---:|---:|
| `sermon_explanation` | 312 | 12 | 38 | 362 |
| `scripture_reading` | 8 | 4 | 3 | 15 |
| `transition` | 1 | 5 | 3 | 9 |
| `other` | 0 | 8 | 0 | 8 |
| 无候选 | 0 | 0 | 17 | 17 |
| **合计** | **321** | **29** | **61** | **411** |

边界裁判支持 378 句，33 句保留不确定。经文出处裁判为支持 42、反驳 3、待审 16、
不适用 350。窗口结论为 `candidate_supported` 10、`review_required` 12、`reject` 17；
`reject` 表示至少有一条独立证据明确反驳，不表示整窗内容全部错误。

850 秒窗口重试后，10 句中只有 `b26-s002` 的画面文字从换行改为空格，语义和所有
候选字段不变。GPT-6 复看图片并记录 `judgmentChanges=[]`、
`batch2JudgmentsRemainValid=true`。

## 代表性问题

1. **过渡不稳**：9 个 `transition` 句只有 1 个得到支持；欢迎语、经文出处引介、
   “This is God’s word”和起立敬拜指令容易被吞进讲解或读经。
2. **混合句被粗分**：读经中夹着解释时，整句容易被标成 `scripture_reading`；例如
   “So this is all about your mind: teaching and deception.” 实为解释。
3. **出处会误绑**：Sardis 3:4 曾关联成 Revelation 2:4；“Revelation chapter 4 and 5”
   被写成 `Revelation 4:5`；Genesis 2–3 的第二章若没有明示，GPT-6 不允许靠常识补齐。
4. **`other` 不可直接采用**：8 个 `other` 候选全部被裁判反驳，主要是把 hidden manna
   的连续解释错归其他。
5. **事件覆盖有空洞**：17 句没有 Gemini 事件覆盖，必须显式保留为待审，不能默认继承
   前后标签。
6. **停顿仍需听审**：Gemini 给出 164 个停顿候选，但 GPT-6 没有直接音频输入；
   独立静音检测只能确认声学间隔，不能判断修辞、犹豫或句末功能。

## 决策

当前模型足以做 **review sidecar**，不够做 **playback authority**。下一步不需要先换更多
Omni 模型；收益更大的方向是：

1. 用现有逐词时间轴把字幕和中文播放速度先稳定下来；
2. sidecar 只暴露高价值提示：读经候选、过渡候选、出处冲突、事件空洞和听审跳转点；
3. 对 `scripture_reading`、`transition` 和 `other` 全量听审，讲解类可按风险抽样；
4. 收集人工句级 Gold 后再决定是否微调提示、增加独立音频裁判或比较下一代模型。

手机听审页由 `build_full_review.py` 生成。它按 39 个窗口提供视频播放、抽帧、Gemini
类别与 GPT-6 结论。页面现可逐句播放、接受或修改类别、记录备注、标记窗口已完整听过，
并把进度自动保存在浏览器本地。导出的 `sermon-omni-human-gold-review-v1` JSON 绑定
源视频、sidecar 和 GPT-6 裁判哈希。只有 411 句全部选为四个正式类别且 39 窗全部标记
已听，导出才会置 `humanGold=true`；`混合／需拆分`、`无法判断` 或未审项目都会保持
`operator_review_in_progress`。即使完整，`releaseEligible` 仍固定为 false，需由后续流程
显式接纳，防止听审完成自动变成发布。
