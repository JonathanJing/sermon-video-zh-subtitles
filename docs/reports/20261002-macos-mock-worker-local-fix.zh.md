# 第 1 条实验：macOS mock worker 修复与本机候选验证

本报告是修复候选分支的本机验证，不能替代修复合并后固定 dev SHA 的正式验收。原 `8c64502404f9ae7110ee49aa990bcaeb2f8cd24d` 失败记录保留在[原实验报告](20261002-experiment1-merged-dev-result.zh.md)。原 unknown 意图没有重派；新验证使用独立合成输入与运行身份。

## 环境与版本

- 修复候选 SHA：`ab98774b4674d44a976d0e3999120e4ee8d2062a`，分支 `codex/mock-worker-macos-diagnostics`；SDK运行时工作树干净，每个子进程检查精确代码身份。
- 基线：PR217、PR218、PR221 已合并的 dev `8c64502404f9ae7110ee49aa990bcaeb2f8cd24d`；本轮没有自动合并 PR。
- 独立 worktree：`/Users/jonathan_jing/.codex/worktrees/mock-dag-experiment-one/sermon-video-zh-subtitles`。原工作区保持 `sync/main-to-dev-2026-10-02` 且干净。
- macOS 27.0 / arm64，python.org framework Python 3.12.8，Prefect 3.8.7，jsonschema 4.26.0，ffmpeg/ffprobe 9.0.1。

## 修复范围

- 在 macOS worker 内允许解释器自动加入的 `__CF_USER_TEXT_ENCODING`，只接受当前 UID 加两个有界十六进制编码值。父进程仍不继承该字段，其他未知环境键继续拒绝。
- 启动失败记入 ERROR 事件，保存固定白名单原因及退出码；不保存原始 stderr、路径、环境或异常正文。未知结果仍不可重派，诊断不能充当“未启动”的证据。
- 日志只读投影将 failed / cancelled / outcome_unknown / blocked 识别为需要处理；不修改历史账本。
- fixture 固定的7份外部输入按字节归档并记录 SHA/大小，拒绝符号链接、非固定引用及超限文件。归档带 `auditOnly=true` / `dispatchAuthorized=false` 标记，并阻止保存副本走 clean_child 派发入口；原引用不改写，不能称为可恢复执行包。

## 验证边界

两个目标语单元，真实本机 mock 子进程与真实 Prefect SDK，离线 fixture 的6次合成 Source/text 调用。真实模型、付费API、GPU和新MFA调用均为0；源对齐仍为缓存重放。模拟音频不能进入生产发布，人工/听辨/设备/场地验收未执行。跨机路径按本次范围推迟，没有修改 Hub、Spark、网络或生产配置。

## 证据位置

所有完整日志和媒体位于独立 worktree 的 `artifacts/mock-worker-local-fix/`，该目录被 Git 忽略。`evidence/{happy,failure,timeout}/<planSHA>/` 保存 SDK 结果、统一账本、engine、mock-control、冻结输入归档；`*-timing.json` 保存外层 wall time；`audit-result.json` 和 `saved-evidence-sha256.json` 为只读复核结果与全部文件 SHA。原输入引用保留原临时路径，审计只读取保存字节。

完整节点计时覆盖仍为 partial；本轮不提供完整 DAG critical path、吞吐量或跨机性能结论。历史 failed/unknown 不会因后续恢复从日志抹除。

## 测试与真实 SDK 结果

定向21项测试通过，27.011秒；集成37项测试通过，682.908秒。后者包含日志、归档和完整DAG组件测试。真实SDK三场景分别运行两个独立子进程，共6次invocation、114个SDK tasks；每次19个节点，父依赖和时间戳均核验。SDK任务Completed与业务状态分开：故障/超时首轮业务必须incomplete。

| 场景 | 首轮 → 第二轮 | 新模拟派发 | wall time | 结果 |
|---|---|---|---|---|
| 正常完成与原样重复 | `synthetic_complete` → `synthetic_complete` | 2 → 0 | 252.074秒 | PASS，退出0 |
| 单节点失败与显式重试 | `incomplete` → `synthetic_complete` | 2 → 1 | 233.229秒 | PASS，退出0 |
| 普通超时与原任务对账 | `incomplete` → `synthetic_complete` | 2 → 0 | 202.027秒 | PASS，退出0 |

每个场景合成Provider调用为6→0，L1=2、L2=4、L3/L4=0；真实Provider/模型调用为0，费用和tokens没有被编造成真实TTS用量。正常重复保持原产物；失败恢复只为失败单元新增attempt 2，成功邻居jobId/字节不变；超时恢复沿用原jobId且新增派发为0。单独组件测试还验证普通超时的显式重试被拒绝。

## 保存证据的独立只读审计

`audit.py`使用现有canonical/typed-completion校验器重新读取保存文件，而非只接受测试退出码：

- 7份WAV均为16kHz、mono、PCM16，每份4,844字节，逐份完成请求/receipt绑定、SHA256/字节长度、精确fixture字节、ffprobe及ffmpeg完整解码校验。
- 6份成功产物的worker completion均与job/revision/stage/父依赖及artifact SHA绑定；另外1份为`fail_after_render`的失败样本，保留WAV但没有成功completion，未计入成功产物。
- 每场景7份固定输入归档，共21份，SHA/大小均匹配；归档不可直接派发。
- 全部1001个证据文件在审计前后SHA不变；事件无损坏、replay integrity均为consistent。

| 场景 | canonical事件 | 验证的独立V1 / V2 handles | 首轮 → 第二轮有效edges |
|---|---|---|---|
| happy | 454 | 5 / 52 | 19 → 19 |
| failure | 468 | 5 / 49 | 13 → 19 |
| timeout | 424 | 5 / 44 | 10 → 19 |

各场景冻结身份：

- happy：plan `c5fef00b8535e9e5e9fd504b1faa88481be4fac1e87405a1ebe390e120b1bf0e`；canonical run `de50ea042301d9c2ebc207d939911b05`。
- failure：plan `a9ec4fbb377f111feef5f383938a3d83899d5704575ca4c188317cb38e1a82f1`；canonical run `6f84db3e2e287a31aba1dff04897e0eb`。
- timeout：plan `1cc83f682326af74e46980c30337e17f63fe4461db2d2fdd499126af27446a6c`；canonical run `2c2695f7b9cfb3b290fae37ed861513f`。

旧失败账本只读复核现在得到`needs_attention`，4条unknown被提升为诊断ERROR；账本SHA仍为`93e103dc62b07109ba7118af14d926dca35a870d1045b613d78fc8b5a144f5b2`。新故障/超时场景中的历史错误也不会因恢复成功被抹除，日志告警与最终业务状态应分开读取。

新保存账本的只读日志检查：happy为`no_detected_error`（0错误）；failure和timeout均为`needs_attention`（各2条历史错误）。三者账本均readable、无unfinished；完整结果见`artifacts/mock-worker-local-fix/log-inspection.json`。

## 实际命令

在上述worktree执行：

```sh
.venv/bin/python -m unittest tests.test_sermon_mock_tts_launch tests.test_sermon_mock_tts_worker tests.test_sermon_mock_tts_control -q
.venv/bin/python -m unittest tests.test_fresh_full_evidence_archive tests.test_sermon_logs tests.test_sermon_log_profile tests.test_sermon_fresh_full_dag.FreshFullDAGComponents -q
.venv/bin/python artifacts/mock-worker-local-fix/run_sdk.py
.venv/bin/python artifacts/mock-worker-local-fix/audit.py
```

`run_sdk.py`在干净代码身份上依次执行以下现有入口，逐场景保存完整log、UTC开始时间、monotonic wall time和退出码；任一失败立即停止矩阵：

```sh
export SERMON_TEST_PREFECT=1
export SERMON_FRESH_FULL_TEST_EVIDENCE_DIR="$PWD/artifacts/mock-worker-local-fix/evidence"
.venv/bin/python -m unittest tests.test_sermon_fresh_full_dag.ActualFreshFullPrefectTests.test_actual_full_graph_then_clean_process_receipt_only_repeat -v
.venv/bin/python -m unittest tests.test_sermon_fresh_full_dag.ActualFreshFullPrefectTests.test_actual_confirmed_failure_explicit_retry_keeps_successful_neighbor -v
.venv/bin/python -m unittest tests.test_sermon_fresh_full_dag.ActualFreshFullPrefectTests.test_actual_ordinary_timeout_then_original_receipt_reconciliation -v
```

审计逐WAV调用`ffprobe -v error -show_streams -show_format -of json <wav>`和`ffmpeg -nostdin -v error -xerror -i <wav> -f null -`。完整命令及每份结果位于`audit-result.json`。定向/集成日志另在`artifacts/mock-worker-fix-targeted.log`、`artifacts/mock-worker-fix-integration.log`。

## 未覆盖与后续

本机修复候选已通过所列验证；正式第1条实验仍等待修复合并后的dev精确SHA复测。跨机模拟任务、Hub/Spark adapter及artifact byte回传按用户本轮范围推迟，未部署、未运行，不声称SSH调度验收通过。39/128-unit规模、controller crash-window、断网/服务重启、真实模型/生产音频均不在本次证据内。继续沿[统一backlog](../backlog.zh.md)的`017 / DEV-SPD-006 / 018`跟踪，不关闭无关项。

## 复盘改进：预检、进度与状态诊断

复盘项沿`017 / DEV-SPD-006 / 018`写入backlog。增加仓库内可复用入口，替代仅保存在artifacts中的临时driver：

```sh
.venv/bin/python -m tests.run_mock_dag_experiment \
  --output-dir artifacts/mock-retro-validation
```

要求干净提交，输出目录必须不存在；仓库内输出必须被Git忽略。默认依次执行原有三个两单元SDK场景，遇到失败停止，保留完整场景日志、`summary.json`、`*-timing.json`、`progress.jsonl`与原有evidence。可用一次或多次`--scenario happy|failure|timeout`选择场景，但不允许重复同一场景。它不恢复旧任务，也不接纳现有证据目录作为执行输入。

每个场景在创建fixture前，以真实`sys.executable -I`、原worker环境清理和临时synthetic engineering profile运行只调用环境校验的预检。预检不提交job、不调用provider；失败立即停止。随后记录preflight、两次invocation和场景验证的开始/结束及wall time；运行中每30秒显示当前阶段和耗时。结构化进度是诊断记录，不能作为完成凭证或critical path。终端仅转发固定进度字段，原始子进程输出存入独立log。

保存的`summary-<invocation>.json`新增`statusDiagnostics`，分别展示SDK任务状态、原业务结果、历史错误和显式对账。历史错误来自整个当前保存账本，可能包含晚于该invocation的记录。只有完整一致账本中相同run/attempt/job/revision的唯一显式reconciliation才能记为`recorded`；没有证据时为`unknown`，不凭后来成功消除历史错误，也不授权重试。

性能改进本批先交付可重复的分场景/分invocation wall time。SDK、日志读取及校验的CPU耗时归因、配对性能实验、生产吞吐量和跨机/规模验收仍保留为独立待办。
