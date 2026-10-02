# 第 1 条实验：合并后 dev 的本机实测与跨机预检

## 结论

2026-10-02 08:10 PDT 开始正式本机运行。实验**未通过端到端验收**：真实 Prefect 已执行 Source、strict text 和两单元 mock 提交边界，但两个提交确认都是 `outcome_unknown`，没有 job 记录或 WAV，最终业务状态 `incomplete`。正常场景失败后停止后续场景，没有重派未知任务，没有扩大规模或绕过拒绝。

MacBook→Mac mini 使用同一局域网普通 SSH；通过 mini 的现有 Hub 读取了 Spark `job.v1` 能力表。这是跨机只读请求成功，不是模拟 TTS 调度成功。能力表没有模拟 TTS task，`tts_experiment.available=false`，`cpu_smoke.available=true`；未提交任意远端任务，未把 CPU smoke 当作音频任务。完整 DAG 的 mock client 仍固定启动本机子进程。

## 环境与固定版本

| 项目 | 实际值 |
|---|---|
| 仓库 | JonathanJing/sermon-video-zh-subtitles |
| PR221 | MERGED，2026-10-02T15:09:30Z |
| 正式测量 dev SHA | `8c64502404f9ae7110ee49aa990bcaeb2f8cd24d` |
| PR217 / PR218 | 已进入该 SHA 的祖先链 |
| 独立 worktree | `/Users/jonathan_jing/.codex/worktrees/mock-dag-experiment-one/sermon-video-zh-subtitles` |
| 工作分支 | `codex/mock-dag-merged-dev-acceptance` |
| 运行时 | macOS 27.0 / arm64，Python 3.12.8（python.org framework），Prefect 3.8.7，jsonschema 4.26.0 |
| 音频工具 | ffmpeg/ffprobe 9.0.1 已安装；本轮未生成可供解码的 TTS WAV |
| 代码身份 | 运行凭证 `trackedWorkingTreeDirty=false`，gitCommit 为上述完整 SHA |
| Mac mini 当前服务 | loopback Hub 来自 `stage1-10392408e046` 部署目录；未部署或修改 |

原 MacBook 工作区保持原分支和文件。Mac mini 的既有 sermon checkout 为 `8e625839f50f7d0a459681d0b1965fa64d8c4407`，存在四个源/测试文件未提交修改，未动该目录。没有修改真实模型、声音配置、生产权限或其他 batch 任务。

## 固定输入与范围

沿用[完整 Fresh DAG 合同](20261002-fresh-full-dag.zh.md)及 `ActualFreshFullPrefectTests` 的现有合成输入。仅 `zh-Hans.fresh-g001`、`zh-Hans.fresh-g002` 两个目标语单元，其分组分别含3/1个 source units。合成 ASR/Source review/text 的6次调用全部由离线 fixture 返回，不是付费请求；MFA 为 prior-alignment cache，不是新对齐。Waveform 合同为16kHz、mono、PCM16，但本次未产出。

- outer plan SHA：`98800bbb75bbb74b4f43b9d79942e8e7b4d6cbf9f2112503226a93107e1f7259`
- canonical run ID：`20063c70f8a21611ba7c47232be7cdc7`
- invocation：`d58d4e9a749040eba693f9c91beed2ac`
- `productionEligible=false`，`publicationAuthorized=false`，人工/听辨未验收。

## 实际命令

在主仓库只读取/刷新远端引用；测量在独立 worktree 执行：

```sh
gh pr view 221 --json state,mergedAt,mergeCommit,url
git fetch origin refs/heads/dev:refs/remotes/origin/dev
git switch -c codex/mock-dag-merged-dev-acceptance 8c64502404f9ae7110ee49aa990bcaeb2f8cd24d
.venv/bin/python -m pip check
SERMON_TEST_PREFECT=1 \
SERMON_FRESH_FULL_TEST_EVIDENCE_DIR="$PWD/artifacts/experiment1-8c645024/evidence" \
.venv/bin/python -m unittest \
  tests.test_sermon_fresh_full_dag.ActualFreshFullPrefectTests.test_actual_full_graph_then_clean_process_receipt_only_repeat -v
.venv/bin/python artifacts/experiment1-8c645024/audit.py
```

外层 Python `subprocess.run` 将测试输出写入 `happy.log`，用 `time.monotonic()` 测 wall time，非零立即停止矩阵。余下两个测试方法没有执行。远端只读命令是通过已验证的 mini LAN SSH 执行：

```sh
curl --fail --silent --show-error --connect-timeout 3 --max-time 15 \
  http://127.0.0.1:3456/spark/jobs/capabilities
```

SSH 使用 BatchMode=yes、ConnectTimeout=5、StrictHostKeyChecking=yes 和原 HostKeyAlias；没有更换主机密钥、修改服务/网络或使用直连 Spark 替代调度。

## 场景结果与耗时

| 场景 | 本次结果 | 证据 |
|---|---|---|
| 正常完成 | **FAIL** | 08:10:24.553 PDT 启动；wall 60.804秒，unittest 59.590秒，退出1；业务 incomplete |
| 原样重复，不重复派发 | **NOT_RUN** | 正常场景首轮断言失败，未到第二 invocation |
| 单节点失败后的选择性重试 | **NOT_RUN** | 避免在同一公共启动阻塞下新增无效实验；未重派原unknown |
| 普通观察超时后的核对与恢复 | **NOT_RUN** | 原启动确认unknown不是预设的观察超时场景，不能替代此验收 |
| mini→Spark 模拟 TTS 调度 | **BLOCKED / 未提交** | 已部署能力表无匹配task，DAG无跨机mock adapter |

## 失败定位与日志审计

两份 intent 已保存，job目录没有状态文件，没有 worker completion、没有 fixture.wav。`newMockDispatches=0`只统计已确认派发；本轮实际进行了2次launcher提交尝试并记录2个unknown确认，不能解读为完全未尝试启动。Source、locale.freeze、strict text、两个 mock.input 完成；两个 mock.observe 为 outcome_unknown；verify/gate/join/final 全部阻断。

无任务、无派发的隔离解释器探针复现：传入 worker 的同形环境后，macOS Python 自动加入 `__CF_USER_TEXT_ENCODING`；`require_environment()` 在严格 ENV_KEYS 检查处抛出 `mock_tts_environment_not_scrubbed`。探针只导入并调用环境校验，不调用 submit/execute、不创建 job。这个复现与原失败位置相符；**原 launcher stderr 未被保存，不能声称从原日志直接读到了该异常**。

提交器捕获非零返回或超时后仅写 outcome_unknown，丢弃 returncode/stderr；因此本次没有通过修改环境白名单、换解释器、patch源码或重建旧请求规避它。原未知意图保持原样。

只读 `audit.py` 使用现有日志/完成凭证校验器核验保存副本：

- 206条canonical事件，replay integrity consistent，无损坏行；6条direct synthetic receipts，L1=2 / L2=4，与summary/weekly消费者计数一致。
- 19个真实SDK task及完整父依赖/开始结束时间；SDK任务全部Completed，但业务状态是incomplete。业务只形成10条有效observed edges，不能声称19条全部验收。
- 5个不同V1 Source completion及13个不同V2 synthetic control completion通过原校验器，均绑定已有日志终态；没有TTS成功完成凭证。
- 两个intent、零job状态文件、零TTS WAV；解码、产物SHA与完成凭证一致性验收**未执行，不能通过**。
- 保存副本205个文件在审计前后SHA完全一致。摘要及逐文件hash另存，没有改原证据。
- 日志检查器的 `logInspectionStatus=no_detected_error` 与业务unknown并存；它不是业务成功标志，列为诊断呈现缺口。
- timingCoverage仍为partial；critical path、ETA和资源排队未测得。control leaf计时不等于完整节点耗时。

## 日志与产物位置

以下相对上述独立 worktree，均在Git忽略目录内：

| 路径 | 内容 |
|---|---|
| `artifacts/experiment1-8c645024/environment.json` | 测量环境/SHA |
| `artifacts/experiment1-8c645024/happy.log`、`happy-timing.json` | 完整测试输出与耗时/退出状态 |
| `artifacts/experiment1-8c645024/remote-capabilities.json`、`remote-capabilities-summary.json` | 经mini读取的Spark能力表与时间 |
| `artifacts/experiment1-8c645024/environment-repro.json` | 无任务环境校验复现 |
| `artifacts/experiment1-8c645024/audit.py`、`audit-result.json` | 只读审计程序/结果 |
| `artifacts/experiment1-8c645024/saved-evidence-sha256.json` | 205个保存文件SHA清单 |
| `artifacts/experiment1-8c645024/evidence/happy/<planSHA>/` | 原SDK结果、plan/输入引用、Source/text及mock控制副本 |

最后一项内，canonical日志在 `fresh-full-dag/<planSHA>/accounting/events.jsonl`，可读日志为同目录 `operations.log`；SDK记录位于 `engine/<invocation>/`，意图/请求在 `mock-control/`。保存函数仅复制fixture的run目录，兄弟目录中的原始source media等引用没有全部打包；原临时树随测试清理。保存副本可做上述审计，**不是完整可直接恢复执行的输入归档**，不能从副本重派。

## Backlog 与下一步

沿现有 `017 / DEV-SPD-006 / 018` 跟踪，详见[统一backlog](../backlog.zh.md)：

1. macOS framework Python注入环境键与worker白名单不兼容：需要有审查和测试的最小兼容修复，不能在本次验收临时放宽。修复进入dev后再固定新SHA；原失败证据保留。
2. launcher失败诊断：保留脱敏退出类别/退出码/允许列表错误码，并继续对真实未知结果禁止重派。
3. logs inspector需要区分“账本无损坏”和“业务存在unknown/blocked”；不能以no_detected_error误导运行完成。
4. evidence保存应覆盖恢复所需冻结输入或明确声明缺失媒体/外部引用，不能把当前副本标为可执行恢复包。
5. 真正跨机模拟调度需版本化Hub任务allowlist、Spark无模型mock worker、DAG adapter及有界artifact byte回传/双端完成凭证。当前未实现/未部署。该路径需要新增任务权限与服务代码部署，可能涉及服务重启；须准备精确变更、回滚及影响后按用户要求确认。不得扩张cpu_smoke或开启真实TTS实验权限代替。

本轮没有生产发布、PR合并、真实模型/GPU调用或扩大两单元上限。结论是“合并后SHA上的失败实测与部分证据校验完成”，不是第1条实验已验收。
