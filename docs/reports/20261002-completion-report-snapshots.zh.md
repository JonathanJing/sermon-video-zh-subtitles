# 批量完成凭证校验与报告快照共用

本批沿 `017 / DEV-SPD-006`、PR #224 实现两项优化：一次操作内共享 completion 的全局/所属 run 完整性检查；最终 layer/accounting/summary/日志检查共用一次账本快照。没有更改证据 schema、生产资格、cap 2、durable 写入前校验或 unknown 不重派规则。

## 实现与边界

- `completion.validate_many` 与 `validate_synthetic_many` 分别接收 V1 和显式 synthetic V2。批次复制输入，先验证全账本，再对每个所属 run 验证一次；逐凭证保留终态、非容器、身份、artifact、依赖、job/revision 检查。跨 run 的冲突不能被过滤掉。
- Source prefix、mock 父节点/依赖边、三个 worker lifecycle 凭证使用批次接口。capture 复用本次已检查的私有行，不再重复整账本验证。原单项 API 的验证顺序保持；没有对外导出可复用的预验证授权。
- `FullFreshDAG.report_bundle()` 读取一次，内部共享事件与完整性结果。返回 layer/accounting 投影；`summarize` 的 `.summary.lock` 及 `summary.json`、`stages.csv`、`stage-attempts.csv`、`operations.log` 四份输出保留。
- 快照仅属于本次调用；下一次调用仍读取和校验实际字节。不使用 mtime、高水位或持久化 success token。操作内 schema/version 改变拒绝；报告内部事件突变也拒绝，且在摘要写入前检查。completion 不跨账本 I/O 持有 schema 锁，避免反向锁顺序。
- 逐事件 schema 指纹优化尚未实现；RQC policy 不缓存策略和超限事件检查仍保留。

## 配对测量

基线为 `7eb153b6017d65fb49eb0b2d9f402dd3ec343242` 的原 completion/accounting/logs/fresh-full-DAG 模块。候选在提交前测量，精确代码 SHA 见[测量摘要](../evidence/2026-10-02-snapshot-optimization/measurement-summary.json)。输入仍是先前保存的三场景完整 synthetic 证据，没有派发新任务。

macOS 27 arm64、Python 3.12.8、jsonschema 4.26.0。18 个独立子进程、每侧首次一次加 warm 三次，共 72 次调用；cold 指 Python 缓存新建，未清空 OS 文件缓存。测量耗时 57.532 秒。9 组完整返回值 hash 全部相等，原 1001 份证据文件及测量期间代码指纹不变。报告的旧组合实际调用原 `layer_evidence()+accounting_projection()`，新组合调用 `report_bundle()`；双方写摘要都在临时字节副本上，原证据只读。

下表为 warm 中位毫秒；V1/V2 分别批处理，不混同两种证据域。

| 场景 | V1 数量；旧→新 | V2 数量；旧→新 | 报告旧→新 |
|---|---:|---:|---:|
| happy | 5；236.784→54.322 | 52；2517.638→61.576 | 682.592→152.555 |
| failure | 5；244.144→55.956 | 49；2396.736→62.696 | 662.838→155.695 |
| timeout | 5；230.614→51.812 | 44；2052.015→57.999 | 618.746→147.766 |

报告每次实际账本读取 **5→1**。独立以固定生成时间比较旧/新 `summarize`，三场景的返回值与四份摘要文件均逐字节一致。cold 数字、范围、代码指纹和输出 hash 保留在测量摘要。

这是保存证据上的操作级收益；样本少，不是统计显著性、整轮 DAG 提速、跨机吞吐或 39/128-unit 资格证明。

## 验证

100 项定向/回归通过：completion/batch、worker/control、schema/cache 共 55 项；Source causality 10 项；报告快照 7 项及原 accounting/logs 28 项。覆盖跨 run/序号冲突、V1/V2 分离、全部绑定、失败/容器终态、schema/version 改变、输入/返回对象突变、追加后重读和损坏日志。

干净代码提交 `988102d4df5c1a523943a1c414582087635cb94f` 上，真实 Prefect 三场景均通过（6 次独立 invocation / 114 tasks），原统一入口退出 0：

| 场景 | 包含验证的总 wall time | 已验证行为 |
|---|---:|---|
| 正常执行与凭证复用 | 195.721 s | 第二轮新增 provider fixture 调用为 0、mock job 派发为 0 |
| 确认失败后选择性重试 | 188.536 s | 仅失败单元新建 attempt，成功邻居保持原 job |
| 普通等待超时后对账 | 162.249 s | 沿原 job 对账成功，没有新派发 |

见 [SDK 验证摘要](../evidence/2026-10-02-snapshot-optimization/sdk-validation.json)。这些时间包含 SDK 进程和测试验证，不是关键路径或受控整轮配对性能结果；不得用它们与旧单次运行之差宣称确定的整轮提速。真实模型/付费 API 调用为 0。

独立只读审计确认 114 个不同任务、160 个 V1/V2 凭证及 6 份成功 WAV 的完整解码与 SHA，7 个 worker jobs 的身份和恢复行为一致，1001 份证据文件未改变。末轮报告 hash 与完整账本字节一致；首轮只验证其 hash 匹配最终账本的完整行重建前缀，不声称存在独立冻结的首轮快照。failure/timeout 的历史 `needs_attention` 保留。见[独立审计](../evidence/2026-10-02-snapshot-optimization/independent-audit.json)。

后续提交只补充证据文档；代码文件与配对测量指纹一致。合并后 dev `58b46767` 的本机三场景复测见[合并回执](20261002-merged-dev-mock-dag-receipt.zh.md)。跨机、39/128-unit 规模及 controller 故障窗口仍未完成。

## 复现

```sh
TMPDIR=/private/tmp .venv/bin/python -m unittest tests.test_sermon_completion tests.test_sermon_completion_batch tests.test_sermon_mock_tts_control tests.test_sermon_mock_tts_worker tests.test_sermon_log_schema_snapshots tests.test_sermon_log_validation_cache -q
.venv/bin/python -m unittest tests.test_sermon_fresh_source_causality tests.test_report_snapshot tests.test_sermon_accounting tests.test_sermon_logs -q
.venv/bin/python -B -m tests.profile_mock_snapshot_optimization --evidence-root artifacts/mock-retro-validation/evidence --output-dir artifacts/new-snapshot-measurement --samples 1 --warm-calls 3
```

`TMPDIR=/private/tmp` 避免既有 Source fixture 在 macOS `/var` 别名下触发路径规范化不一致。输出目录必须全新；保存证据为 audit-only，不可据此恢复调度。早期 worker/control 检查曾与代码修改并发触发身份变更拒绝，不计入通过；上述 55 项在代码停止修改后重新运行，退出 0。
