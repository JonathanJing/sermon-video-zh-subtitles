# 周六统一生产入口

`scripts/run_saturday_harness.py` 负责按顺序运行已有 PDF Supervisor 和配音桥接器，并把 PDF、音频候选、人工审核、同步、发布分别报告。它不重新实现审批、质量检查或完成门槛。

需要跨进程重启保留状态及等待审批证据时，使用 [Temporal 包装入口](sermon-temporal.zh.md)；它调用本页既有入口。固定输出质量比较见 [Promptfoo 回归](saturday-quality-harness.zh.md)，执行账本观察见 [Jaeger/OTLP 集成](sermon-trace-export.zh.md)。

默认 `inspect`，`shadow` 与其相同：只读显式指定的本地报告，不调用模型、不启动任何子进程、不创建目录或写文件。读到的 `complete` 只是保存的 PDF 报告状态，标记 `saved_snapshot_unverified`，不表示当前生产健康。未提供 `--bridge-report` 时，音频显示 `not_observed`，不会扫描“最新目录”或猜测来源。

## 检查

日期、输入 state、工作目录、Supervisor 报告和桥接配置均须显式传入。下面是命令模板；替换已核实的日期和配置路径，配置的 `weeks` 必须包含该日期。secret 参数是资源引用，不填写密钥值。

```bash
.venv/bin/python scripts/run_saturday_harness.py \
  --mode inspect \
  --sunday YYYY-MM-DD \
  --state-file gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json \
  --work-root artifacts/post-live-runs \
  --supervisor-report artifacts/sermon-production-supervisor/YYYY-MM-DD/latest.json \
  --bridge-config artifacts/sermon-dubbing/saturday-bridge.json \
  --gcs-bucket sermon-zh-artifacts-ai-for-god \
  --gcs-prefix sundays \
  --api-key-secret projects/ai-for-god/secrets/openai-api-key/versions/latest \
  --youtube-api-key-secret projects/ai-for-god/secrets/youtube-data-api-key/versions/latest
```

可追加 `--bridge-report /absolute/path/bridge-latest.json` 读取已有配音报告。报告的日期及配置 SHA-256 必须匹配；相同周日的 `same_video` 与 `live_archive` 仍各自保留 sourceId 和工作目录，不能互相替代来源证据。桥接配置使用[现有格式示例](../experiments/sermon-dubbing-poc/saturday-bridge.example.json)，示例的未知讲员、标题、授权范围须按现有证据填写，不复制占位内容作为授权。

## 明确执行

把上述完整命令中的 `--mode inspect` 改为 `--mode execute` 即可执行。可追加 `--out artifacts/saturday-harness/YYYY-MM-DD/report.json` 保存本次阶段报告。`inspect/shadow` 拒绝 `--out`，保持只读。

1. 先调用[现有本地 PDF 入口](../scripts/run_codex_local_sermon_production.py)。保留来源刷新、源锁、租约、审批和 GCS 上传及远端验证；关闭 SendGrid 参数，由当前 Codex 对话汇报。仅操作员显式添加 `--skip-source-refresh` 时跳过来源刷新。下载授权可用 `--youtube-cookies` 传入现有文件。
2. 必须获得此次子进程新写的 Supervisor `finalSnapshot` 才继续；没有新证据时保留旧报告但跳过音频执行，提示检查 PDF 日志。Supervisor 自己复核确定性产物，入口不把退出码当成完成证明。
3. 调用[现有桥接器](../experiments/sermon-dubbing-poc/continue_saturday_dubbing.py) 的 `--execute`。PDF 等待并不自动阻断独立来源：桥接器重新验证两条路径，健康的同版本视频优先，未就绪时可继续已有直播归档兜底。桥接器拥有实际可执行性判断及候选锁。
4. 候选结束仍停在原有审核要求。新入口不写人工审批，不执行音频 Firebase 部署，不发送消息，不修改 automation。

人工窗口审批继续使用[原生产 Runbook](codex-local-production-runbook.zh.md)；源或时间线改变会使旧审批失效。既有 PDF 上传属于原正式生成契约，不是新增音频发布授权。`--model` 只选择 Supervisor 模型，实际翻译、阅读审核模型仍由其已有生成契约管理。

两个子阶段使用共享 `bounded_process` 执行器设置进程组及有限 deadline。默认 PDF 为 6 小时，桥接为 7 小时，可用 `--pdf-timeout`、`--bridge-timeout` 指定正有限秒数。超时清理本地子进程组并报告 `needs_attention`；PDF 超时不继续启动桥接。SSH 被终止不证明 Spark 模型已停止，配音 runner 的远程尝试收据仍须核对，不能因超时直接重复生成。`SIGKILL` 不能由 Python 捕获，恢复依靠已有租约、继承锁和不确定结果收据。

报告的 `workflowComplete` 始终为 `false`：这个入口只汇总阶段，不具有整条链含人工听审和公开音频发布的验收器。候选带有同步报告哈希只说明收据绑定，不代表时序检查通过；人工审核和线上音频状态需要原验收流程的独立证据。机器审核不自动成为人工审核。

## 验证范围

```bash
.venv/bin/python -m unittest tests.test_saturday_harness
```

测试使用临时 JSON 和 mock 子命令，覆盖只读模式零子进程/零写入、日期和配置错配、PDF 等待时继续桥接、旧快照阻止执行、来源隔离、超时/失败报告和不误报候选完成。这不是付费生成、Spark、GCS 或现场播放的生产验证。当前新增入口也未自动替换已有定时任务。
