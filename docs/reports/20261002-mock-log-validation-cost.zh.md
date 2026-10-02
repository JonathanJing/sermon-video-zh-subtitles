# 验证与日志开销：两单元保存证据的独立归因

## 结论

当前小样本最值得优化的是**同一日志快照被反复做完整性回放和 schema 校验**。单纯增加缓存容量、减少终端日志或更换磁盘，没有本次测量支持。这里没有实施优化，也没有降低任何校验要求。

完整日志读取的成本大部分在校验路径；完成凭证批量校验又成倍重复该路径。另一个独立热点是逐事件生成 schema 精确类型指纹。新加的状态摘要投影成本相对较小。

这是固定保存证据的操作级测量，**不是整轮DAG的CPU占比报告**。不能把各项嵌套耗时相加，也不能据此宣称143秒凭证复用里某项占了多少。

## 范围与方法

- 环境：macOS 27.0 / arm64、Python 3.12.8、jsonschema 4.26.0；同一MacBook、本机顺序运行。
- 分析入口提交：`ccf38f5ca2d8b3ce7681b21a40f00b40a6e9235b`；输入为`8ff42bc740824640f0116cb759bf21d590a951b9`验证留下的三场景完整证据。业务代码未改，未重新派发任务或调用模型/API。
- happy/failure/timeout分别含454/468/424条事件，57/54/49个去重完成凭证；happy日志641,503字节、58份controller delivery记录。
- 每场景10项操作；每项3个独立Python进程，每进程首次调用加两次复用，共270次无profiler测量。冷态指Python缓存新建，**不指冷盘**；准备及hash核对会使OS页缓存变暖。
- 同时记录wall/CPU时间、缓存计数、结果一致性；汇总cold的3个样本和warm的6个样本，用中位数与范围，不估计p95或统计显著性。
- 仅在完成基线后，对happy的三个代表操作各额外做一次warm cProfile。其时间受探针影响，仅用于调用链与次数归因，不替代无profiler基线。
- 所有输入仅只读；不裁剪账本、不追随原临时路径、不从保存副本恢复执行。另在新建并删除的临时文件上测现有`outbox._append`，该文件是非权威IO样本，不是执行账本。
- 原1001份证据文件的集合、大小和SHA在全测量及profile前后均不变。

原始数字摘要见[measurement-summary.json](../evidence/2026-10-02-log-cost/measurement-summary.json)。

## 正常场景的无profiler结果

单位为毫秒。各行包括不同的内部调用，**不得纵向相加**；例如完整性回放包含schema验证，weekly投影包含读取和回放。

| 操作 | 首次调用中位数 | 缓存复用中位数 | 复用范围 |
|---|---:|---:|---:|
| 读取日志原始字节 | 0.139 | 0.043 | 0.042–0.048 |
| 预读字节的JSON解析 | 2.975 | 3.154 | 2.960–3.451 |
| 原有完整日志读取（含校验） | 718.701 | 99.479 | 98.640–100.954 |
| 逐事件schema校验 | 716.903 | 98.528 | 95.805–102.764 |
| 一次整账本完整性回放 | 647.610 | 24.020 | 23.646–24.133 |
| 57个完成凭证逐一验证 | 3380.842 | 2753.401 | 2749.620–2800.753 |
| 一次写入前完整性检查（只读部分） | 772.519 | 141.275 | 139.904–228.665 |
| weekly报告投影 | 809.157 | 187.611 | 183.843–188.061 |
| 日志检查器 | 781.058 | 132.642 | 129.698–136.870 |
| 新增状态诊断投影（内存事件） | 654.303 | 25.898 | 25.427–26.538 |

复用阶段校验/投影操作的CPU与wall时间接近（约98.7%–99.5%），支持当前测量主要消耗CPU的判断；并不排除真实工作负载的IO等待、锁竞争或调度等待。

| 场景 | 完成凭证批量验证 | 写入前完整性检查 | 新状态摘要 |
|---|---:|---:|---:|
| happy | 2753.401 ms | 141.275 ms | 25.898 ms |
| failure | 2650.888 ms | 145.890 ms | 26.495 ms |
| timeout | 2279.973 ms | 136.117 ms | 25.577 ms |

## 调用链说明

### 1. 完成凭证反复回放整本日志

[completion._rows](../../scripts/sermon_completion.py)对每个handle先检查全账本，再检查所属run。happy只有一个run，两个范围包含同一批454条事件，但两次检查均执行。cProfile确认：

- 57个handle → 57次`_rows` → **114次`replay_integrity`**。
- **51,756次事件字节/类型检查**，51,813次`fact_hash`，103,569次canonical序列化。
- 8条`rqc_observation`按既有策略不缓存，另有2条约13.4KB的`workflow_started`超过8KiB单事件缓存上限；10条事件被重复做**1,140次未缓存schema校验**。
- profile中`_rows`包含6.435/6.472秒；这说明该批操作的调用集中在哪里，不是无探针性能数字或全DAG占比。

热态每批有50,616次缓存命中、0次缓存miss，缓存只占444/8192条、592,732/16,777,216 payload bytes。**不是条目容量抖动**。缓存命中仍需严格类型检查、canonical bytes、fact hash和回放语义验证。

### 2. 单事件校验反复生成schema内容指纹

[log_contract._schema_snapshot](../../scripts/sermon_log_contract.py)每次用`marshal.dumps(schema, 2)`捕获精确类型内容，防止可变schema被错误复用。完整读取454条事件触发454次snapshot/指纹；一次durable precheck触发513次。

这项保护有必要，但调用粒度值得重新设计。现有`replay_integrity`已经在一次批处理内共用一个schema snapshot，因此warm单次回放约24ms，反而低于逐事件schema循环约99ms；二者调用结构不同，不能用相减推导“完整性逻辑为负耗时”。

### 3. 日志写入前校验与物理追加分开

[durable.validate_locked](../../scripts/sermon_durable_accounting.py)读取58份delivery记录及日志，再检查完整union。一次只读precheck约141ms，**不包含**写事件、写pending、directory fsync或锁竞争。

独立临时文件测量使用现有[outbox._append](../../scripts/sermon_log_outbox.py)，先填充641,503字节，每次追加1,400字节；3个试验各30次，试验中位数约0.045–0.053ms，三个试验中位数的中位数约0.047ms。全部临时文件已移除。这里只测canonical编码/seek/write/`os.fsync`调用返回；不等同于整个durable事务，也不证明断电持久性。因此本机微基准不支持把主要问题归因于这个低层追加步骤。

## 为什么凭证复用仍可能较慢

既有证据中happy首次invocation为96.916秒、第二次为142.960秒。代码显示：重复执行仍走各节点控制逻辑、Source prefix验证、mock byte验证和最终多个报告投影；它面对累计账本，并且新进程不能继承上一进程的schema缓存。

本次确认这些路径中的单次校验成本和重复回放结构，但没有采集整轮DAG的调用次数/CPU采样，且没有第一轮结束时的完整冻结账本快照。因此“全部差额都由日志导致”仍不能成立。启动成本、真实节点级调用次数、写入频率、锁等待及其他处理仍需单独绑定测量。

## 后续优先级与安全条件

1. **优先设计同一不可变快照内的批量完成凭证校验**：完整性检查与run索引在该快照内复用，每个handle仍单独检查terminal/job/revision/artifact/dependencies。全局冲突不得因scope过滤丢失；新字节/新schema必须重新验证。不能用mtime、高水位或持久缓存跳过实际字节检查。
2. **减少单批次内schema指纹的重复构建**：明确捕获的schema边界，保留bool/int、nested mutation、版本变化和失败不缓存等保证。RQC的policy语义仍需检查；可研究schema与policy语义拆分，但本报告未实施或证明该优化。
3. **复用最终只读投影的同一已验证快照**：避免`accounting_projection`、`summarize`、`layer_evidence`和`inspect_logs`各自重复读/验；先证明输出、冲突检测与hash绑定等价，再做配对性能验收。
4. **暂不优先增加缓存容量、调高2-unit上限或放宽timeout**。当前warm无容量miss；39/128-unit、跨机与真实模型性能仍未验收。

上述为后续设计/开发任务，写回既有`017 / DEV-SPD-006`；没有在分析过程中实施性能优化或改变合同。改变验证cadence或storage trust boundary时须另行版本化设计与审查。

## 复现

在对应worktree中运行，输出目录必须为新路径：

```sh
.venv/bin/python -B -m tests.profile_mock_dag_logs \
  --evidence-root artifacts/mock-retro-validation/evidence \
  --output-dir artifacts/mock-log-cost-analysis

# 指定一个现有保存的完整plan目录；每次profile另用新输出路径。
.venv/bin/python -B -m tests.profile_mock_dag_logs --child \
  --saved artifacts/mock-retro-validation/evidence/happy/<planSHA> \
  --operation completion_batch \
  --profile-output artifacts/mock-log-cost-analysis/completion.pstats

.venv/bin/python -B -m tests.profile_mock_log_append \
  --output artifacts/mock-log-cost-analysis/append-probe.json
```

原始270条测量、各进程cache delta、3份cProfile结果、临时追加样本和完整输入hash清单位于`artifacts/mock-log-cost-analysis/`；主输出为`artifacts/mock-log-cost-analysis.log`。所有原始媒体和profile留在Git忽略目录。只读precheck使用现有文件的共享锁，不调用会创建文件的outbox上下文；未提交任何任务、未启动GPU或调用付费API。

独立复核确认聚合数值和profile摘要与原始结果一致。复核后仅加强分析工具的输出保护：拒绝覆盖已有profile文件、拒绝写入整个evidence树（包括兄弟场景），并在独立profile前后核对输入文件hash。4项边界测试及真实pstats写入/拒覆盖smoke通过；测量动作未改，未把输出保护测试加入上述270次基线。摘要分别保留测量时和发布时的工具源码SHA。
