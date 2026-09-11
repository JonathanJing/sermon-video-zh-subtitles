# Agent 执行入口：准备周日字幕页面与创建本场会话

这是可直接交给 Agent 的执行型 Markdown，不依赖全局 skill 安装。运行细节与故障处理见[白皮书](sunday-live-operations-whitepaper.zh.md)。用户仅要求撰写/审核本文时，不执行下面的运行步骤。

## 使用示例

从项目 README 打开本文，或在新的 Agent 对话中发送：

```text
读取 docs/sunday-live-agent-runbook.zh.md，准备本周日实时字幕操作页。
复用这台 Mac 上已经安装的运行环境；先检查现有录音，打开页面后停在待机。
返回页面、有效模型、预检结果和还需要我处理的事项。
```

需要实际新 session 时，可以发送：

```text
读取 docs/sunday-live-agent-runbook.zh.md，开始已指定周日场次的实时字幕。
使用本次明确指定的音频输入和分享范围，创建新的录音 session，并核验观看链接。
沿用已有授权；未指定的麦克风或公网范围先澄清，能独立进行的预检继续完成。
```

## 执行契约

- 目标是运行现有 `experiments/local-live-poc`，不是重新开发页面、部署新网站或生成配音。
- 未指定动作时按 `prepare`：启动/复用服务并打开待机页；`start` 需要本次录音授权和明确分享范围；`finish` 必须对应已确认的 session 与结束请求。已有授权持续有效，不重复询问。
- 默认使用已选定的正式模型、`contextPolicy=none`；若用户明确指定了不同配置，按已有授权与其验收边界处理。实际启动配置与目标不符时不能静默降级。
- 公网发布器启用后可能自动发送字幕。只改变二维码路线并不能禁用发布；只有核实公网未启用，才能报告没有公网发布。当前启动器仍默认监听 LAN viewer（`0.0.0.0:8780`）；`local` 仅表示本机观看、不分发链接，不代表网络隔离。若用户要求禁止任何 LAN 暴露，先在启动前报告缺少标准关闭开关，并处理已授权隔离配置，不能直接按默认启动。
- 不自动改代码、安装大模型、执行付费生产、重新部署 Firebase、删除录音、提交 Git 或向他人发送链接。用户另行授权的必要动作可按其准确范围执行。

## A. 定位并保留当前工作

1. 确认当前项目为 `sermon-video-zh-subtitles`；从实际 checkout 定位，不硬编码个人目录。读取根 `AGENTS.md` 与 `experiments/local-live-poc/AGENTS.md`。
2. 查看当前分支、`git status --short` 和启动脚本，保留所有已有差异。当前 checkout 中的功能可能尚未全部提交，不能默认另一台机器的 fresh clone 相同。
3. 从用户上下文解析目标周日、`prepare/start/finish`、麦克风和 `local/lan/public`。准备模式缺少音频设备不妨碍预检；开始模式缺少关键输入时只问必要问题。
4. 先查看已有操作页、运行身份和本场状态。有录音正在运行时复用该页，禁止再开一个录音 session 或关闭/刷新它。

## B. 检查并打开

从仓库根目录进入 POC：

```bash
cd experiments/local-live-poc
LOCAL_LIVE_CONTEXT_POLICY=none ./scripts/sunday-live.sh --check
```

若失败，按白皮书定位缺项。预检会做临时写入探针、可能检查云端登录；不打印 `firebase/runtime.env`、访问令牌或完整环境。不要为了文档/准备请求执行首次安装或云端部署。若只缺已安装 Ollama 的运行进程，在启动授权内启动它再检查。

上述命令显式请求无 Pack 基线；若用户已明确指定其他合格策略，按其授权替换。`firebase/runtime.env` 仍可能覆盖环境，检查实际策略；不符时先解决配置来源，不改变活跃录音。

预检通过后，在持久终端/PTY 中运行以下命令并保留会话，不让工具超时杀掉本任务的启动器：

```bash
LOCAL_LIVE_CONTEXT_POLICY=none ./scripts/sunday-live.sh
```

复用已有健康实例；等待启动器完成真实就绪检查。轮询要有上限，遵从当前脚本的等待窗口，超时后读本次日志，不无限重启。

打开 `http://127.0.0.1:4173/`，同时读取 `http://127.0.0.1:8766/api/health`。仅记录 service、status、有效模型/ASR、默认 Context、存储可用性和公网是否启用等必要字段。确认 `service=local-live-caption-gateway`、`status=ready`，并在页面检查实际操作状态。

对 `prepare`：到此返回 `page_prepared`，明确“尚未开始录音、尚未创建新 session”；留下启动终端，等待用户开始本场。不能为获得二维码提前创建空会话。

## C. 创建与验证本场（仅 start）

1. 核对开始录音已在用户授权内，并确认实际公网配置符合分享范围。若已有活跃录音，优先返回该状态和页面，不另建新场次。
2. 操作浏览器 UI，选定用户指定的音频输入和正式模型。需要系统麦克风授权时让用户完成；不规避权限。
3. 点击“开始录音与字幕”或“开始新录音”。核对录音状态和本地增量写入，读取实际 session ID/目录。若 UI 不直接展示 ID，可读取该页面刚返回的 session 响应或其绑定的本地状态；不根据文件排序猜测。
4. 检查获准音频的电平、英文 final、对应中文、保存计数增长。无声音或设备无法操作则将音频链路标为未验证，不注入假字幕或把回放写成现场通过。
5. 从本场页面提取实际 viewer 链接；默认只交给当前用户。按指定路线验证实体手机；无设备访问时分别报告浏览器验证与待人工手机验收，保留录音正常运行。
6. 需要预检与正式分场时，完整结束预检并创建正式新 session；重新交付正式二维码。保存日期与 session 的映射在本机运行报告中，不假定前端存在日期输入字段。

从此保持当前 session，不主动关闭页面、停止进程或做故障注入。Agent 可以在报告启动结果后结束当前对话；明确 runtime 留在运行及其终端位置，不声称会在后台持续监控。只有用户请求继续监控/定时结束时，才安排相应的持续执行方式。

## D. 停止与交接（仅 finish）

1. 确认目标 session 后点击“停止并保存”，等待最新连接完成排空；保留任何 incomplete/gap 状态。
2. 按 manifest 中的实际文件名核验文件、SHA-256 和完整解码。使用白皮书中的 scorer 命令汇总并阅读结果；模型语义和实体手机验收仍独立。
3. 保存核验通过或恢复副本已交接后，检查其他操作页、独立浏览器录音和 `health.liveProgress.activeStreamCount`/`streams`。核对进程的 checkout 路径、PID 与本任务启动记录，确认无其他活跃场次且拥有关闭授权，才执行 `./scripts/stop-sunday-live.sh`。共享 PID 文件与命令名不能证明任务归属；复用的既有 runtime 默认保持运行。不要清理其他进程或录音。

## E. 返回格式

采用简短中文，字段只填写实际完成的事实：

```text
目标周日：日期（America/Los_Angeles）
动作：prepare / start / finish
状态：page_prepared / session_created / local_captions_verified /
      viewer_verified / session_finalized / needs_input / blocked
操作页：实际 URL
运行：执行机器、实际分支/提交、实际 ASR / 翻译 / Context
会话：session ID、实际本地目录；尚未开始则写“未创建”
观看：路线与实际链接；未启用/未验证时说明
证据：本次已执行的页面、音频、保存、哈希或设备检查
未完成：准确缺项与下一步；没有则写“本次范围已完成”
运行是否继续：是/否，保留的终端或下一步停止方式
```

报告和截图不得包含访问凭据。session token 链接只交付给获准接收者，不写入 README、Git 或公共日志。不要把阶段性 `page_prepared` 或 `session_created` 说成整场 Sunday-ready。
