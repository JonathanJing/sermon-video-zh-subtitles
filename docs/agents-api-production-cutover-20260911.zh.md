# Agents API 生产切换记录 · 2026-09-11

## 安装与范围

生产目录的本地 Supervisor 默认后端已改为 `agents-api`，模型为 Astra Medium。原 SDK 仅作为显式回退。同步 19 个相关脚本、测试和文档，逐文件核对安装前后 SHA-256；保留既有未提交修改，并合并另一任务新增的 Cloud Run Job 退役说明。未提交或推送 Git。

恢复材料保存在 `artifacts/agents-api-cutover-20260911/manifest.json` 与 `before/`。回退时须先确认没有未决会话、工具执行或租约，核对安装后 hash，再按清单恢复相应备份；禁止覆盖后续修改。新增文件按清单处理，不清理其他产物。

## 当前设计

Codex 调度唤醒本地入口 → Agents API session 选择受限工具 → 本机确定性流程执行 → GCS 保存源、租约、审批、QA 和交付证据。服务端只收到日期、动作枚举和状态布尔值；源内容、路径、配置及审批细节不发送给控制层模型。工具重放、未知会话创建结果、取消未确认均有持久化门禁。

详见 [Supervisor 契约](sermon-production-supervisor-agent.zh.md)、[本地生产 runbook](codex-local-production-runbook.zh.md) 与 [每周发行清单](tongxing-weekly-release.zh.md)。双 PDF、Context Pack 和配音发行仍分别以自己的 QA、审批及交付收据为准。

## 已验证

- 离线完整回归：根目录 1,018 项、配音 POC 259 项，共 1,277 项通过；零失败、零跳过。本轮未运行独立 Promptfoo 真实集，不把此前缺依赖的 3 项跳过算作通过。
- 两个真实 Agents API 合成状态用例：缺审批时不生成；模拟可执行状态下生成工具只调用一次。没有实际媒体生成。
- 实际 GCS 状态的只读 API 用例：目标 `2026-09-13`，返回 `waiting_for_matching_sunday`，零生产变更。
- 当前 Firebase 发行完整 GET、大小和 SHA-256 检查：21 个公共文件全部通过，6 个 MP3 的 HTTP 206、Content-Range 和首段 hash 全通过。
- 生产 registry 位于 `artifacts/weekly-release/registry`，head 为 `rel_44dc27de59267ab93ce8dccb`、generation 0，完整保留 6 周，状态 `published_http_verified`。没有重新部署网页、音频或 App；真机刷新与离线使用未在本轮复测。

安装后的正式入口（未指定 backend，验证默认值）已完成只读验收：`agents-api`、根 session `completed`、2 次工具调用、attemptedStages 为空；最终业务状态 `observed / waiting_for_matching_sunday`。收据为 `artifacts/agents-api-cutover-20260911/production-shadow.json` 和 `acceptance.json`。这不表示 9 月 13 日生产完成。API token 计数 best-effort，金额保持 unknown，须与 Platform 账单核对。

## 执行与调度状态

用户明确授权后，已通过正式入口执行 `2026-09-13` 的生产检查（execute、默认 Agents API、禁用 SendGrid、复用当前源状态）。退出码 0，根 session completed，2 次工具调用，最终业务状态为 `observed / waiting_for_matching_sunday`，attemptedStages 为空。当前源尚未匹配目标周日，因此未启动下载、timeline 或 PDF 生成；不能称为本周产物已完成。该次使用 `--skip-source-refresh` 验证既有状态；每周调度使用正常源刷新路径。收据：`artifacts/agents-api-cutover-20260911/production-run.json` 与 `acceptance.json`。

本机已创建并回读核验自动化「每周周六双 PDF 与周日 Context Pack」，ID `pdf-context-pack`，状态 ACTIVE，跟进当前任务。实际执行时间为 America/Los_Angeles 周六 18:00、20:00、22:00 和周日 08:00；调度器其他周末唤醒时段由提示词跳过。无变化或不可行动时保持安静，仅重要变化、失败、完成或需要用户动作时在 Codex 内报告。

调度继续保留人工窗口审批、源绑定、租约、QA、发布与未决会话门禁；禁用 SendGrid，不重复生成已完成周次。调度安装回执：`artifacts/agents-api-cutover-20260911/automation-installed.json`。定时配置已启用，首次未来计划运行尚未发生；本次手动 execute 验收与未来调度实际唤醒分别记录。
