# 近三个月实时翻译研究综述与设计映射

检索日期：2026-08-30

时间窗口：2026-05-30 至 2026-08-30

范围：同时语音到文本翻译、流式 LLM、前缀监督、上下文增强、长语音评估

证据边界：优先 ACL Anthology、arXiv 原文和官方项目文档；搜索摘要不作为结论

## 1. 结论

近三个月与本用例最相关的公开工作并没有给出“只要蒸馏一个 4B 模型就能完成证道同传”的现成答案，但形成了很一致的工程方向：

1. **级联仍然可行**：稳定的流式 ASR + 经过领域 LoRA 的翻译 LLM 是多支 IWSLT 2026 系统采用的路线。
2. **训练输出时机**：用 `<wait>`、prefix-to-prefix 或 adaptive policy 让模型学习何时等、何时写，比只用整句平行语料更接近实时任务。
3. **必须训练真实 ASR 噪声**：ASR-noise augmentation、stable transcript 和真实 incremental prefix 是质量基础。
4. **上下文有效但要受控**：RAG、预翻译 exemplar、ASR word boosting 和 contextual prior 可提升领域质量，但论文没有替我们解决“周六稿不得补写周日事实”的安全门禁。
5. **长时间测试不可省**：研究明确指出长语音会出现 latency accumulation；短句 TTFT 不能证明 45–75 分钟证道可用。
6. **约 2 秒是研究上可达到的延时区间之一，但不是统一 TTFC 定义**：论文使用 Average Lagging、LAAL、CU-LongYAAL 等不同指标，不能直接等同于“讲员开口到会众看到首字”。

因此，本项目采用 `streaming ASR -> post-trained 4B/9B text student -> church SSE`，配合 prefix `WAIT/WRITE`、真实 ASR replay、Context Pack hard negatives 和长时端到端测量，是有研究依据的设计；实际质量和延时仍需本地验证。

## 2. 论文对照

| 工作 | 时间 | 核心方法 | 报告结果/重点 | 对本项目的直接启发 |
|---|---|---|---|---|
| [CUHKSZ Simultaneous Speech Translation System for IWSLT 2026](https://aclanthology.org/2026.iwslt-1.13/) | 2026-07 | Qwen3-Omni-30B-A3B；LoRA；Qwen3-30B-Instruct 合成 chunk-aligned 监督；模型预测 `<wait>`；固定音频 chunk、bounded history、context prior | En→Zh 低延时组报告 40.5 BLEU、1.95 s；2–4 s 组 42.1 BLEU、2.16 s | 证明 read/write policy 可通过数据内化；支持 bounded history 与 Context Pack，但其 30B 音频模型不适合我们的 M1 首版 |
| [Pinch-AST](https://aclanthology.org/2026.iwslt-1.30/) | 2026-07 | off-the-shelf speech model + translation backbone；语言对 LoRA；ASR-noise-augmented parallel data；character-level longest-common-prefix retranslation | 单 H100 80GB 在 real-time budget 内，覆盖 En→Zh 等方向 | 支持级联、LoRA、ASR 噪声训练和 LCP/commit 策略；其硬件与我们的 DGX Spark 不可直接类比 |
| [MLLP-VRAIN UPV IWSLT 2026](https://aclanthology.org/2026.iwslt-1.24/) | 2026-07 | Parakeet + Qwen3.5；adaptive black-box policy；context track 使用 ASR word boosting 与离线预翻译 exemplar RAG | 报告 context processing 额外提升 1.03；包含 En→Zh contextual track | 与我们的 Qwen3.5 学生、周六 Context Pack 最接近；说明 ASR 与 retrieval 要一起设计 |
| [NeMo@IWSLT 2026](https://aclanthology.org/2026.iwslt-1.23/) | 2026-07 | dual-mode Unified ASR Transducer + multilingual LLM cascade；ASR 在不同延时下输出稳定转写 | 覆盖 En→Zh、standard/contextual、low/high latency，并分析 ASR/LLM 选择 | 直接支持把 ASR 稳定性作为独立门禁，而不是让学生掩盖 ASR 错误 |
| [Do LLMs Need Architectural Changes for Simultaneous Speech Translation?](https://arxiv.org/abs/2607.13158) | 2026-07-14 | 固定长度 chunk、cumulative decoding、rewind committed prefix、teacher-labeled prefix-to-prefix targets、bounded waiting | 内部对话语音评估相对 streaming baseline 提升 +1.54 COMETKiwi，Average Lagging +0.15 s | 最直接支持我们的 prefix teacher data、bounded wait 与 committed prefix；结果是内部数据且非证道域 |
| [Test-Time Adaptation of an Offline Multimodal Foundation Model](https://aclanthology.org/2026.iwslt-1.27/) | 2026-07 | pause segmentation、wait-k 变体、多轮对话、response prefilling、KV cache | 在 IWSLT 2026 dev 上报告优于 cascaded baseline 的 quality-latency trade-off | 支持先用简单 controller、bounded history 与 KV cache，不急于改模型架构 |
| [AlignAtt4LLM](https://aclanthology.org/2026.iwslt-1.32/) | 2026-07 | Qwen3-ASR + forced alignment；Gemma-4 decoder-only translation；attention-based emission policy | 欧洲语言在约 2 s / 4 s 区间优于 baseline；论文称 En→Zh 结果更混合 | 是后续 policy 研究方向；因 En→Zh 证据不稳定和实现复杂，不作为第一版 |
| [A Practical Evaluation Method for Long-Form Simultaneous Speech-to-Speech Translation](https://aclanthology.org/2026.iwslt-1.3/) | 2026-07 | 长语音可重现实验方法 | 指出代表性系统在长语音上存在显著 latency accumulation | 支持完整证道与 75 分钟延时漂移门禁，不能只测短 clip |

## 3. 与证道用例最接近的模式

### 3.1 级联 ASR + 小型翻译 LLM

Pinch-AST、MLLP-VRAIN 与 NeMo 都说明级联并未过时。对证道项目，级联的额外价值是可审计：

- 能看到 live English evidence。
- ASR 和翻译各有指标。
- 周六资料只能在文本 matcher 层辅助。
- 翻译失败时仍保留英文 sidecar。
- 4B/9B 学生训练不需要重新学习音频表征。

缺点是 ASR 延时与翻译延时相加或重叠；必须从 audio capture 到 viewer render 做统一时间戳。

### 3.2 Prefix policy 与 `<wait>`

CUHKSZ 与 P2P 工作共同支持：同传最关键的不是完整句翻译，而是让模型在不完整源文本下学会等待与提交。

本项目把这一点落为：

```text
input  = source history + new ASR prefix + committed Chinese + short context
output = WAIT | WRITE(deltaZh, commitBoundary)
```

这比普通“英文段落 -> 中文段落”更符合首字、稳定性和不可回写约束。

### 3.3 ASR 噪声与稳定前缀

Pinch-AST 使用 ASR-noise augmentation，NeMo 强调稳定 transcription，MLLP 同时调整 ASR word boosting。这意味着：

- 训练数据必须保留真实 ASR emissions 和 revision。
- clean transcript 只能证明翻译上限。
- 经文、人名与数字要单独做 ASR recall。
- 不能把人工完美英文随机截断后称为真实 streaming data。

### 3.4 Context/RAG

MLLP 在 contextual track 使用离线预翻译 exemplars，CUHKSZ 注入 contextual priors。这与周六资料高度相关，但需要更严格的产品安全规则：

- 只注入附近 anchor、术语和经文候选。
- 低置信、错序或偏离立即退回 live-only。
- 建 hard negatives：周六有而周日没说。
- `Saturday-only addition` 必须为 0。

论文显示 context 可能提高平均质量，不等于先验不会制造事实新增。

## 4. 延时应该怎样理解

不同研究使用不同定义：

- Average Lagging/LAAL：译文相对源输入的平均滞后。
- CU-LongYAAL：包含计算时间和长语音效应的延时指标。
- 应用报告的 2 s/4 s regime：任务分组或整体政策结果。
- 产品 TTFC：讲员开始说话到会众屏幕出现第一个有意义中文字符。
- 首个可读短语：比单一字符更符合会众体验。

因此不能从 CUHKSZ 的 1.95 s 直接推出我们的 iPhone -> DGX -> SSE p50。它只能说明 En→Zh 的约 2 秒研究区间是现实目标之一。

本项目同时报告：

- speech start -> first meaningful char。
- speech start -> first readable phrase。
- semantic end -> stable caption。
- student request -> first token。
- p50/p95/p99 与 75 分钟 latency drift。

## 5. 对后训练方案的具体修改

研究证据促成以下设计选择：

| 选择 | 证据映射 |
|---|---|
| 先做文本级联，不先训音频学生 | Pinch-AST、MLLP、NeMo |
| 使用 Qwen3.5 4B/9B 候选 | MLLP 直接使用 Qwen3.5；官方存在对应开放权重模型 |
| 训练 `WAIT/WRITE` | CUHKSZ `<wait>` 与 P2P bounded waiting |
| 使用真实 ASR prefix 与噪声增强 | Pinch-AST、NeMo |
| bounded history/KV cache | CUHKSZ streaming agent、test-time adaptation |
| Context Pack + hard negatives | MLLP/CUHKSZ contextual track，加上本项目忠实度门禁 |
| 75 分钟完整 replay | long-form evaluation 的 latency accumulation 发现 |
| 暂不做 AlignAtt | En→Zh 结果更混合，且实现复杂度高 |

## 6. 论文没有证明的事项

- 没有论文证明这些模型已在教会扩声、回声和现场噪声下达到门禁。
- 没有论文验证我们的中文圣经版本、讲员术语和周六/周日差异。
- H100 80GB 的 real-time 结果不能直接映射到 DGX Spark 的 unified memory/带宽。
- 30B 音频模型的 IWSLT 结果不能证明 4B/9B 文本学生达到同样质量。
- BLEU/COMET 改善不能证明 unsupported addition 为 0。
- IWSLT 延时指标不能替代 iOS/Web viewer render 的 TTFC。
- arXiv P2P 论文是 2026-07 v1，需把结论视为早期研究证据。

## 7. 建议复现实验

不复刻整套 IWSLT 系统，先复现能直接回答产品问题的部分：

1. 用同一周日音频保存真实 ASR emissions。
2. 构造 full-segment、固定 chunk、真实 emission 三种 prefix 数据。
3. 训练普通 SFT 与 `WAIT/WRITE` P2P 两个 4B LoRA。
4. 加入 ASR-noise augmentation 做第三个 candidate。
5. 对 P2P candidate 分别关闭/开启 Context Pack。
6. 在 4B、9B 和云端 realtime 上跑同一完整证道。
7. 报告 TTFC、首个可读短语、稳定延时、revision、经文/专名、unsupported addition 和长时漂移。

如果这个最小复现没有净收益，不应直接升级到端到端音频模型或更复杂 attention policy；先检查数据、ASR 和标签策略。
