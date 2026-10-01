# Strict 受控流程入口与测试前开发边界

本批补齐 PR #177 之后的实际调用接线，保持生产默认路径不变。`run_locale` 会执行真实 producer/validator 的组合；这里的开发回归使用模拟 transport，不能代替从固定 dev 进行的 fresh 3 分钟验收。

## 当前入口

1. 使用现有 Layer 1 工具准备真实剪辑、English Source Package、anchors 和独立源审核凭据。新剪辑必须保留自己的媒体 hash 与 approved window，不能用历史缓存声称新生成。
2. 可信调用者在同一个 LOGC session 中调用 `sermon_strict_locale.run_locale`，显式提供冻结的源/policy/rubric 字节、group plan、真实依赖图、共享 BudgetStore、已授权 bounds、单次 transport 与实测 usage resolver。入口先验证所有组和完整覆盖，再调用 `sermon_strict_controller.run_group`。
3. 每组的生成、只读审核、有限审核恢复与不可变内容修订复用现有预算和锁。未知结果或日志失败不能购买新尝试。返回 `machine_review_passed` 只代表组机器审核通过；locale 仍须运行真实语言插件和公共 Candidate bridge。
4. locale 把机器 Candidate、语言回执与 revision bindings 写入不可变目录，返回 `waiting_human`。人工审批使用现有工具与冻结 rubric；入口不生成批准。把实际当前 revision roots 和独立审核凭据交给 `AdmissionBoundary`，再消费唯一 `prepare_layer3` intent。
5. Layer 3 准备、renderer、冷/热缓存 unit receipt 和 Audio Package builder 显式传入同一个 `strict_rubric`（CLI 为 `--strict-rubric`）。源、voice、音频解码、同步和独立听审门槛不变。
6. Layer 4 保持真实 preparation/stage 产物身份，交付绑定须重新验证当前 strict Gate、共享预算、人工凭据和资产。canonical staging receipt 不冒充 legacy weekly release plan；本地 staging 不代表部署、HTTP 或设备验收。

## 冻结范围与剩余门槛

| 项目 | 开发/运行边界 |
|---|---|
| D1–D5 私有模块与单组恢复 | #177 已提供；本批补确定性组/locale 调用入口 |
| 全量 locale 机器 Candidate | 每组生成和审核后运行实际公共/插件 bridge；保留人审暂停 |
| strict-v3 Layer 3 | 原有自然语速 render→unit receipt→Audio Package 路径传递冻结 rubric；不会在失败时替换成 text-only |
| 三语 full-text 本地交付 | 使用已有正式资产构建和 staging 的审核/解码门禁；独立绑定实际产物，不写部署授权 |
| 默认 canonical dispatcher / rollout | 不切换；显式入口用于受控开发与后续获准验收 |
| target-to-target 依赖修复 | 当前 strict prompt 只使用冻结 English context；若 graph 声明跨目标组上下文，调用前阻断，仍需独立选择性失效 adapter |
| 模糊范围 decision responder | 保留确定性人审/工程升级停止；真实 responder 未接入，不声称该分支自动完成 |
| 可选音频 compaction、第二份 short-script | 不属于本次 full-text 自然语速路线；选择它们时需要各自 strict 接线和独立审核 |
| Text-only 交付 | 必须有同 locale `audio_unavailable` package；正式三语音频 staging 不是 text-only producer |
| 真实 provider usage / 费用 | 可信 resolver 必须报告实测值；缺失保持 unknown 并保留 reservation。预算引用 hash 本身不是调用授权 |
| 完整测试 | 等待父任务协调固定 dev、获准预算、实际源/voice/工具与具名人工门槛；本批聚焦检查不属于 D6/D7 验收 |

本批都是后端代码，不改变已安装 App。既有其他 native PR 是否需要新构建/审核仍按各自差异判断。没有 merge、部署、App Store 发布或真实付费调用。
