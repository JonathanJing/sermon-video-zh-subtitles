# 证道实时翻译模型选型方案

日期：2026-08-30

状态：候选冻结，最终选型待 benchmark

## 1. 选型结论

首轮不是选一个“最大、最新”的模型，而是固定四个学生对照和一个开放权重教师：

| 角色 | 首选 | 对照 | 结论用途 |
|---|---|---|---|
| Mac 低延时学生 | `Qwen/Qwen3.5-4B` | `Qwen/Qwen3.5-4B-Base` | 比较已有 post-training 能力与从 Base 适配的上限 |
| DGX 质量学生 | `Qwen/Qwen3.5-9B` | `Qwen/Qwen3.5-9B-Base` | 比较质量、延时和训练稳定性 |
| 外部学生数据教师 | `Qwen/Qwen3.8-27B` 固定 revision | 人工翻译/审核 | 生成 sequence-level 候选，不参与周日运行 |
| 商业参考 | `gpt-5.6-sol` | 云端 realtime translation | 未获外部蒸馏授权前只做隔离参考，不进入训练集 |

生产候选暂定为：

- M1 Max 64GB：4B post-trained 或 4B Base+LoRA 中门禁最好的一个。
- DGX Spark：9B post-trained 或 9B Base+LoRA 中门禁最好的一个。
- 27B 只用于离线制数、困难样本复核和质量上限，不预设为低延时现场模型。

## 2. 为什么学生优先开放权重

学生不一定要符合严格的“开源软件”定义，但本项目需要：

- 下载并固定权重。
- LoRA/SFT、合并 adapter 和量化。
- 在 MacBook/DGX Spark 本地部署。
- 为每个 artifact 计算 hash 并保留回滚版本。
- 未来可能向固定教会发放推理 artifact。

因此实际要求是“**开放权重 + 许可证允许修改和目标部署**”。只提供 fine-tuning API 的闭源学生技术上也能训练，但无法满足现场本地运行和离线控制。

Qwen 当前官方模型页为这些候选标示 Apache-2.0。每次正式训练仍要把实际下载 revision 的 `LICENSE`、`NOTICE`、model card 和文件 hash 保存到 receipt，不能只引用移动的 `main` 页面。

## 3. 研究快照

以下 revision 是 2026-08-30 从 Hugging Face model API 读取的研究快照；正式训练前必须重新解析并由负责人批准，不应自动跟随 `main`：

| 模型 | 2026-08-30 revision | 页面标示许可 | 角色 |
|---|---|---|---|
| `Qwen/Qwen3.5-4B` | `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` | Apache-2.0 | Mac post-trained 学生 |
| `Qwen/Qwen3.5-4B-Base` | `1001bb4d826a52d1f399e183466143f4da7b741b` | Apache-2.0 | Mac Base 对照 |
| `Qwen/Qwen3.5-9B` | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` | Apache-2.0 | DGX post-trained 学生 |
| `Qwen/Qwen3.5-9B-Base` | `68c46c4b3498877f3ef123c856ecfde50c39f404` | Apache-2.0 | DGX Base 对照 |
| `Qwen/Qwen3.8-27B` | `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` | Apache-2.0 | 离线教师 |

来源：[Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)、[Qwen3.5-4B-Base](https://huggingface.co/Qwen/Qwen3.5-4B-Base)、[Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)、[Qwen3.5-9B-Base](https://huggingface.co/Qwen/Qwen3.5-9B-Base)、[Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)。

这些 revision 是可复现实验起点，不是永久的安全或质量背书。

### Qwen3.5 的多模态开销

Qwen3.5 官方 checkpoint 是统一 vision-language 架构，不是纯文本专用模型。我们的学生只用文本，因此：

- LoRA 首轮冻结 vision tower 和所有非文本模块，不让无关参数进入 optimizer。
- 训练与推理 receipt 记录实际加载参数、冻结参数和 text-only prompt path。
- 在 DGX 记录未使用视觉模块带来的常驻内存；在 Mac 验证 MLX/量化转换是否完整支持该架构。
- 如果 text-only 运行仍携带不可接受的多模态开销，才引入纯文本小模型作新 bake-off；不能在同一个实验中静默换 family。

NeMo AutoModel 的当前发布说明包含 Qwen3.5 9B-to-4B VLM knowledge-distillation recipe，并说明可冻结 vision/audio towers。这证明框架层已有相关机制，但不等于该 recipe 已在单台 Spark 和本数据上通过。[NeMo AutoModel release notes](https://docs.nvidia.com/nemo/automodel/whats-new/release-notes)

## 4. Post-trained 与 Base 怎么选

### Post-trained checkpoint

优点：

- 已有英中翻译、指令遵循和结构化输出能力。
- 小数据 LoRA 更可能快速得到可用 POC。
- 降低从 Base 学习通用对话/翻译能力的样本需求。

风险：

- 可能啰嗦、解释任务或带入原有聊天风格。
- 对 `WAIT`、append-only 和严格短输出的服从可能不稳定。
- 后训练偏好可能与同传的“少说、晚一点但正确”冲突。

### Base checkpoint

优点：

- 更容易围绕单一协议塑造输出行为。
- 没有过强的助手式解释偏好。
- 官方 Base model card 明确把 fine-tuning 和 LoRA 风格 PEFT 作为 intended use 之一。

风险：

- 需要更多高质量数据才能达到自然翻译与 JSON 稳定性。
- 小语料更容易欠拟合、语言退化或只记住领域表达。

因此必须保留 post-trained 与 Base 对照。POC 默认先训 post-trained，Base 跑同一小规模 recipe；如果 post-trained 在格式、抢跑或重写上反复失败，再扩大 Base 路线。

## 5. 4B 与 9B 怎么选

| 维度 | 4B | 9B |
|---|---|---|
| 目标硬件 | M1 Max 与 DGX | 主要是 DGX Spark，Mac 仅研究 |
| 优势 | 首 token 更有机会低、部署轻、可做便携方案 | 翻译与语义判断容量更大，困难经文/长距离重排更有希望 |
| 主要风险 | 漏译、抢跑、复杂神学句退化 | TTFT、功耗和长时延时更高 |
| 生产角色 | 低延时主候选 | 质量主候选 |
| 决策方法 | 同数据、同 ASR、同 prompt、同门禁对比 | 同左 |

不能用参数量直接决定。最终选择依赖端到端 p95、unsupported addition、术语准确率和 75 分钟漂移，而不是单句 BLEU 或 tokens/s。

## 6. 教师选型

### 6.1 默认教师：Qwen3.8-27B

选择理由：

- 开放权重，能在 DGX Spark 离线运行并固定 revision、template 和 decoding 参数。
- 当前官方 model page 标示 Apache-2.0，技术和许可链路比闭源 API 教师更容易审计。
- 参数量明显大于 4B/9B 学生，适合生成 full-segment 与 prefix 候选。
- 必要时可以研究 logits/hidden-state KD；POC 仍先做更简单的 sequence-level labels。

限制：

- 27B 不是人工真值，仍会漏译、补写或产生过于书面化中文。
- 它自身是否优于学生必须先在人工 calibration set 上证明。
- 教师 inference 与学生 training 不应同时占用 DGX Spark；先制数并固化 dataset，再释放教师。

### 6.2 GPT-5.6 Sol

GPT-5.6 Sol 官方模型页显示它支持文本、Structured Outputs、Batch 和 streaming，但不支持音频输入，也不支持该模型本身 fine-tuning。[官方模型页](https://developers.openai.com/api/docs/models/gpt-5.6-sol)

技术上，它可以生成 sequence-level 标签；合同上不能据此自动认定可用于训练外部学生。当前 OpenAI Services Agreement 限制把 Output 用于开发与 OpenAI 产品或服务竞争的 AI 模型，并只定义了有限例外。因此本项目状态为：

| 用法 | 当前状态 |
|---|---|
| 少量、不进入训练集的人工质量参考 | 可研究，仍按组织政策留痕 |
| 自动生成外部 Qwen SFT/P2P 数据 | **BLOCKED，等待书面授权/合同确认** |
| 用 GPT 输出打分并自动驱动外部训练 | **BLOCKED，按外部模型开发处理** |
| OpenAI 平台内、明确支持的小模型 fine-tuning/distillation | 可另立方案，但不能本地部署 |

详细条款与 go/no-go 见[许可与数据治理](./licensing-and-data-governance.zh.md)。

## 7. ASR 模型不是学生选型的附属项

学生只看英文 prefix，因此 ASR 是独立的硬门禁。近期系统采用过 Parakeet、Qwen3-ASR、dual-mode transducer 等不同路线，但本项目尚未实测并锁定具体 checkpoint。

ASR bake-off 至少比较：

- speech start -> first unstable/stable English prefix。
- 英文 WER 与 sermon 专名 recall。
- unstable -> stable 的 revision 行为。
- 75 分钟内延时累积、内存和断句稳定性。
- 能否把真实增量日志保存为学生训练 prefix。

学生 benchmark 必须固定同一 ASR replay；否则无法区分翻译模型与 ASR 变化。

## 8. 暂不进入首轮的模型路线

| 路线 | 暂缓原因 |
|---|---|
| iPhone 1B–3B 本地学生 | 设备碎片、热状态、模型分发和隐私复杂；方案 C 不需要每台会众设备推理 |
| 30B 级端到端音频模型 | 训练与运行复杂，难以复用现有文本资产，M1 Max 不合适 |
| Qwen3.8-27B 作为周日主模型 | 虽可能装入 DGX Spark，但 TTFT/持续延时没有证据，且失去 4B/9B 小模型目标 |
| 任意第三方 GGUF 直接训练 | GGUF 是推理交付格式，不是首选训练源；训练从官方 safetensors revision 开始 |
| 自动跟随 `main` 或“latest” | 无法复现，可能改变许可证、template、Tokenizer 和行为 |
| 多教师输出静默混合 | provenance 不清，无法做消融或删除来源 |

## 9. Bake-off 决策表

每个候选必须用相同 dataset version、seed 列表、prefix contract 和评估集：

| Candidate | 训练 | 必测部署 |
|---|---|---|
| 4B post-trained | BF16 LoRA | DGX BF16/量化，Mac MLX 8/6/4-bit |
| 4B Base | BF16 LoRA | 同上 |
| 9B post-trained | BF16 LoRA | DGX BF16/8/6/4-bit |
| 9B Base | BF16 LoRA | 同上 |

第一轮晋级规则：

1. 任一忠实度硬门禁失败，直接淘汰，不用更低延时抵消。
2. 忠实度都合格时，先比较端到端 first-readable p95 和 revision rate。
3. 4B 达到质量门禁且显著更快时，优先便携方案；9B 只有可见质量收益时才承担额外成本。
4. Base 只有在足够数据下稳定超过 post-trained 才晋级；不能因为“更纯”而默认更好。

## 10. 最终输出不是模型名字

正式选型应写成 immutable artifact profile，例如：

```json
{
  "profile": "sermon-live-dgx-v1",
  "baseModel": "Qwen/Qwen3.5-9B",
  "baseRevision": "...",
  "adapterSha256": "...",
  "mergedSha256": "...",
  "quantization": "bf16",
  "datasetVersion": "sermon-simul-ds-v1",
  "promptSchema": "sermon-simul-v1",
  "runtime": "vllm-or-sglang-pinned",
  "promotionReport": "..."
}
```

只有这个 profile 通过 preflight，系统才能报告本地 producer ready。
