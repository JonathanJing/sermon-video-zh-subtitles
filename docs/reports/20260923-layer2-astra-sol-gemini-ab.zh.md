# Layer 2 韩语模型 A/B 与第三方裁判：证据摘要

日期：2026-09-23。这里记录两轮 **shadow** 实验的可公开核对结论；完整 fixture、匿名稿、模型响应和 Gemini API 收据保存在本机 Git ignored 的 `artifacts/layer2-model-ab-20260923/`。模型会话中的 Astra/Sol 输出没有 OpenAI API request ID、token、价格或延迟收据，因此本报告不比较两者调用成本或速度。

## 第一轮：Astra 与 Sol 初译、两模型复核

从同一 2026-09-20 证道片段抽取 **14 个英文 source units／13 个韩语组**，两名初译模型分别只读冻结英文、相同任务要求和韩语术语／经文约束。Astra 与 Sol 均覆盖 14/14 单元、保持 13/13 组顺序，并保留锁定人名与两段经文。两名匿名审稿者都偏好 Astra 的口语表达，但这只是小样本偏好，不能推出整篇优势。

审稿包含 Sol、Astra 两份匿名译稿，以及加入六处已知错误的控制稿。**Astra reviewer 与 Sol reviewer 都检出 6/6 控制错误，对原始两稿没有报告实质错误。** 首次未注入完整韩语 policy 时，两者都漏掉术语／经文规则问题；后续复核必须接收冻结 policy 和锁定原文。Gemini `gemini-3.8-flash` 用相同匿名包再次检出 6/6 控制错误，同时对两份原稿标出同一处 *get affirmed* 的轻微措辞疑点；这项判断留给韩语人工审核。

本轮选取的 English Source Package JSON hash 为 `5b3c5e15d37f70aea047823710d7c45cd247b161509a1f37a73f4e1598c471a7`，韩语 policy 绑定的包 hash 为 `4d645ff0aad0b55b2eb913fd0749ebcb3bed010ddfc037e89e1f8a98f44a227b`；anchor 内容相同，但包内 anchor 路径不同。因此本轮只可比较英文内容上的模型输出，**不能形成该 policy 的正式 Layer 2 候选**。

## 第二轮：Astra 初译、Sol 逐组复核、Gemini 裁判

使用与韩语 policy 身份相符的 `ready_for_translation` 英文包，扩展至完整 **178 秒片段的 45 个英文单元／44 个韩语组**。旧人工批准译文未提供给初译或复核模型。Astra 草稿覆盖 44/44 组、45/45 单元，固定人名和两处经文摘句通过确定性检查；Sol 标出 3 处轻微语义问题、4 条风格意见和 2 项不确定性。

Gemini 的独立全文复核报告 **0 个问题**，与 Sol 的具体发现不一致。把五个争议组交给 Gemini 定向裁决后，**其中两处确认需要修订**：一处把“救主对我们怀有美意”写成具体赐物动作；另一处把讲员对两种资料的口语重启误写成撤回前项。其余三处判为可接受或仍待人工判断；同一 *get affirmed* 译法在两轮 Gemini 判定中也不一致。这说明第三方模型全篇“零问题”不能替代逐组复核，更不能单独授予通过。

## 采用范围

实验支持新运行采用 **Astra 初译 → Sol 独立逐组复核**，并保留确定性 coverage、语言插件、经文／术语政策和逐组人工批准。该组合已写入 [Layer 2 生产操作说明](../target-language-astra-sol-production.zh.md)，但本实验没有生成新的 `human_translation_approved` candidate，没有进入 Layer 3，也没有更改已有批准稿。扩大到整篇证道、其他 locale、成本／延迟及母语人工质量评价仍需各自独立证据。
