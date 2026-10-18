# 复盘：20261017-deepseek-translation-review-ab

数据见同目录 `INDEX.md`、`manifest.json` 与脱敏收据。

## 结论先行

本轮是六段冻结英文的单批 Layer 2 实验，不是生产运行。A 臂为 `gpt-6.1-sol`（初译 high、独立审核 medium），B 臂为 `deepseek/deepseek-v4.1-flash-1017`（初译与审核均 high）；两臂使用相同输入、相同任务说明和结构化 schema，经一次盲化 `gpt-6-astra` medium 比较。

运行以 `outcome.json status=succeeded` 结束，五次模型调用均返回、无工具调用。DeepSeek 初译比 Sol 快 53.5%，但 DeepSeek 审核慢 7.32 倍，初译加审核合计 191.321 秒，相比 Sol 的 75.102 秒慢 2.55 倍。盲评认为两臂均无实质语义错误，Sol 以术语惯例和中文自然度小胜；DeepSeek 两次均未遵守外层 JSON schema，必须本地确定性归一化，因此当前不能进入 canonical Layer 2。

本轮 `productionEligible=false`、`humanApproval=false`。未发布页面、未生成音频，也未执行真机或场地验收。

## 总时间

- 从第一份 DeepSeek 事件文件创建到汇总完成约 4 分 58 秒；五次模型调用合计 4 分 36 秒。
- 本轮分两次 runner 启动：第一次在 DeepSeek 初译成功返回后暴露本地解析器只接受对象的问题；第二次复用该成功结果，没有重复派发。
- 未发生等待人审、凭据或服务；约 22 秒为启动、落盘、评分及本地解析修复开销。
- 没有同模型同配置的上一轮可比运行。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | 输出 token | 速度 | 费用 | 证据 |
|---|---|---|---:|---:|---:|---:|---|---|
| L1 来源 ASR | not_run | | 0 | 0 | 0 | | US$0 | |
| L1 词级对齐（MFA） | not_run | | 0 | 0 | 0 | | US$0 | |
| L1 英文机器评审 | reused 冻结 reference | | 0 | 0 | 0 | | 无新增调用 | `summary.json` source |
| L2 初译 B | DeepSeek V4.1 Flash 1017／OpenRouter Responses | high／default | 1 | 24.284 秒 | 2,370 | 97.59 token/s | 未取得供应商金额收据 | `deepseek-translate/receipt.json` |
| L2 初译 A | GPT-6.1 Sol／OpenRouter Responses | high／default | 1 | 52.276 秒 | 2,007 | 38.39 token/s | 未取得供应商金额收据 | `sol-translate/receipt.json` |
| L2 独立审核 B | DeepSeek V4.1 Flash 1017／OpenRouter Responses | high／default | 1 | 167.036 秒 | 16,815 | 100.67 token/s | 未取得供应商金额收据 | `deepseek-review/receipt.json` |
| L2 独立审核 A | GPT-6.1 Sol／OpenRouter Responses | medium／default | 1 | 22.826 秒 | 1,455 | 63.74 token/s | 未取得供应商金额收据 | `sol-review/receipt.json` |
| 文本质检（盲评） | GPT-6 Astra／OpenRouter Responses | medium／default | 1 | 9.267 秒 | 373 | 40.25 token/s | 未取得供应商金额收据 | `blind-judge/receipt.json` |
| L3 配音、回转写、音频质检 | not_run | | 0 | 0 | 0 | | US$0 | |
| L4 构建与发布 | not_run | | 0 | 0 | 0 | | US$0 | |

DeepSeek 审核的 16,815 个输出 token 中，15,731 个是 reasoning token，占 93.55%；因此高 token/s 不代表更快完成任务。收据只确认请求模型、用量与墙钟时间，没有独立的 OpenRouter 发票或实际费用回读。

## 质量结果

| 指标（审核后） | DeepSeek | Sol | 解释 |
|---|---:|---:|---|
| BLEU-zh | 57.1119 | 57.4514 | 参考为历史 Sol-reviewed，存在方向性偏差 |
| chrF2 | 49.7843 | 54.8715 | Sol 较高 |
| 严格术语命中 | 20/21（95.24%） | 18/21（85.71%） | 只认参考中的精确字符串，音译或有效变体可能被漏计 |
| 审核修改段数 | 5/6 | 2/6 | DeepSeek 改正了 `All clear`、`night clerk`、`rescued` 等措辞 |
| 盲评总分 | 18/20 | 20/20 | Astra：Sol 小胜，confidence=medium |
| 严重语义错误 | 0 | 0 | 仅为模型盲评，不是人工裁定 |
| schema 合规 | 0/2 | 2/2 | DeepSeek 两阶段均需确定性归一化 |

盲评指出 DeepSeek 的“那位‘我是’”“我的祷告都是，希望……”和“情感上我感觉一点都不好”较生硬；Sol 使用“自有永有者”，整体更适合会众阅读。DeepSeek 审核本身有价值：把 `All clear` 从“全部安全”改成“警报解除”，把 `night clerk` 明确为“值夜班的前台职员”，并区分普通“获救”与属灵“得救”。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| DeepSeek 初译 | 返回顶层数组，译文字段名为 `english`，未遵守对象 schema 与 `zh` 字段 | OpenRouter/Codex 到该模型的 structured-output 约束未被模型遵守 | 占用资源后 | 保留原始响应，确定性包装数组并将译文字段改名；复用已返回结果，不重发 | 后续四次调用与汇总完成；收据标记 `schemaConformant=false` | 本报告 PR |
| DeepSeek 审核 | 再次返回顶层数组；审核耗时 167.036 秒、reasoning 15,731 token | 相同 schema 遵循问题，且 high 审核推理失控 | 占用资源后 | 保留原始响应并确定性包装；生产准入保持阻断 | 盲评与自动指标只读取归一化副本 | 本报告 PR |
| 报告 runner | 第一次启动只接受对象，在成功调用后抛出 `AttributeError` | 预检未覆盖该模型忽略 schema 的响应形状 | 占用资源后 | 增加已返回结果对账与归一化；第二次启动复用首笔结果 | 五份收据唯一、无重复 DeepSeek 初译调用 | 本报告 PR |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 在付费 A/B 前做一个最小 schema smoke，并验证顶层类型及字段名 | DeepSeek 0/2 schema 合规 | 更早阻断不兼容模型 | 工程 | 新实验 runner 前置检查 |
| 速度／成本 | 为 DeepSeek reviewer 测试 low 或显式 reasoning cap；不得把本轮 high 直接用于生产 | 审核 167.036 秒、15,731 reasoning token | 降低 7.32 倍审核延迟和未知费用风险 | 工程 | 后续独立实验，不由本轮自动派发 |
| 质量 | 增加多讲员、多术语批次和人工双语盲审 | 本轮只有六段，Astra confidence=medium | 判断自然度差异是否稳定 | 内容／工程 | `DEV-EXP-004` 或新稳定 ID |
| 流程 | 将原始 schema 违规计入硬门禁，不以归一化成功代称模型合规 | DeepSeek 两次均需归一化 | 防止实验兼容层进入 canonical producer | 工程 | 后续 runner 合同 |

## 实际覆盖范围

- L1：复用冻结、已音频审核的英文 reference；没有新 ASR、MFA 或英文机器评审。
- L2：执行六段中文初译、各自独立审核、自动 reference 指标和一次盲化模型评审。
- L3：not_run；没有 TTS、回转写、同步或音频质检。
- L4：not_run；没有页面构建、发布、HTTP、浏览器、设备或场地证据。

## 遗留状态

- 原始 prompt、模型输出、事件和 stderr 仅留在 ignored 的 `artifacts/deepseek-translation-review-ab-20261017/`，不进入 Git。
- 没有未决远端调用、job hold、Spark 资源占用或发布产物。
- DeepSeek 仍是实验候选；本轮不修改 canonical 模型政策、生产缓存或人工批准。

## 外部可见的变化

- 仅发布本脱敏 docs-only 运行报告 PR。
- Dev、Beta、TestFlight、正式页面、推送、设备播放和场地验收均为 `not_run`。
