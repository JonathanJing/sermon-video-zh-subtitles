# 新任务 API 优先运行策略切换

2026-10-05，操作者在 Codex CLI 高并发故障及社区限额调查后决定：后续开发、Beta 测试与正式内容生产先使用 OpenAI API。开发／Beta 对应 `tongxing-dev`，正式内容生成对应 `tongxing-prod`；两个项目继续复用各自的 runtime key。此决定替代此前“文字与监督默认 CLI、API 仅限备用”的新任务策略，不更改历史收据或正在运行任务的后端身份。

本次代码切换范围：standalone Layer 2 的 Sol 文字调用改为显式选中 Project 的单次 Chat Completions API；canonical Layer 2 恢复已有的绑定预算 API transport（正式执行仍要求预算授权）；固定 605.5 秒 L2 诊断入口默认选 API；本地和后端触发的 Supervisor 默认选已有的可恢复 Agents API 会话；周六 harness、post-live 阅读稿、共用文字 JSON 入口、英文机审、笔记和阅读稿的默认分支改走 API。Layer 1 的 Sol 6.1 来源机审纳入现有单次请求与费用上限，估算费率取官方 Standard 档位并按 cache-write 更高的输入费率预留。显式的 Codex CLI 诊断入口仍保留，只有手动指定才使用，不作为 API 异常的自动回退。

生产安全边界：本地新模型运行从[环境启动器](../openai-minimal-project-setup.zh.md)选中项目；API key 不入 Git／日志。Layer 2 的 `.started.json`、原始响应和预算 reservation 继续区分完成与未知；网络错误不触发新的付费 attempt。旧运行不能原地从 CLI 改为 API，须按原身份对账后创建新的运行身份。Agents API 既有会话保留相同恢复锁，不自动创建第二会话。云端服务仍从 Secret Manager 获取原有 key；本次本地切换不证明云端两个 Project 的 secret 已迁移。

严格预算的 canonical L2 当前只允许 `default` tier，standalone L2 使用 `fast`；代码按实际绑定合同选择 tier。fast 预算扩展需另开版本和新的预算批准，不能在旧授权下换档。

当前验证包括两项目的本地配置检查、两项目对 `gpt-6.1-sol` 和 `gpt-6-luna` 的模型元数据 GET（均 HTTP 200），以及无真实模型调用的路由／预算／Supervisor 定向测试。模型 GET 不证明实际推理权限；Agents API 会话、fast tier 实际生效、三语完整翻译复核、内容批准与后续 L3／L4 发布均需新的实跑收据。旧 605.5 秒来源诊断及学习产品 CLI 实验入口尚未迁移成通用 API producer；不得把它们作为新 API 默认流程调用。
