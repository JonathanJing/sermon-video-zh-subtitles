# 第 1 条实验：本机模拟 TTS 全链 DAG 待验收报告

## 结论与时间

2026-10-02 07:40 PDT（14:40 UTC），仅完成只读核查、独立 worktree 与依赖准备。PR221 仍 OPEN、mergeCommit=null；按本次要求停止正式实验，等待其合并后的 dev。没有正式运行耗时、DAG 事件或 WAV 产物；不能把历史/CI结果当成本机结果。

## 环境与版本

- 仓库：JonathanJing/sermon-video-zh-subtitles。
- 原工作区：`/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles`；分支 `sync/main-to-dev-2026-10-02`；开始检查 tracked/untracked diff 为空，未修改其工作文件。
- 独立目录：`/Users/jonathan_jing/.codex/worktrees/mock-dag-experiment-one/sermon-video-zh-subtitles`；报告分支 `codex/mock-dag-experiment-one`。
- 准备基线（不是正式验收 SHA）：`c47bc54c511615b79d576456c0e5c31b398d5dd4`。
- PR217 已合并：`338196b8f490782d03a2ae0bb14d3b6e348c3fa0`；PR218 已合并：`8bee25447d62504cb99a4b4b6b05b3e052042f10`。两个 SHA 均经 merge-base 验证是上述 dev 的祖先。
- PR221 当前 head：`aec52bad183e686601d5825a383a79832cd0b7fb`，未作为运行版本；检查时部分 CI 仍在进行。
- macOS 27.0 / 26A428，arm64；隔离 `.venv` Python 3.12.8，Prefect 3.8.7，jsonschema 4.26.0；ffmpeg/ffprobe 9.0.1。`pip check` 通过。
- 未加载真实模型、调用付费 API、启动 GPU、连接 Mini/Spark、修改生产设置或启动常驻服务。

## 已执行命令与准备证据

```sh
git status --short
git branch --show-current
gh pr view 217 --json number,state,mergedAt,mergeCommit,baseRefName,url
gh pr view 218 --json number,state,mergedAt,mergeCommit,baseRefName,url
gh pr view 221 --json state,mergedAt,mergeCommit,headRefOid,url,statusCheckRollup
git fetch origin dev
git config --get-all remote.origin.fetch
git fetch origin refs/heads/dev:refs/remotes/origin/dev
git merge-base --is-ancestor 338196b8f490782d03a2ae0bb14d3b6e348c3fa0 origin/dev
git merge-base --is-ancestor 8bee25447d62504cb99a4b4b6b05b3e052042f10 origin/dev
# 通过 Codex create_worktree(ref=origin/dev) 创建独立目录；随后在该目录固定基线：
git switch -c codex/mock-dag-experiment-one c47bc54c511615b79d576456c0e5c31b398d5dd4
python3.12 -m venv .venv-experiment1
.venv-experiment1/bin/python -m pip install -r requirements-prefect.txt
mv .venv-experiment1 .venv
python3.12 -m venv .venv
.venv/bin/python -m pip check
```

准备约 6 分钟（07:35–07:41 PDT，含资料核查与依赖安装；不是基准耗时）。依赖和准备记录均在独立目录：`artifacts/experiment1-preflight/pip-install.log`、`artifacts/experiment1-preflight/pr221.json`。报告不包含秘密。原 remote fetch 仅配置少量分支，`git fetch origin dev` 更新 FETCH_HEAD 却未刷新 origin/dev；已显式刷新引用，未更改 fetch 配置。

## 四个场景状态

| 场景 | 本次状态 | 待验证结果 |
|---|---|---|
| 正常全图 | NOT_RUN / 等待 PR221 | Source→text→mock input/submit/observe/verify/gate→join→final.readonly；19 个实际 SDK task；6 synthetic calls、2 mock jobs |
| 原样重复 | NOT_RUN / 等待 PR221 | 同计划独立进程，0 新 calls/jobs，原产物字节不变 |
| 单节点失败后选择性重试 | NOT_RUN / 等待 PR221 | 保留成功邻居，失败节点显式授权后仅新增 1 个 job/attempt |
| 普通超时与状态核对恢复 | NOT_RUN / 等待 PR221 | 原 unknown 留存，核对原 job/receipt，0 新 calls/jobs |

## 合并后执行与核验清单

先重新核验 PR221 merged 及 mergeCommit 在 dev 祖先链，在独立干净 worktree 固定合并后 dev **完整 SHA**，重读变更后的合同/测试。沿用[完整 DAG 合同](20261002-fresh-full-dag.zh.md)，不改测试入口绕过拒绝。

以下是待执行入口，**本次未执行**；应逐方法记录 wall time/退出状态与 stdout/stderr：

```sh
SERMON_TEST_PREFECT=1 \
SERMON_FRESH_FULL_TEST_EVIDENCE_DIR="$PWD/artifacts/experiment1-merged-dev-evidence" \
.venv/bin/python -m unittest tests.test_sermon_fresh_full_dag.ActualFreshFullPrefectTests -v
```

现有三个方法分别为 `test_actual_full_graph_then_clean_process_receipt_only_repeat`、`test_actual_confirmed_failure_explicit_retry_keeps_successful_neighbor`、`test_actual_ordinary_timeout_then_original_receipt_reconciliation`。固定 mock 单元为 `zh-Hans.fresh-g001` / `zh-Hans.fresh-g002`；不是只有两条源 anchor。无需扩样。

证据保存到 `<evidence>/<happy|failure|timeout>/<planSha256>/`。读取 sdk-result、summary、原 canonical accounting、plan/layer-map、worker completion、输入输出 hash；逐一对齐 run/node/job/attempt、状态与时间、executor、重试和依赖边。对保存的 WAV 做只读完整解码、byte count/SHA256 和 typed receipt 比对。复制件中的原绝对路径需映射，不能据复制件再次派发。Prefect 临时 DB 不保存，持久化 engine records 保留在证据中。

## Backlog 与未覆盖项

1. 阻塞：PR221 合并后运行上述四场景，才可填写正式 SHA、耗时、日志覆盖与 WAV 验收。
2. 当前日志 timing coverage 为 partial：critical path、ETA、资源队列未完整测量；control leaf 只覆盖凭证落盘/terminal binding，不是完整业务节点耗时。验收时再次检查合并后代码。
3. 实验使用单 worker 调度，两单元结果不证明并行吞吐或 39/128 单元可扩展性；PR221 性能改善未在本机测得。
4. 普通 timeout 对账不覆盖 controller crash-window / missing ACK；不得改用其他手段触发被拒绝的故障窗口。
5. Source alignment 使用 prior-alignment fixture；没有新 MFA、真实源内容质量、真实 TTS 听感、人工批准、设备或现场验收。
6. 本机模拟 transport 尚未验收；真实 Mac mini→Spark 跨机调度/SSH 路由也未验收。后者需独立真实请求及双方凭证，涉及新增权限/服务/网络时先列明影响求确认。
7. Git 远端分支引用可能陈旧；后续继续显式刷新 dev 并对照 GitHub SHA，不能仅信本地 origin/dev。

本轮没有产品发布、PR 合并或对其他实验的操作。所有未来模拟产物必须保持 synthetic、productionEligible=false；失败历史不得因恢复成功而抹除。

## 用户要求实机 mini→Spark 后的只读预检

检查时间：2026-10-02T14:41:06.116564+00:00。用户指定通过 Mac mini 实机调度 DGX Spark；保留两单元、模拟 TTS、合并后 dev 和不改网络/服务的原约束。

- 再次查询 PR221：OPEN，mergeCommit=null，head 仍为 `aec52bad183e686601d5825a383a79832cd0b7fb`；远端 dev 仍为 `c47bc54c511615b79d576456c0e5c31b398d5dd4`。
- 按仓库 spark_transport 的既有默认 bridge/HostKeyAlias 发起一次只读 SSH 探针：BatchMode=yes、ConnectTimeout=5、StrictHostKeyChecking=yes；远端命令仅为 `uname -s` 和带 10 秒超时的 loopback Hub `/health` GET。未输出凭据，本文省略私人地址。
- SSH exit=255，TCP 22 连接超时（`Operation timed out`），约5秒；未进入远端 shell，Hub health 未执行。没有任务提交、jobId、跨机收据或 WAV；不能声称 mini→Spark 已请求或已验收。
- 未尝试直连 Spark 替代路由，未开启 SSH/Tailscale、修改 ACL/端口/凭据、安装常驻服务或干扰 batch。
- Backlog：先恢复/确认既有获准 Mac mini 连接路径；随后只读核验已部署任务 allowlist 与模拟产物字节回传合同。PR221 合并和连接恢复后仍需正式全链验收。最新仓库文档的接口部署状态不等于本次实时核验。

## 连接恢复实测

2026-10-02T14:43:51.269291+00:00，按用户“先恢复连接”授权执行。

- 根因：本机和 Mac mini 的 Tailscale 均为 Stopped。本机原 tailnet 地址走默认 LAN 网关。
- 本机执行已有 Tailscale.app 的 `up --timeout=20s`，状态恢复 Running、selfOnline=true。
- mini 经现有 mDNS/LAN SSH 连接，保持 BatchMode 与 StrictHostKeyChecking=yes，使用原 HostKeyAlias 验证同一主机；没有接纳新主机密钥。
- mini 普通 `up` 因残留 `exit-node-allow-lan-access` 非默认设置被 CLI 拒绝；显式保留该参数又因没有 exit-node 被拒绝。以 `tailscale set --exit-node-allow-lan-access=false` 清除不一致选项后，`up --timeout=20s` 成功。未使用 reset、未改 ACL/认证/端口、未安装服务。
- 重新经原 Tailscale 地址 SSH 到 mini：退出0，系统 Darwin；mini 本地 `http://127.0.0.1:3456/health` 返回 ok=true、local-api-hub 0.2.0；同一远端命令通过 mini 再 SSH 到 Spark 执行只读 `uname -s`，返回 Linux，退出0。
- 此次证实 MacBook→mini→Spark 的实际 SSH 可达性；不等于调度器提交、DAG、模拟 WAV 或统一日志端到端验收。未调用模型/启动GPU/提交实验作业/重启生产进程。
- PR221 再核仍 OPEN、mergeCommit=null；正式模拟 DAG 实验继续等待原定合并后 dev 条件。
