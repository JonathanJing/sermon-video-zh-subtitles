# Agents API：从生产到页面发行

通过 `--release-workflow-config /absolute/path/release-workflow.json` 显式启用。未提供参数时，现有双 PDF Supervisor 的工具和完成判定保持原合同。扩展目前只支持 `--agent-backend agents-api`；使用 Supervisor 当前配置的调度模型（默认 `gpt-6-sol`）、现有 OpenAI 凭据与 `environment: none`，不新增云端沙箱。

## 与四层生产合同的关系

本文描述当前中文页面发行的 legacy Agent adapter，不取代[四层生产接口](multilingual-production-interfaces.zh.md)。`generate_audio_candidate` 当前耦合部分 Layer 2／3 行为，`record_published` 只登记旧 registry；除非执行链实际产出并校验四个正式包，否则这里的 `complete` 只能按本流程自身的 legacy scope 解读，不能报告为 `four_layer_release`。

今后的预制多语言生产必须从 `ready_for_translation` 的 `English Source Package` 开始；目标语言文字、音频和发布分别消费上一层冻结输出，不得由发布 Agent 补译、改写音频或提升上游审核。迁移期间旧工具可以继续执行，但 Agent 的状态与总结必须同时标明实际 scope 和缺少的规范包。

## 分工与状态

Agent 检查状态并调用命名工具；本地代码决定动作是否允许，构造固定命令，运行模型或发行程序。工具参数不接受命令、路径、任意目标、审批内容。现有模型并发与机器路由由各阶段执行器负责。

| 动作 | 必要条件及完成证据 |
|---|---|
| 原来源准备、转写与双 PDF | 现有来源、人工范围、质量、租约和交付校验 |
| `generate_audio_candidate` | 当前 bridge 的来源与生产目录一致；复用已有候选和缓存 |
| `sync_audio` | 原声锚点与时序检查通过；组装同步音轨 |
| `build_page` | 最终音轨有有效人工听审收据；沿用原页面构建和指纹绑定检查 |
| `prepare_release` | 合并到既有发行 registry，保留历史页；明确列出允许更新的页面 |
| `deploy_release` | 有绑定本次发行包、站点、配置和 registry 父版本的发布授权 |
| `verify_release` | 核验真实 HTTP 文件哈希和音频 Range |
| `record_published` | HTTP 证据与当前 registry 一致，登记 `published_http_verified` |

这个 legacy 扩展启用后，只有发行登记与完整证据检查通过才报告本流程的 `complete`。这不等于 `four_layer_release`，也不表示手机或现场验收完成。默认最小状态 `sermon-agent-state-minimal-v1` 保持兼容；扩展使用 v2，额外提供 `workflowScope` 和 `workflowComplete`。完整路径、稿件、日志和授权详情只保存在本地。

## 配置

以下是结构示例，路径需替换成已验证的真实资料。日期必须是主日。所有工作、页面候选、发行、registry 和执行收据目录互不包含；不把凭据写入此 JSON。

```json
{
  "schemaVersion": "sermon-release-workflow-v1",
  "weeks": {
    "2026-09-20": {
      "bridgeConfig": "/absolute/path/bridge.json",
      "work": "/absolute/path/current-source-audio-job",
      "candidate": "/absolute/path/new-page-candidate",
      "release": "/absolute/path/new-release",
      "registry": "/absolute/path/existing-release-registry",
      "stateDir": "/absolute/path/release-action-receipts",
      "authorization": "/absolute/path/release-authorization.json",
      "project": "ai-for-god",
      "site": "ai-for-god-sermon-audio",
      "origin": "https://ai-for-god-sermon-audio.web.app",
      "replacePages": []
    }
  }
}
```

`work` 必须精确匹配 bridge 对当前源规划的任务目录。可以先按现有 bridge 检查命令获得该路径。初始 registry 仍通过[每周发行流程](tongxing-weekly-release.zh.md)建立，不自动把未知线上内容登记为基线。当前适配器支持专用 Firebase `SITE.web.app`；自定义域名尚未接入。

```sh
python scripts/run_codex_local_sermon_production.py \
  --sunday 2026-09-20 \
  --release-workflow-config /absolute/path/release-workflow.json \
  --mode shadow
```

使用项目现有的状态文件、Secret 和其他生产参数。检查通过后，将模式改为 `execute` 可执行已允许的步骤。只读检查后半段也可运行：

```sh
python scripts/sermon_release_workflow.py \
  --config /absolute/path/release-workflow.json --sunday 2026-09-20
```

缺少人工听审或发布授权时，保持等待。准备发行包后，本地 snapshot 的 `evidence.requiredReleaseAuthorization` 给出准确绑定字段；操作者的授权收据另需 `approvedBy`、`approvedAt`。Agent 没有写入或自授该授权的工具。

## 长任务与恢复

后半段工具启动持久化本地任务，立即返回状态；任务运行与 Agent 连接分离。每次执行调用保留同一输入身份、任务 ID、命令摘要、日志与状态。再次运行相同配置会检查原任务，不重复生成或部署。任务完成后继续调用生产入口，可以推进下一个允许的阶段；没有新增定时任务，已有调度需显式传入全流程配置。

`queued/running` 表示等待任务；`succeeded` 只表示子进程成功，仍需重查产物。`failed/uncertain` 或失去执行所有者时停止自动重试，保留证据供核实。配置改变也不能绕过未结束或结果未知的旧任务。核实后需要明确修复/恢复方案；本次没有提供清除未知收据的 Agent 工具。

全流程开关会绕过旧的“PDF 已完成即结束”快捷返回。单独的 `--resume-failed-generation` 仍用于 PDF 恢复，不能与全流程开关组合后将 PDF 成功误报为页面完成。

## 验证边界

使用模拟 Agents API 会话、真实短进程以及合成发行包验证：工具权限、错误完成声明、去重、超时、进程死亡、配置/来源改变、听审/发布授权、HTTP 证据和 registry 状态。

这些测试不调用付费模型、不部署 Firebase、不证明线上页面或设备已验收。实际启用需选择真实周次配置，先做 shadow 检查，再沿已授权流程执行。
