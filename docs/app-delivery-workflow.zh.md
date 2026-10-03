# 已批准 App 产物的本地交付包

这个显式启用的 producer 消费已有的来源包、各 locale 的翻译／音频／大纲／默想，以及 iOS Beta、Firebase Dev 的能力证明和独立人工批准。它实际复制已核验的依赖，生成可独立读取的本地包，并接入 Supervisor 的 `app_delivery_readiness` completion scope。它不生成四项内容、不代写人审、不执行正式发布或通知。输入合同及准入规则见 [App 开发说明](pr229-local-development.zh.md#app-产物与-pdf) 和 [四层合同](multilingual-production-interfaces.zh.md)。

默认生产入口仍走原路径。只有传入 `--app-delivery-config` 才接入这个 adapter；不能同时配置旧 `release_workflow_config`，也不能混用旧 PDF 的审批、修复或强制重跑参数。新 scope 的完成表示 `prepared_not_published`，并不表示 Layer 4 已发布、设备已验收或现场可用。现有旧 `dual_pdf` completion latch 不会把新包标为旧 PDF 完成；新入口也不会因旧 PDF latch 跳过 App 包检查。

## 配置与执行

把配置、输入和输出放在忽略的运行目录，例如 `artifacts/app-delivery/2026-10-04/`。输入计划及其引用文件必须满足检查器的路径和 schema 门禁；输入目录、任务目录、交付包目录彼此分开。配置可命名 `workflow.json`：

```json
{
  "schemaVersion": "sermon-app-delivery-workflow-config-v1",
  "sunday": "2026-10-04",
  "plan": "inputs/plan.json",
  "jobRoot": "jobs",
  "outputDirectory": "bundles"
}
```

先查看当前输入和真实 durable job 状态：

```sh
python -m scripts.sermon_app_delivery_workflow inspect \
  --config artifacts/app-delivery/2026-10-04/workflow.json
```

实际 local production 入口可以观察或执行一次固定动作。观察不会创建任务或包；执行会启动受锁保护的本地复制 worker，不调用模型、读取生产凭据或刷新来源：

```sh
python -m scripts.run_codex_local_sermon_production \
  --app-delivery-config artifacts/app-delivery/2026-10-04/workflow.json \
  --sunday 2026-10-04 --mode shadow \
  --out artifacts/app-delivery/2026-10-04/shadow.json

python -m scripts.run_codex_local_sermon_production \
  --app-delivery-config artifacts/app-delivery/2026-10-04/workflow.json \
  --sunday 2026-10-04 --mode execute \
  --out artifacts/app-delivery/2026-10-04/run.json
```

worker 是异步 durable job。用 `inspect` 观察退出后的状态，或再次运行同一入口核验完成。重启后先验证原任务和包；完整有效的包返回 `workflowComplete: true`、`completionScope: app_delivery_readiness`，不再复制。同一任务失败或结果未知时不会自动重启。缺少双端人工批准时只能等待批准，不能用本地复制替代实际 App 查看。

首次准入前，adapter 在配置旁的 `.app-delivery-routes/` 持久化 Sunday、jobRoot 和 outputDirectory，并用配置路径固定的锁串行准入。此后修改这些字段会拒绝执行，避免移动根目录隐藏原任务的活 owner 或未知结果。同一路径的配置应保留原路由；不同周使用新的配置。移动配置／运行目录属于显式迁移操作，本 adapter 不提供跨路径迁移或清除未知任务的功能。

## 包和恢复

每个 job ID 对应一个包，包含 `prepare-intent.json`、`assets/frozen-app-plan.json`、仅计划及其证据实际引用的资产，以及最后写入的 `bundle-manifest.json`。所有资产按原字节复制，文件和新增目录链均同步到磁盘；完成标记只在再次核验来源、候选、批准和文件 hash 后写入。原始包和审核证据保持原字节。

独立消费已复制包：

```sh
python -m scripts.sermon_app_delivery_workflow inspect-bundle \
  --bundle artifacts/app-delivery/2026-10-04/bundles/JOB_ID
```

这个命令重新运行真实准入检查和音频解码／同步验证，原输入目录不必仍然存在。相对引用从 `assets/` 读取；原来源包中的绝对引用只允许从记录的原输入根目录映射到复制目录。它不改写来源包或审核字节，也不允许访问原输入根之外的文件。篡改复制文件会导致检查失败。

失败或未知任务的修复必须显式指定原 job ID：

```sh
python -m scripts.sermon_app_delivery_workflow recover \
  --config artifacts/app-delivery/2026-10-04/workflow.json \
  --expected-job JOB_ID
```

只允许 durable 状态为 `failed` 或 `uncertain`，并且原 job 锁可取得、已记录 worker PID 不存活、当前输入／代码／配置身份与原任务完全匹配。原始 `queued` 或 `running` 即使锁空也不能作为恢复许可；死 owner 应先通过已有 `sermon_workflow_jobs.inspect_job(job_root, job_id)` 核对及收敛状态。未知 PID 或活 PID 不会被当作可重试。

恢复检查并复用已复制的正确字节，只补缺失文件；已有文件 hash 不匹配则拒绝覆盖。成功恢复写入单独 reconciliation，绑定原 request／state hash 和最终 manifest hash，保留原失败或未知状态。它不通过重写旧状态伪造成功，也不创建新模型尝试。来源、产品、能力证明或批准变化后的旧 job 不能以新证据恢复；旧未知任务在原任务根中继续占位，需核对原结果。

## 独立状态与尚未接入的路径

`pdfAdHoc` 和 `productionRuns` 保留为当前观察字段，不进入冻结 App 包的身份。无 PDF、按需 PDF 失败或后来修复，不会重新生成 App 包；正式端观察更新也不重新生成。顶层 `publication` 始终为 `not_run`。输入中另行提供的 `production.ios_prod`／`firebase_prod` pass 或 fail 仅是已绑定收据的观察，不能使本 producer 宣称发布。

现有离线测试使用明确标为 synthetic 的产品和审核收据，实际启动本地 durable worker／并发 CLI、解码音频、复制包并从原目录不可用的状态独立消费。测试覆盖原批准失效、输入中途变更、失败恢复、活 owner、未知占位、目录持久化顺序、PDF 独立及重启去重。它们证明接线和恢复规则，不是实际人工批准或双端发布验收。

```sh
python -m unittest tests.test_sermon_app_delivery_workflow tests.test_sermon_app_delivery
```

四项产品的模型生成 adapter、双端正式 publisher／回退、真实客户端设备验收和通知发送仍未接入这个 scope。单端发布失败后的实际远程回退不能在本地 fixture 中证明；本批只验证提供的 pass／fail 观察不会触发复制或虚报发布。
