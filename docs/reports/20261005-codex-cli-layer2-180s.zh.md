# 固定三分钟 Codex CLI 翻译／复核流程实测

2026-10-05，完成固定 180.013167 秒样本的中文翻译和独立复核：39 个冻结英文单元、13 个原分组，经现有 Layer 2 分组循环实际调用 Codex CLI 26 次。每组 Astra 普通速度翻译 → 独立 Sol Fast 复核，medium 推理；**13 组全部机器通过，测试 evidence 已汇总。** 未使用旧译文或项目 API key，没有重跑 ASR/TTS/发布。

## 调用与实际验收

新增 [测试入口](../codex-layer2-test.zh.md) 验证 fixture 的模拟范围、固定媒体身份和分组计划，将 [CLI transport](../../scripts/codex_layer2_transport.py) 注入现有 [Layer 2 runner](../../scripts/run_target_language_models.py)。因此本轮不是上一轮独立片段脚本的循环复制：使用现有逐组提示词、覆盖、语义检查和 evidence 聚合，实际测试程序调用 CLI 的路径。

| 检查 | 结果 |
|---|---|
| 原计划／源顺序 | 13 组，39 单元，各覆盖一次 |
| 模型调用 | 26 个唯一 Codex thread/request ID；每组翻译／复核独立 |
| 完成回执、无工具、stdout/file 一致 | 26 次通过 |
| JSON Schema、group/unit 身份、coverage 子串 | 全部通过 |
| Sol 语义四项检查、未决 issues/uncertainty | 13 组 pass，无未决项 |
| 同一实现、同参数恢复 | 0 新调用；26 个回执及 group/raw/evidence 哈希不变 |
| 代码补强后尝试恢复旧身份 | 明确拒绝实现变化，0 新调用、原 evidence 不变 |
| 语言插件、正式 candidate admission、人审 | not_run |
| controller 生产 dispatch、音频、发布、设备 | not_run |

固定媒体 SHA 为 `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`。输入来自已有三分钟测试 fixture 的模拟人工收据；本次强制 `simulationOnly=true` 的测试分支，不调用正式 source 准入，也不伪造 formal ready/human approval。输出只能称为测试机器 evidence，不能称为正式 Layer 2 Candidate 或全四层交付。原生产入口仍保留 API／人工／plugin 门禁；canonical controller 尚未接入此 CLI transport。

## Token、时间与速度

CLI `0.159.0-alpha.12.1`，ChatGPT 登录、API key 环境移除。每次调用带独立超时和私有回执，没有 API fallback。下面用各角色所有输出 token 除以对应模型进程时间之和，避免把各组 TPS 做简单平均。

| 角色 | 调用数 | 进程时间合计（秒） | 输入 token | 缓存输入 | 输出 token | reasoning token | 会话输出 token/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Astra 普通翻译 | 13 | 144.155 | 210,723 | 24,576 | 2,916 | 0 | 20.23 |
| Sol Fast 复核 | 13 | 189.684 | 210,774 | 132,352 | 10,830 | 5,914 | 57.09 |

模型进程区间合计 333.839 秒，约 5.56 分钟；这不是包括测试准备、测试命令校验和报告整理的整次墙钟耗时。翻译单次 8.42–13.77 秒，复核 10.72–21.84 秒。每次开始、结束和耗时由 accounting observation 记录。

缓存输入是输入子集；reasoning 保留 provider 报告，不重复相加；provider 未单独返回 total token 时保持 null。速度含 CLI 启动、认证、prefill、排队和等待，纯生成时间/TPS 未取得。服务端实际模型／速度档位未独立返回，记录 requested model/tier 与 null server identity；测得吞吐不证明固定 Fast 加速倍数或订阅额度倍率。

本轮总输入 421,497 token，其中缓存 156,928 token；输出 13,746 token。输入明显包含 CLI 固有代理上下文，不能只按三分钟英文长度估算额度。项目 API 调用为 0，但没有独立计量 ChatGPT 额度实际扣减或金额。

## 内容与复盘

Sol 对多组作了修订再给 pass，例如第1组将“逃出沙盒”改为“走出沙盒”，避免额外的逃脱意图。其余逐组证据和全文在本地 `review.md`；模型结论不代替源音频裁定或人工内容审核。本轮没有同输入 API 对照，也不建立正式内容质量或速度优越结论。

复盘发现并修复：

1. CLI 原始返回初次写入沿用默认权限；补上 private 写入，原回执权限也收紧为0600，字节和哈希不变。
2. 测试实现身份原先在循环 finally 才落盘；增加首次 dispatch 前的 sibling context binding。强制终止前也留下实现绑定；旧目录没有绑定时拒绝推断身份，代码变更须新 run。
3. API 与 CLI 使用不同缓存 fingerprint；CLI binding 包含二进制、适配器、schema、速度档位等。同 run 可恢复，跨 run carry-forward 尚未开放；未知调用仍保留 started marker并阻止重发。

真实26次调用及原版本恢复发生在上述两处结构补强之前，原实现 SHA 和可核验源码快照留在 `frozen-implementation/`。补强后以定向测试验证权限和身份门禁，并实际确认当前代码拒绝旧目录实现漂移；没有为了这两处结构变化再消耗26次真实模型调用。CLI transport本身未在运行中改变。代码／CLI实现变化后继续跑该样本应使用新的输出目录，不改写本轮回执。

## 证据

Ignored 根目录 `artifacts/codex-cli-layer2-180s-20261005/`：`request.json`、`run-identity.json`、`test-context.json`、`test-report.json`、13组各自 policy-preview/raw/cache、`_cli_calls/` 的26次返回、`evidence.json`、`accounting/`、`validation-first.json`、`resume-before.json`、`resume-verification.json`、`post-fix-drift-check.json`、`review.md` 和 `frozen-implementation/`。原始文本、返回、认证和媒体不入 Git；Git 保存实现、定向测试、运行说明和这份复盘。

[前一轮单片段与 Fast 对比](20261005-codex-cli-fragment-translation-review.zh.md) 只证明孤立调用；本轮新增证据证明固定三分钟测试可由现有分组流程完成翻译和独立复核。正式 production backend、controller dispatch、language plugin 与 candidate admission 的切换仍是后续工作。
