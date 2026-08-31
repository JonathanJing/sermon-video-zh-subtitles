# 模型许可与训练数据治理

日期：2026-08-30

状态：设计门禁，不构成法律意见

## 1. 核心结论

技术上能调用、下载或生成，不等于拥有训练与分发权。后训练至少同时受五层权利约束：

1. 学生 base model 的许可证。
2. 教师模型或 API output 的使用条款。
3. 证道音频、视频、讲稿和字幕的授权。
4. 中英文圣经译本的训练、存储和展示授权。
5. LoRA、merged、量化 artifact 的内部部署或对外分发范围。

任何一层不清楚，相关数据或 artifact 都不能进入 production promotion。

## 2. “开源”“开放权重”“可以蒸馏”不是同一件事

| 类型 | 能得到什么 | 能否本地后训练 | 本项目适用性 |
|---|---|---|---|
| 只开源代码 | inference/training code，未必有权重 | 通常不够 | 低 |
| 开放权重 | 可下载参数 | 技术上通常可以，仍看许可证 | 高 |
| 厂商 fine-tuning API | 厂商托管的自定义模型 | 可以定制，不能拿回权重 | 不满足本地关键路径 |
| 只有 generation API | 文本输出 | 可做 sequence label，但必须确认 output 条款 | 教师候选，许可风险独立 |
| 自有 proprietary weights | 自己拥有/获许可的权重 | 取决于内部权利 | 也可作为学生，不要求公开 |

学生模型不一定要“开源”，但要在本地运行，就必须取得权重，并获得修改、量化、部署和预期分发的许可。

教师不一定开放权重：文本级蒸馏只需要教师输出；logit-level KD 通常需要 logits 或本地权重。无论哪种，教师条款必须允许输出用于该外部学生训练。

## 3. 学生模型许可清单

对每个候选 revision 确认：

- 是否允许复制权重。
- 是否允许修改、fine-tune 和创建衍生作品。
- 是否允许 LoRA adapter、merged weights 和量化。
- 是否允许商业/非商业、内部/外部部署。
- 是否允许向教会或第三方重新分发 artifact。
- 是否有 attribution、NOTICE、使用限制或 patent 条款。
- base model 上游数据/代码是否另有条款。

Qwen3.5 4B/9B 与 Qwen3.8-27B 当前官方 model page 标示 Apache-2.0，但正式运行要保存实际 revision 的 LICENSE/NOTICE，不把页面标签当作永久授权。[Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)、[Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)、[Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)

Apache-2.0 的 base model 许可不会自动覆盖训练语料。一个 adapter 可以继承/遵守 base 许可，但其数据来源仍需逐项合法。

## 4. OpenAI 教师边界

### 4.1 Output ownership 不等于无条件训练权

OpenAI 当前 Services Agreement 第 4.1 节说明，在 OpenAI 与客户之间，客户保留 Input 权利并拥有 Output；同一协议第 3.3(e) 又限制在 Permitted Exception 之外，使用 Output 开发与 OpenAI 产品和服务竞争的 AI 模型。Permitted Exception 当前定义为有限的分类/组织模型，以及通过 OpenAI fine-tuning 或定价页所列服务定制 OpenAI 提供的模型。[OpenAI Services Agreement](https://openai.com/en-GB/policies/services-agreement/)

因此，“客户拥有输出”不能单独证明可把 GPT 输出批量用于外部 Qwen 翻译学生。

### 4.2 本项目的保守状态

| 活动 | 状态 | 处理 |
|---|---|---|
| GPT-5.6 Sol 输出直接成为 Qwen SFT/P2P label | **BLOCKED** | 需要 OpenAI 书面许可、适用 Order Form 或法律/合同负责人确认 |
| GPT 自动 judge 分数直接选择/训练外部学生 | **BLOCKED** | 视为模型开发数据，先确认条款 |
| 少量输出供人工理解质量，不进入训练/自动优化 | 受控研究 | 记录目的、数据范围和组织政策，不自动导入 dataset |
| OpenAI 平台内明确支持的 distillation/fine-tuning | 可另立方案 | 受当前可 fine-tune 模型与服务条款约束，且不满足本地权重目标 |

OpenAI 曾发布平台内 Model Distillation 工作流，重点是用较大 OpenAI 模型数据微调较小 OpenAI 模型；它不是训练外部开放权重模型的通用授权。[Model Distillation in the API](https://openai.com/index/api-model-distillation/)

GPT-5.6 Sol 官方模型页还显示该模型不支持 audio input，也不支持对 GPT-5.6 Sol 本身 fine-tuning；即使获准做标签，它也只是离线文本教师。[GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)

### 4.3 解除 BLOCKED 所需证据

至少取得一项明确、可归档的依据：

- OpenAI 针对本项目与外部 Qwen 学生用途的书面许可。
- 适用 Order Form/Service-Specific Terms 明确覆盖外部模型训练。
- 组织法律/合同负责人基于实际协议确认，并记录范围、地域、用途和期限。

不能用客服口头回答、论坛帖子、旧博客或“其他人也这样做”替代。

## 5. 默认教师治理

在 GPT 路线阻塞期间：

- 主数据教师使用固定 revision 的 Qwen3.8-27B。
- calibration/test 由双语人工审核，不让教师自己证明教师正确。
- 每个 label 保存 model revision、template、prompt、decoding、input/output hash。
- 教师输出经过 schema、append-only、source coverage、经文和 Saturday-only validator。
- 不同教师或人工来源不静默混合；训练 loader 可按 provenance 过滤。

开放权重教师降低 API 条款风险，但不消除 base license、训练数据和输出准确性责任。

## 6. 证道内容权利

每间教会/讲员的授权需要明确覆盖：

- 现场录音与原始视频。
- 周六和周日讲稿、字幕、大纲。
- 转写、翻译和人工编辑。
- 把正文发给外部 provider。
- 本地模型训练和长期保存。
- 生成衍生数据、LoRA 和 merged weights。
- 向本教会或其他教会部署/分发模型。
- 撤回授权、保留期和删除程序。

“视频公开可看”“教会内部使用”或“我们已经有字幕”都不能自动推出可训练和可再分发。

## 7. 圣经译本权利

分别确认：

- 英文版本全文是否可存储和训练。
- 中文版本全文是否可存储和训练。
- verse-level 对齐是否允许制作衍生数据。
- 会众端能否展示完整经文或仅显示短引用。
- 是否需要 attribution、版权声明或使用量限制。
- 模型权重是否可能被视为包含/再分发该译本内容。

保守技术设计：

- 模型主要学习书卷/人名/术语与引用模式。
- canonical verse text 由有许可的 deterministic resolver 返回。
- 受限全文不默认塞入 Context Pack 或训练语料。
- artifact 发布前对 memorization/长段复现做抽样测试。

## 8. 数据分类与存储

| 数据 | 默认存储 | Git | 远程诊断 |
|---|---|---|---|
| 原始音频/视频 | 受控对象存储/NAS | 禁止 | 禁止 |
| 完整 transcript/translation | 受控训练数据仓库 | 禁止，除非明确公开且去敏 | 默认禁止正文 |
| 去敏 fixture | repo | 可以 | 可以 |
| rights receipt | 受控元数据仓库 | 只放无敏感摘要/schema | 只放状态 |
| teacher raw output | 受控 staging | 禁止 | 禁止 |
| telemetry | 指标仓库 | schema 可以 | 不含正文 |
| model artifact | model registry/NAS | 禁止大权重 | 只发 hash/status |

正文日志与在线 telemetry 分仓。远程日志默认只包含 event type、延时、状态、匿名 ID、artifact hash 和错误分类。

## 9. Artifact 分发范围

为每个 artifact 标注：

```json
{
  "artifactId": "sermon-live-9b-v1",
  "baseLicense": "Apache-2.0",
  "trainingDataScopes": ["internal-only", "church-A-only"],
  "allowedDeployment": ["church-A-internal"],
  "adapterRedistribution": false,
  "mergedWeightRedistribution": false,
  "bibleTextIncluded": "resolver-only",
  "approvedBy": "...",
  "approvalAt": "..."
}
```

模型技术上能复制，不代表 receipt 允许复制。方案 C 的“统一发放”可以先发 App 与服务访问，不必同时向每间教会分发模型权重。

## 10. 删除与撤回

数据 lineage 必须支持：

```text
source -> transcript -> segment -> prefix -> teacher label
       -> dataset version -> training run -> adapter/merged/quantized artifact
```

撤回时：

1. 隔离来源及全部衍生数据。
2. 阻止受影响 dataset/model 新 promotion。
3. 判断是否需要重建 dataset 和重训模型。
4. 删除受控存储中的正文与 artifact，或按适用授权做限制。
5. 保留不含正文的删除审计。

没有 lineage 的大规模 synthetic 数据不可接受，因为无法响应来源撤回。

## 11. Go/no-go 清单

训练开始前：

- [ ] base/teacher revision 与 LICENSE/NOTICE 已归档。
- [ ] 每个 source 有 rights receipt。
- [ ] Bible 版本与训练/展示范围已确认。
- [ ] teacher 输出用途已确认；GPT 外部蒸馏仍为 blocked 时，loader 明确拒绝 GPT provenance。
- [ ] 数据仓库、Git 与 telemetry 边界已建立。
- [ ] 删除索引可以从 source 追到 prefix。

模型晋级前：

- [ ] adapter/merged/quantized 分发范围已批准。
- [ ] artifact 可追溯到 dataset、code、container 和 base revision。
- [ ] 未授权正文不在模型包、prompt、log 或 fixture 中。
- [ ] memorization/长段复现抽查完成。
- [ ] App/会众端版权与 AI 字幕提示已确认。

## 12. 需要负责人决定的事项

1. 谁是每间教会证道内容的授权人。
2. 首轮是只在本教会内部训练/部署，还是未来跨教会共享。
3. 选用哪套中英文圣经版本，以及精确允许范围。
4. 是否向 OpenAI 申请外部模型蒸馏书面许可。
5. 模型只部署为受控服务，还是未来发放 adapter/权重。
6. 数据与 artifact 的保留期、撤回 SLA 和最终删除负责人。
