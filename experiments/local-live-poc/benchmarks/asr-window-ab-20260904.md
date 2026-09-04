# ASR 最长窗口 3 秒 / 6 秒：真实模型回放，2026-09-04

**结论：保留 3 秒默认，将 6 秒保留为待评估候选。** 6 秒减少了部分断词、重复尾词和中文碎片，但仍把 `buried anger is rarely / dead anger` 切开，也出现新的增译。从音频段开始到首条可读字幕事件的 P95，由 **4.790 秒增加到 7.910 秒**。这一次 90 秒开发片段不足以批准任何方案成为周日已验证默认；保留 3 秒也不表示原有语义问题已解决。

## 输入与运行边界

- 输入：历史麦克风录音 session `20260904T194140.715Z-c0524bb5` 的 **390–480 秒**，本报告表内时间均相对此 90 秒切片；两轮以 1 倍速发送到隔离本地 Gateway，再走真实 Qwen ASR、MiLMMT 翻译和 readable presenter。
- 本轮没有使用现场麦克风、浏览器渲染确认或手机端验证。`caption.display` 是 Gateway 发出的字幕事件，**不是已经在屏幕上显示的证据**。
- 两轮均为 `contextPolicy=none`、`translationUnitPolicy=legacy`、`sourceFragmentPolicy=content_words`、`readable_chunks`；记录的配置仅 `vadMaxSegmentMs` 从 `3000` 改为 `6000`。VAD 静音阈值仍为 500 ms，ASR finalization 仍追加 12 个静音帧。
- 模型为 Qwen3-ASR 0.6B 8-bit、MiLMMT 4B Q8；ASR SHA-256、翻译模型 digest 和 prompt hash 在两轮相同，详见[脱敏逐段数据](asr-window-ab-20260904.json)。
- 两次均记录基准 revision `516c3253a077aba5de7fc9f802b88da20154956c`、`dirty=true`。该 revision 不能唯一复现当时未提交的源码，也不能代表之后的健康状态、恢复或延迟归因修复。两轮顺序执行，没有随机顺序、重复运行或资源条件对照。
- **以下质量判断为机器文本评阅，不是 human Gold、盲评或听音校订。** 此切片有意包含已知问题，是开发诊断材料；没有参考转录，不能计算 ASR WER 或声称总体准确率提升。

| 冻结输入 | SHA-256 |
|---|---|
| 历史完整 ASR WAV | `9ae93881dcc74bd1f174c99b37bb73ca7686e522e27286672ab8f5255b5743c7` |
| 90 秒切片 WAV | `19d26141b5835ed21b0a2850eebb48439872c5b53b1c8113ad9f51f6eb1f7893` |
| 切片 PCM | `dc35bf7e7ac3ebe034903ce45a06fd05276131afe0dba82ca1378eb4456e240a` |

独立复核重新读取了原始完整 WAV，截取 390–480 秒 PCM，并重算两轮 recovery WAV、ASR WAV、ASR PCM 的 SHA-256：均与同一切片匹配。不是仅转述 runner 的成功字段。

## 工程完成性

| 指标 | 3 秒 | 6 秒 |
|---|---:|---:|
| session | `20260904T205827.159Z-c201ce4c` | `20260904T210056.378Z-2bcf73c2` |
| 发送 / 持久化 PCM 帧 | 900 / 900 | 900 / 900 |
| PCM 字节 | 2,880,000 | 2,880,000 |
| 1 倍速发送耗时 | 90.005 s | 90.011 s |
| ASR processing / final | 33 / 33 | 19 / 19 |
| translation started / final | 33 / 33 | 19 / 19 |
| 获得 caption.display 的 final | 33 / 33 | 19 / 19 |
| 字幕事件：全部 / partial | 34 / 1 | 27 / 8 |
| 达到最长窗口的 ASR final | 26 / 33 | 10 / 19 |
| VAD 发出的音频区间总长 | 88.3 s | 89.1 s |
| errors / worker drain / completed | 0 / true / true | 0 / true / true |

两轮事件序号分别连续为 1–260、1–179；无 ASR failed/empty、翻译失败、丢队列或 lexical guard skip 事件。WS 收到的事件与持久化事件逐对象相同，唯一差异是 `stream.ready` 的 WS-only viewer 信息；字节序列本身因 JSON 序列化不同而不同。脱敏数据不保存 viewer token/URL。

这里的“覆盖”指每个已发出的 ASR final 都有翻译及字幕事件，不代表每个口述词都被正确识别。VAD 未发出的区间仍完整保存在 PCM；19 段比 33 段少，也不能被解释为丢失了 14 段。

## 延迟：必须同时看段结束与段开始

以下单位均为 ms，单元格为 **P50 / P95 / 最大值**。每个 ASR final 一条样本，因此 A/B 的分母分别为 33 和 19，并非相同句子的配对质量统计。

| 指标 | 3 秒 | 6 秒 |
|---|---:|---:|
| audio-end → ASR final | 1254 / 1518 / 1721 | 1259 / 1277 / 1279 |
| audio-end → 中文首 token | 1395 / 1658 / 1897 | 1408 / 1445 / 1450 |
| audio-end → 中文 final | 1638 / 1910 / 1955 | 1795 / 1994 / 2007 |
| audio-end → 首条 caption 事件 | 1640 / 1894 / 1955 | 1796 / 1910 / 1941 |
| audio-start → 首条 caption 事件 | **4618 / 4790 / 4913** | **7683 / 7910 / 7941** |
| audio-start → final caption 事件 | 4618 / 4790 / 4956 | 7683 / 7994 / 8008 |
| translation queue wait | 0 / 0 / 0 | 0 / 0 / 0 |
| 连续两段首条 caption 事件的最长间隔 | 3702 | 6527 |

6 秒的 audio-end 首 token P95 较低，但同一指标没有计入形成该音频段所需的更长等待；不能据此说观众更快看到字幕。首 token 也不等于满足 readable presenter 阈值的可读字幕。最长更新间隔包含静音及旧字幕停留，不等于黑屏时长。

复算口径：token/final 耗时取每段 `translation.final.uxMetrics`；字幕事件耗时为 `asr.final.uxMetrics.audioEndToAsrFinalMs + (caption.display.at - asr.final.at)`，用 ASR 的单调时钟指标锚定事件时间戳差，约 1 ms 精度。首条取该段第一个 `caption.display`，完整条取第一个 `displayKind=final`。audio-start 耗时再加 `audioEndMs - audioStartMs`。P50 为中位数，P95 在排序后 `(n-1)*0.95` 处线性插值并取整。逐段值及事件 sequence 保存在 JSON 中，可重新计算。

## 同一音频时间上的质量变化

| 切片时间 | 3 秒输出 | 6 秒输出与机器评阅 |
|---|---|---|
| 12–18 s | `say that suppression.` / `Question of anger...`，中文为“都称这是镇压” / “愤怒的问题……” | 合成 `suppression of anger`，译为“抑制愤怒”。词组连续性改善，但仍截在 `cardiovascular`，不能由此证明全文 ASR 正确。 |
| 18–26.4 s | `...relationships and.` / `Your emotional health—that burying your.` / `Anger isn't really best.`；中文割裂 | 18–24 s 仍以 `That burying your` 截断，中文新增“**因此，切忌埋怨。**”；24–26.4 s 仍是“愤怒并不是最好的选择”。更长窗口没有恢复跨界关系，还出现不受该英文支持的解释。 |
| 26.6–33.9 s | `Buried anger is rarely.` →“埋藏的愤怒很少见。”；`Dead anger.` →“死气沉沉的愤怒。” | 6 秒把姓名和引语前半合并，**仍在 rarely 后切开**，同一错误继续存在；只把前半句加长不能解决补语归属。 |
| 50.9–54.7 s | 完整 `...let it out.` 后另发 `Out.` →“出去” | 6 秒仅发完整句，去掉独立尾词“出去”。这是片段文本层面的明显改善。 |
| 54.7–60.7 s | `the more we` / `We express our anger...`，中文先悬空后重新起句 | `the more we express our anger, we actually become more angry` →“我们越是表达愤怒，反而会变得越生气”。比较关系恢复。 |
| 72.6–84.6 s | `where they are.` →“在他们所在的地点”；接着 `Circulated an ethical viewpoint...` | 前段变为 `where they articulated`，改善局部连贯；后段却是 `They calculated an ethical viewpoint` →“计算出一个合乎道德的观点”，仍无法得到可靠叙述。另有“我让人们……”增加原英文没有的第一人称。 |
| 84.6–88.4 s | `put into three.` 后又发 `Groups.` →“群组” | 6 秒得到一个完整的 `three groups` 译句，避免单独尾词；两轮都仍有 `From their viewpoint`，不能在没有听音校订时认定它正确。 |

这些是按时间对齐的诊断实例，不是胜率。两轮在片尾 88.4–90 s 都停在 `And of the three groups, the.`，本切片本身也截断语义。

## 默认选择需要的证据

目前可以确认：增加声学窗口能减少部分碎片，代价是本片段首条可读字幕约多等 3 秒；固定 6 秒边界仍可切断关键句。下一轮应在冻结 revision、独立未用于开发的连续 sermon 音频上，保留音频时间对齐，进行 ASR 人审及否定、因果、代词、增译和遗漏的双语盲评，并同时测 audio-start → 实际浏览器/手机显示及资源、故障恢复。达到这些门槛前，不以本轮局部改善改动默认。

原始运行报告和事件保存在本机 ignored `artifacts/benchmarks/sunday-readiness/real-asr-{3,6}s.*`，媒体及带 viewer 信息的完整日志不入 Git。本报告与 JSON 是可审查的紧凑衍生证据，不是现场就绪验收。
