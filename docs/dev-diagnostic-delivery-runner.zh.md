# Dev 诊断发布执行器

`run_dev_simulated_delivery.py` 接续已经冻结的三语模拟包，不调用 ASR、翻译、TTS 或任何模型 API。执行范围固定为 Dev Hosting；模拟审核不构成正式批准，Beta 构建、音频播放、真机与场地验收分别保留 `not_run`。Codex Luna/Sol 负责监控与异常判断，确定性步骤由执行器连续推进。

## 准备与执行

先用缓存生成新的隔离页面。省略 `--run-id` 时自动生成时间戳和随机后缀；同一输出目录不能覆盖。显式 `--page-id` 只用于有意选择页面身份，发布预检仍拒绝与已有页面重名。

```bash
.venv/bin/python scripts/build_dev_180s_simulated_inputs.py \
  --run-id <unique-run-id> --out artifacts/dev-180s-page-test-20261004/<unique-run-id>/inputs

.venv/bin/python scripts/prepare_dev_simulated_publication.py baseline \
  --out artifacts/dev-180s-page-test-20261004/<unique-run-id>/baseline \
  --cache-public <verified-cache-public> --cache-receipt <verified-baseline-receipt>

.venv/bin/python scripts/run_dev_simulated_delivery.py \
  --baseline artifacts/dev-180s-page-test-20261004/<unique-run-id>/baseline \
  --prepared artifacts/dev-180s-page-test-20261004/<unique-run-id>/inputs/work/prepared \
  --source-video <hash-bound-cached-source.mp4> \
  --out artifacts/dev-180s-page-test-20261004/<unique-run-id>/workflow
```

最后一条默认只做本地预检，打印准确目标及输入身份。加 `--execute` 才按以下顺序执行真实 Dev 发布：

1. 准备只新增资源的 snapshot，guarded publish。
2. 绑定实际发布版本重新取基线，并验证线上资产 SHA。
3. 从 verified baseline 自动生成 canonical JSON SHA 的 joined release plan。
4. 封存并叠加隔离页面，保留默认页和所有既有 sibling 页面。
5. guarded publish 最终目录，读回三语 release 与资源 SHA/bytes。

HTTP 资源读回不等于 Web 浏览器交互、原生客户端解析或音频播放验收。执行器报告只声明其实际验证范围；这些验收继续使用对应客户端工具并单独记录。

## 监控与恢复

`workflow-state.json` 记录输入/实现哈希、当前阶段、每次尝试耗时和输出收据哈希。原参数重跑会校验并复用已成功阶段；HTTP 最终读回每次恢复都重新执行。修改输入、实现或已完成输出会停止。未完成的本地产物目录不自动覆盖，须核验并准备新的输出；已发布资源及租约回执保留。

发布时看同一 snapshot 的 `hosting-publisher-progress.json`：`checking_baseline`、`deploying`、`verifying_readback`、`completed` 或 `failed`。部署期间每 5 秒更新心跳。进程锁阻止本机活跃发布期间重入或对账。

`deployment-attempt-v2.json` 保持权威：派发前仍写 `outcome_unknown` 以应对崩溃，运行状态由独立 progress 文件表示。不要仅凭该字段或心跳过期重试，也不能通过复制 snapshot 绕过租约。发布失败/超时后保留远端租约，明确核对远端版本后调用既有 `reconcile()`；恢复执行器只接受 `deployed`，绝不自动重发未知发布。显式对账后的最终回执优先于原进度文件中的历史失败状态。

## 耗时与 Codex TPS

报告分开保存全程墙钟时间、各阶段执行时间（包含 CLI/HTTP 等待和失败尝试），以及 Codex 的生成计量。宿主没有提供真实 token 与生成时间时，TPS 输出 `null`、状态 `not_instrumented`，不使用经验数字或 API token=0 来代替 Codex 用量。

如果宿主另行提供观测值，可用 `--monitor-metrics <observed.json>` 导入：

```json
{
  "schemaVersion": "sermon-codex-monitor-metrics-v1",
  "turns": [
    {
      "turnId": "unique-observed-turn-id",
      "outputTokens": 100,
      "generationSeconds": 2,
      "evidenceRef": "path-or-id-of-observed-host-telemetry"
    }
  ]
}
```

示例数字只说明格式。计算口径为 `sum(outputTokens) / sum(generationSeconds)`，不计输入 token、工具等待或整条流程耗时。导入器校验唯一 turn ID、有效计量和证据引用并记录文件 SHA；它不从宿主自动采集，也不验证外部证据真实性。独立或并行监控任务的指标须分别记录，不能拼成单模型瞬时吞吐。

## 本次修复验证

离线测试覆盖：活跃发布心跳、独立进程持锁与崩溃后的明确对账、未知发布禁止重试、HTTP 失败后复用已发布阶段、恢复时重新读回、输出篡改拒绝、独立页面 ID、raw/canonical hash 差异和合法 TPS 导入。固定三分钟缓存生成的真实三语模拟包也执行了本地构建和执行器预检。

本次代码验证没有再次发布远端页面，没有付费模型调用，也没有补做 Beta 或播放验收。
