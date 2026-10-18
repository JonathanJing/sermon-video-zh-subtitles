# 复盘：20261017-deepseek-translation-review-low

数据见同目录 `INDEX.md`、`manifest.json` 与脱敏收据。

## 结论先行

本轮复用上一轮相同六段英文、DeepSeek high 与 Sol 收据，只新增 DeepSeek low 初译、DeepSeek low 独立审核及一次三方盲评。运行最终 `succeeded`，`productionEligible=false`、`humanApproval=false`。

把 DeepSeek reasoning 从 high 改为 low 后，初译没有变快（25.083 秒，对 high 24.284 秒）；审核从 167.036 秒降至 89.880 秒，快 46.2%，reasoning token 从 15,731 降到 9,379。两阶段合计从 191.321 秒降到 114.963 秒，但仍比 Sol 的 75.102 秒慢 53.1%。盲评排序为 Sol > DeepSeek high > DeepSeek low，三者均无严重语义错误。DeepSeek low 仍是 0/2 schema 合规，不能进入 canonical Layer 2。

## 总时间

- 从 low 初译事件文件创建到汇总完成约 2 分 27 秒；三次成功模型调用合计 2 分 11 秒。
- 两次 DeepSeek low 调用仅在首次 runner 中执行；盲评 schema 预检失败后，第二次 runner 复用它们，只重试盲评。
- 无人工、凭据或服务等待；未取得供应商金额收据。

## 各层模型、耗时与速度

| 阶段 | 模型 | reasoning／tier | 调用 | 耗时 | 输出 token | reasoning token | 速度 | 费用 |
|---|---|---|---:|---:|---:|---:|---:|---|
| L2 初译 | DeepSeek V4.1 Flash 1017 | low／default | 1 | 25.083 秒 | 4,348 | 2,865 | 173.34 token/s | 未回读 |
| L2 独立审核 | DeepSeek V4.1 Flash 1017 | low／default | 1 | 89.880 秒 | 10,195 | 9,379 | 113.43 token/s | 未回读 |
| 三方盲评 | GPT-6 Astra | medium／default | 1 | 16.038 秒 | 583 | 252 | 36.35 token/s | 未回读 |
| DeepSeek high 对照 | reused | high／default | 0 | 191.321 秒 | 19,185 | 17,280 | | 无新增调用 |
| Sol 对照 | reused | high 初译／medium 审核 | 0 | 75.102 秒 | 3,462 | 1,226 | | 无新增调用 |
| L1、L3、L4 | not_run | | 0 | 0 | 0 | 0 | | US$0 |

Low 初译的 reasoning token 反而比 high 增加 85.0%；单批结果说明 reasoning 标签不保证每次调用单调减少用量。

## 质量结果

| 指标（审核后） | DeepSeek low | DeepSeek high | Sol |
|---|---:|---:|---:|
| BLEU-zh | 58.5100 | 57.1119 | 57.4514 |
| chrF2 | 52.1755 | 49.7843 | 54.8715 |
| 严格术语命中 | 19/21 | 20/21 | 18/21 |
| 审核修改段数 | 0/6 | 5/6 | 2/6 |
| 盲评总分 | 17/20 | 18/20 | 20/20 |
| 严重语义错误 | 0 | 0 | 0 |
| schema 合规 | 0/2 | 0/2 | 2/2 |

自动指标使用 Sol-reviewed reference，存在方向性偏差。盲评指出 low 把 `tacos` 译成不够准确的“墨西哥卷饼”，并保留“救援，是的，完成了”等不自然表达；high 的直译也略生硬，但整体优于 low。Low 审核没有修改任何一段，说明降档减少了审核纠错贡献。

## 错误

| 阶段 | 现象 | 原因 | 发现时机 | 处理 | 结果 |
|---|---|---|---|---|---|
| DeepSeek low 初译／审核 | 两次仍返回顶层数组，初译还把译文字段命名为 `english` | structured-output 约束未被该模型遵守 | 占用资源后 | 保存原始响应并确定性归一化 | 收据标记 `schemaConformant=false`；生产阻断 |
| 三方盲评预检 | Provider HTTP 400，`uniqueItems` 不允许出现在 response schema | 本地 judge schema 使用了不支持的 JSON Schema 关键字 | 派发前／未完成推理 | 删除该关键字并只重试盲评 | 后续盲评成功；DeepSeek 调用未重发 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 跟踪 |
|---|---|---|---|---|
| 速度／成本 | 若继续研究 reviewer，应增加显式输出／reasoning cap，而非只改 low | low 审核仍有 9,379 reasoning token、89.880 秒 | 避免审核推理失控 | 后续独立实验 |
| 质量 | 增加多批次和人工双语盲审 | 单批盲评 low 17/20、无严重错误 | 判断质量差距是否稳定 | `DEV-EXP-004` 或新稳定 ID |
| 预检 | 将 provider 支持的 JSON Schema 子集做本地静态检查 | `uniqueItems` 被派发前拒绝 | 避免无效请求 | 实验 runner 合同 |
| 准入 | schema 合规继续作为硬门禁 | low 与 high 均 0/2 | 防止归一化掩盖接口不兼容 | canonical Layer 2 不变 |

## 实际覆盖范围

- L1：复用冻结英文 reference；未运行 ASR、MFA 或英文评审。
- L2：新运行 DeepSeek low 初译与独立审核；复用 high、Sol；新运行三方盲评。
- L3、L4：not_run；无音频、发布、HTTP、浏览器、设备或场地证据。

## 遗留状态

- 原始 prompt、响应、事件和 stderr 仅留在 ignored `artifacts/deepseek-translation-review-low-20261017/`。
- 没有未决远端调用或资源占用；失败盲评明确为 schema 400、未完成推理。
- 模型政策、生产缓存和人工批准均未改变。

## 外部可见的变化

- 仅发布本脱敏 docs-only 运行报告 PR。
- Dev、Beta、TestFlight、正式页面、推送、设备播放及场地验收均为 `not_run`。
