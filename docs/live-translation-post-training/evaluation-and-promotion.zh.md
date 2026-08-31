# 证道实时翻译评估与模型晋级方案

日期：2026-08-30

状态：门禁设计，尚无实测结论

## 1. 评估目的

本项目不是证明学生在一般翻译 benchmark 上“更聪明”，而是回答：

1. 周日真实音频开始后，会众多久看到第一段可读中文。
2. 字幕是否忠实，特别是周六资料会不会诱导补写。
3. 小模型是否在经文、专名和证道表达上比未训练模型与云端基线更好。
4. 4B/9B 在完整 45–75 分钟证道中是否持续稳定，而不是只在短片段好看。
5. 一个不可变 artifact 是否有足够证据进入现场 rehearsal。

## 2. 五路固定对照

使用同一批周日录音、同一 ASR replay、同一 Context Pack 和同一渲染客户端：

1. 商业/云端 realtime baseline。
2. 未训练 Qwen3.5 4B/9B。
3. 领域 full-segment SFT。
4. Prefix `WAIT/WRITE` 学生。
5. Prefix 学生 + Context Pack。

另做两项消融：

- post-trained vs Base。
- BF16 vs 8/6/4-bit。

不能在比较模型时同时替换 ASR、segmenter、prompt、网络路径或字幕 UI。

## 3. 评估数据层

| 集合 | 输入 | 检查重点 |
|---|---|---|
| E0 clean text | 人工英文 prefix | 学生本身翻译与 policy |
| E1 real-ASR replay | 保存的真实 ASR emissions | ASR 噪声鲁棒性与端到端表现 |
| E2 context match | 周六/周日高度相似 | 术语、经文、稳定性收益 |
| E3 divergence/hard negative | 改序、删段、换例证、错经文 | 不补写、快速退回 live-only |
| E4 unseen speaker/church | 未见讲员或教会 | 泛化 |
| E5 long form | 完整 45–75 分钟音频 | 延时累积、内存、热状态与恢复 |

所有 test sermon 在 prefix/synthetic 扩增前已冻结，目标中文由人工审核。

## 4. 时间戳与指标定义

### 4.1 观测点

```text
speechStartedAt
audioFrameCapturedAt
audioFrameReceivedAt
asrFirstUnstableAt
asrFirstStablePrefixAt
studentRequestedAt
studentFirstTokenAt
captionCommittedAt
eventAcceptedAt
sseSentAt
viewerRenderedAt
semanticUnitEndedAt
```

所有观测点使用同一单调时钟域或保存可校准的时钟偏差；不能拿不同设备的 wall clock 直接相减。

### 4.2 产品延时

- `TTFC`：`speechStartedAt ->` 首个有意义中文字符。
- `time_to_first_readable_phrase`：`speechStartedAt -> viewerRenderedAt`，且中文达到人工定义的最小可读语义短语。
- `student_ttft`：`studentRequestedAt -> studentFirstTokenAt`。
- `time_to_stable`：`semanticUnitEndedAt ->` 对应 stable caption 在会众端显示。
- `recovery_time`：链路中断 -> 新鲜字幕重新显示。

“模型首 token”不能代替“会众首个可读短语”。论文中的 Average Lagging、LAAL、CU-LongYAAL 与本项目 TTFC 也不是同一指标，报告时必须并列而非互换。

## 5. 延时预算与目标

方案 C 的工程预算：

| 阶段 | 初始预算范围 | 备注 |
|---|---:|---|
| iPhone capture/VAD/chunk | 100–400 ms | chunk 太大直接增加下限 |
| LAN 上行与 framing | 10–100 ms | 会场 Wi-Fi 必须实测 |
| Streaming ASR 首个可用 prefix | 400–1,500 ms | 最可能成为瓶颈 |
| Student TTFT + 短 delta | 150–900 ms | 目标 TTFT p95 <= 500 ms |
| event ingest + SSE + render | 50–300 ms | Admin 与会众都测 |

这些范围不能简单相加为承诺值，因为 ASR 与翻译可以增量重叠。产品门禁仍使用端到端实测：

- 首个有意义字符：p50 <= 1.5 秒，p95 <= 3 秒。
- 首个可读中文短语：p50 <= 2 秒，p95 <= 3.5 秒。
- 英文 stable prefix 到 student first token：p95 <= 500 ms。
- semantic unit end 到 stable：p95 <= 5 秒。
- 断线恢复或明确故障态：<= 10 秒。

这些是目标，不是当前已验证事实。

## 6. 翻译质量指标

### 6.1 人工评分

每个样本至少从以下维度评分：

| 维度 | 建议权重 | 说明 |
|---|---:|---|
| 忠实/信息完整 | 35% | 不漏关键意思，不增加 live English 不支持的信息 |
| 经文与专名 | 20% | verse、书卷、人名、地名和神学术语 |
| 手机可读性 | 15% | 简洁、自然、适合 1–2 行快速阅读 |
| 时机 | 15% | 不过早猜、不无谓等待 |
| 稳定性 | 10% | 首次可读后少改写 |
| 格式与安全降级 | 5% | schema、WAIT、低置信行为正确 |

### 6.2 自动辅助指标

- chrF、BLEU：作为可重放参考，不单独决定晋级。
- COMET/COMETKiwi 或等价质量估计：比较模型版本，不替代人工忠实度。
- verse exact-match、book/person/entity F1。
- terminology accuracy 与同篇一致性。
- omission rate、unsupported addition rate。
- `Saturday-only addition` count/rate。

自动 judge 若使用闭源模型且其结果自动影响外部模型训练，先走许可审查；最稳妥的是将测试集人工 rubric 作为最终裁决。

## 7. 流式稳定性指标

- `WAIT` precision/recall：该等时是否等、该写时是否写。
- `revision_rate_after_first_readable`：首个可读短语显示后，被替换字符比例。
- rewrite events/minute。
- duplicate emission rate。
- committed-text violation count。
- stale output count：过期 request 的输出仍被发布。
- incorrect commit unrecoverable rate。
- source-prefix coverage：输出能否映射到当前 live evidence。

目标：首次可读短语后的 revision rate <= 15%，且 committed-text violation 为 0。

## 8. ASR 独立指标

- WER/CER。
- sermon 专名、经文和数字 recall。
- speech start -> first unstable/stable prefix。
- stable prefix revision rate。
- segment boundary 延时。
- 75 分钟 latency accumulation。

学生质量报告必须分别列 clean text 与 real-ASR replay。如果 clean text 通过而 real-ASR 失败，先修 ASR/数据增强，不宣称学生已达到现场要求。

## 9. Context Pack 门禁

对同一个学生做 `context off` 与 `context on`：

硬门禁：

- test/golden set 的 `Saturday-only addition = 0`。
- unsupported material count = 0；发现任何一例必须逐例 adjudicate。
- Context Pack 不得恶化 first-readable p95。
- `low/diverged/no-pack` 输出至少等价于该学生的 live-only baseline。
- 偏离后在一个受控窗口内停止使用旧 anchor；具体秒数由 replay 标注确定。
- 每个 prior-assisted caption 保留 source evidence、pack ID、candidate ID 和 match score。

Context Pack 有质量收益但破坏忠实度时，淘汰 Context 路线，而不是降低忠实度门禁。

## 10. 系统与硬件指标

Mac 与 DGX 分开报告：

- cold/warm model load。
- first-token p50/p95/p99。
- decode tokens/s 与 real-time factor。
- peak/steady memory、KV cache 增长。
- temperature、power 与 thermal throttling。
- 75 分钟 latency drift：前 10 分钟与后 10 分钟比较。
- crash、OOM、NaN、stale request 和 reconnect。
- artifact/hash/runtime receipt。

短 benchmark 不能代替完整证道。近期长语音研究提示延时会随连续输入累积，因此 75 分钟测试是 promotion 必需项。

## 11. 统计与人工审核

- 每个候选至少使用 3 个训练 seed；报告均值、方差和最差 seed。
- 模型比较在同一 sample 上做 paired analysis。
- 按讲员、教会、经文/非经文、Saturday match/diverge 分层。
- 人工 blind review 隐去模型名和教师来源。
- 先校准审核者；报告双人一致率与 adjudication 数量。
- 所有严重 unsupported addition 单独列出，不被平均分掩盖。

POC 样本少时不夸大统计显著性；同时报告 effect size、置信区间与案例审查。

## 12. Promotion gate

一个 student profile 只有全部满足才可标记 `ready_for_rehearsal`：

### 忠实度

- `Saturday-only addition = 0`。
- 严重 unsupported addition = 0。
- committed-text violation = 0。
- 人工忠实度不低于云端 realtime baseline。

### 领域质量

- 经文、专名、神学术语相对未训练同规模模型有可见且可重放的提升。
- Context Pack on 比 off 有净收益，或明确选择 live-only profile。

### 延时与稳定

- first readable phrase p50 <= 2 秒、p95 <= 3.5 秒。
- student TTFT p95 <= 500 ms。
- semantic end -> stable p95 <= 5 秒。
- first-readable 后 revision rate <= 15%。

### 长时与故障

- 完成 75 分钟回放，无 crash/OOM/KV 失控。
- 后半程仍满足 p95 门禁。
- producer 失败、SSE 断线和显式云端 fallback 行为通过。

### 治理与可复现

- base/dataset/code/config/container/artifact hash receipt 完整。
- 许可证与 rights manifest 通过。
- 训练数据可按 source 删除重建。
- 未批准 artifact 在 preflight 被拒绝。

## 13. 决策结果

评估只能产生以下状态：

| 状态 | 含义 |
|---|---|
| `rejected` | 有硬门禁失败；保留证据，不继续 promotion |
| `needs_data_revision` | 主要问题来自数据/schema/teacher，发布新 dataset 后重训 |
| `needs_runtime_revision` | 模型质量合格，ASR/runtime/网络延时不合格 |
| `ready_for_rehearsal` | 可进入隔离现场演练，不等于 production |
| `ready_for_promotion_review` | rehearsal 通过，可请求显式生产切换授权 |
| `production` | 只有完成部署、smoke、真实会众 loopback 与回滚验证后才能标记 |

不得因用户接受风险而删除原始失败门禁；风险接受和测试事实要同时保留。

## 14. 现场验收

至少一次真实 iPhone -> venue host -> backend -> iOS/Web 完整演练：

- iPhone 实际摆位、音量、回声、噪声与外接音源。
- Wi-Fi/蜂窝切换、10 秒中断、来电、Siri、锁屏和 App 前后台。
- 第二台 Admin 争抢 lease、重复开始和 crash recovery。
- iOS 与 Web 收到相同 church/session/event/caption。
- 点击结束后 1 秒内本地 audio level 归零，public SSE 收到结束回执。
- 物理音频 marker 测量 speech-start 到 iOS/Web render，不用模拟器时间替代。

Cloud Run health、后端 200、模型能加载和 simulator UI 测试都不能替代这条端到端验收。
