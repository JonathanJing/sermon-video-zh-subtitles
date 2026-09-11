# 周日实时字幕：新页面与会话运行白皮书

维护日期：2026-09-11。本文依据当前工作区中的启动脚本、Gateway、浏览器操作页和会话存储实现。服务是否健康、设备是否可用须当次验证；文档更新时间不代表现场验收日期。

**目标：让操作员或 Agent 从已有项目出发，为本场周日证道打开操作页、创建独立录音会话和观看链接，并在结束后核验录音保存。** 可直接执行的入口见 [Agent 运行指令](sunday-live-agent-runbook.zh.md)。仅阅读这份白皮书不会启动服务、录音或发布。

## 1. “新页面”具体是什么

| 对象 | 创建方式 | 生命周期与边界 |
|---|---|---|
| Mac 操作页 | 启动现有应用，打开 `http://127.0.0.1:4173/` | 是同一个应用入口；打开新标签页不等于创建录音 session |
| 本场会话 | 操作页点击“开始录音与字幕”或“开始新录音” | 自动生成随机 session ID、录音目录和观看身份；不用每周修改前端源码 |
| 手机观看页 | 读取本场操作页生成的二维码/链接 | 只读字幕；LAN 与公网分别验证。不可照抄上周 token 或从健康接口模板拼接 URL |
| 停止后的本地档案 | 点击“停止并保存”，等待最后连接排空 | manifest、录音、PCM/WAV、事件和哈希共同构成保存证据 |

已有 Firebase viewer 部署可由不同 session 复用，常规周日运行无需再次部署 Hosting。首次云端配置或新部署按 [Firebase viewer 文档](../experiments/local-live-poc/FIREBASE_PUBLIC_VIEWER.zh.md) 单独执行，不混入每周启动步骤。

本白皮书的“页面”指实时字幕。预制配音、双 PDF 与同行 App 的新周次发行属于另一条路径，见[配音操作 Runbook](../experiments/sermon-dubbing-poc/SATURDAY_AUDIO_RUNBOOK.zh.md)及[配音方案](saturday-to-sunday-chinese-voice-plan.zh.md)。不要把直播归档候选当成同视频正式音轨，也不要用本流程重建或覆盖每周发行目录。

## 2. 系统与职责

![周日运行流程](diagrams/sunday-live-workflow.svg)

浏览器负责麦克风、独立 MediaRecorder、操作控件与显示；Gateway 接收 16 kHz 单声道 PCM，管理 ASR、翻译、会话存储和只读分发。当前英文 ASR 是现场字幕的来源，翻译只由不可变的英文 final 触发。新英文到来时不能搭配上一句的中文。

- 操作接口默认 `127.0.0.1:8766`，操作页默认 `127.0.0.1:4173`。模型和录音控制端点保持本机访问。
- LAN viewer 默认端口 `8780`，仅暴露随机 token 对应的观看功能；是否能访问取决于实际 Wi-Fi、防火墙和设备。
- 公网通过 Mac 出站发送字幕到已配置 Firebase viewer，不向公网开放本机控制端口。公网故障不应阻断本机显示和录音。
- 录音与 ASR/翻译独立。模型失败并不自动结束录音，但浏览器关闭、麦克风断开和存储故障仍需恢复处理。

运行默认优先使用已安装的 Qwen3-ASR/MLX 与 MiLMMT Q8；启动脚本在 Qwen 不可用时可能选择已安装的 Whisper。执行者必须核对实际 provider，不能把 fallback 报成 Qwen。`contextPolicy=none` 是基线。`v4.1 Q5 · 实验候选` 不作为本白皮书的正式默认，不能用于 LAN/Firebase 分享。

## 3. 每场输入和权限

至少识别：目标周日、执行机器/仓库、任务模式、音频输入和分享范围。日期按 `America/Los_Angeles` 解释，日界或目标场次不明确时只问缺少的日期，不覆盖机器系统时区。

任务分为三种：

1. **准备页面**：检查并启动本地服务、打开操作页；不点击开始，不声称新 session 已创建。
2. **开始本场**：用户已要求开始录音/字幕时，选择输入并点击开始，核验新 session；麦克风系统授权仍由用户处理。
3. **结束本场**：用户要求结束，或已授权的运行时间范围结束后，停止并保存、核验档案，再关闭本任务拥有的启动器。

已有授权和已批准的来源/上下文继续有效，不要求重复签字。不能用默认值替用户决定公网传播范围，也不能替用户确认本周与周六是同一篇信息。请求只写“创建页面”时执行到“准备页面”；若必须创建实际录音会话，再明确录音与分享范围。

**分享选择不是发布开关。** 操作页切换“公网/局域网”主要选择显示哪个二维码；已配置的公网发布器可能在 session 开始后自动出站发布。若要求不向公网发送，开始前必须核实公网发布器未启用；不能只切换二维码便声称没有公网分发。配置变更仅限已授权目标，保留原配置，且不输出凭据。

**本机观看不等于网络隔离。** 当前 Gateway 默认同时监听 `0.0.0.0:8780` 的 LAN viewer，没有标准的“关闭 LAN”启动开关。下文的 `local` 仅表示操作员在本机观看且不分发链接；严格要求禁止任何 LAN 暴露时，须在启动前说明现有入口不能满足，先处理已授权的隔离配置并核验，不能靠 `publicViewer.configured=false` 宣称仅本机网络可达。

## 4. 开场前：准备运行环境

从仓库根目录执行，先查看适用的 `AGENTS.md`、当前分支和差异，保留其他工作。下列命令不安装模型：

```bash
cd experiments/local-live-poc
LOCAL_LIVE_CONTEXT_POLICY=none ./scripts/sunday-live.sh --check
```

`--check` 会检查依赖、选定 ASR、Ollama 模型、会话目录写入能力与至少 10 GiB 可用空间；如配置 Firebase，还会检查凭据是否可用。它会创建并移除临时写入探针，不能称为完全无写入检查；它也不证明麦克风、实体手机或现场语义质量通过。

若唯一问题是 Ollama 未运行，可在已授权启动范围内打开已安装的 Ollama，然后重试。依赖、模型或磁盘不满足时，报告准确缺项；不要临场悄悄安装大模型、清理录音或换成未经选择的实验模型。首次安装参见 [POC README](../experiments/local-live-poc/README.md)。

启动脚本会读取本机忽略文件 `firebase/runtime.env`。不要将其内容、访问令牌或完整环境变量打印到报告。命令行环境变量也可能被该文件覆盖，最终以 preflight 和健康接口中的有效配置为准。上面显式请求 `none`；若实际策略不符，先定位配置来源，不要继续创建 session，也不要修改正在录音的实例。用户明确要求 Pack 时才按其已验证的策略替换该值。

周六 Pack 不是必需品。若用户明确要求使用 Pack，按[契约](saturday-to-sunday-context-pack-plan.zh.md)核对周次、同篇人工确认、有效期、哈希和内容审核，并让 readiness 限制能力。缺少同篇审批或已审中文时保留 `none`/允许的较低能力；不得拿周六正文代替现场识别。

## 5. 打开页面并创建本场

在单独且保持存活的终端中启动：

```bash
LOCAL_LIVE_CONTEXT_POLICY=none ./scripts/sunday-live.sh
```

启动器负责运行进程并在就绪后打开操作页；不要只运行 `npm run dev` 后便报告字幕系统已启动。已存在健康的运行实例时复用它，先查看操作页是否正在录音，不再启动第二份，也不点击另一个标签页的开始按钮。

核对两个终点：操作页可加载；`GET http://127.0.0.1:8766/api/health` 返回 `service=local-live-caption-gateway` 且 `status=ready`。HTTP 200 不代表 ready，还要检查所选 ASR、默认翻译、`defaultContextPolicy`、存储与 `publicViewer.configured`。不要将包含内部路径和网络地址的完整健康响应贴到公开文档。

获准开始后按顺序操作：

1. 在页面选定正确的麦克风/调音台输入，保留默认正式模型；系统权限弹窗交由用户操作。
2. 点击“开始录音与字幕”。确认录音进行中、本地保存开始增量写入，并记录界面返回的本场 session ID。不要从“最新目录”猜测 ID，也不要手工调用 start API 来制造空 session。
3. 用本场获准的短句确认输入电平、英文 final、对应中文与增量文件写入。静音时没有字幕不应伪装为模型通过；真实输入不可用则注明该项未验证。
4. 需要手机观看时，从本场页面取得对应路线的真实链接。LAN 用同一 Wi-Fi 实体手机验证；公网用获准的蜂窝设备验证。仅打开手机尺寸浏览器不等于实体设备验证。
5. 若先做了预检录音，停止保存该 session，标明为预检；正式开始再创建独立 session，并重新核验和分发新二维码。不得让观众继续使用预检/上一场链接。

当前前端没有目标周日标题字段。运行报告可记录目标日期与 session ID 的映射，但不能声称该日期已经写入 session metadata。不要为了每周运行临时修改 schema。

## 6. 场中观察与故障处置

| 观察 | 操作 | 仍需保留的事实 |
|---|---|---|
| ASR/翻译暂时失败 | 保持独立录音，观察健康与恢复提示 | 录音继续不等于字幕连续或翻译正确 |
| Gateway 中断、页面提供“恢复字幕与保存” | 保留原标签页，按现有恢复入口重连同一 session | 记录缺口；不要用刷新页面代替恢复 |
| 本地保存失败 | 保留页面和浏览器录音副本，停止后下载恢复文件 | 未完成 manifest 不可标记安全保存 |
| 麦克风断开 | 停止并保存当前会话，再重新选择设备开始新场次 | 原音频可能存在缺口 |
| 公网字幕失败 | 本机继续；按已授权范围使用 LAN 路线并重新检查 | 手机到达与渲染须实际验证 |
| 进程/端口冲突 | 查看端口所有者与运行身份，复用正确实例 | 不杀掉身份不明或其他任务的进程 |
| 无法确认物理手机、PA 或中文语义 | 保留未验证状态，交给现场操作员补验 | 不根据一张截图填成通过 |

不要在真实录音中主动做故障注入、模型切换、全文重播或全套测试。长场资源与延迟观察按当前界面和事件记录，历史 replay P95 不是本场保证。

## 7. 结束、保存和关闭

1. 点击“停止并保存”，等待最后一句和最新连接的 worker/storage drain；确认显示“本地保存 已完成”。若提示“可恢复/不完整”，保留原状态和副本。
2. 依据本场返回的目录检查 `manifest.json`；读取 `audioFile`、`eventFile`、`asrPcmFile`、`asrWavFile`，不要固定假设浏览器总会输出 WebM。核对 `status`、时长、计数、`audioSha256`、`pcmSha256`、`pcmWavSha256` 与实际文件。录音和 ASR WAV 还需解码核验。
3. 可用现有只读 scorer 汇总事件和完整性。以实际 session 目录替换下面变量后执行；输出留在忽略的本机产物目录：

```bash
sunday_session_dir="/absolute/path/to/the-confirmed-session"
.venv/bin/python scripts/score-soak-e2e.py "$sunday_session_dir" \
  --output "$sunday_session_dir/operator-score.json"
```

scorer 报告不是人工语义/现场验收报告；命令退出成功后仍须阅读检查结果。`completed` 也不保证字幕没有断档。 scorer 检查哈希，不运行音频解码；如果本机已安装 FFmpeg，可另行执行以下只读完整解码检查。缺少 FFmpeg 时注明解码未验证，不将哈希通过代替解码：

```bash
.venv/bin/python - "$sunday_session_dir" <<'PYCODE'
import json, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1]).resolve()
manifest = json.loads((root / "manifest.json").read_text())
for key in ("audioFile", "asrWavFile"):
    media = (root / manifest[key]).resolve()
    if not media.is_relative_to(root) or not media.is_file():
        raise SystemExit(f"Missing or invalid {key}")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(media),
                    "-f", "null", "-"], check=True)
print("recording and ASR WAV decoded successfully")
PYCODE
```

4. 确认录音已完成或恢复副本已保留，并检查所有操作页及 `health.liveProgress.activeStreamCount`/`streams`，确保没有其他活跃录音；不能仅因 stream 数为零就忽略浏览器独立录音。再核对启动进程的 checkout 路径、PID 与本任务启动记录。只有本任务拥有且获准关闭的运行实例，才执行 `./scripts/stop-sunday-live.sh` 或在其启动终端按 Ctrl-C。停止脚本使用共享 PID 文件，命令名检查不足以证明任务归属；复用的既有 runtime 默认保持运行。不要使用无差别 `killall`。
5. 手机页应显示结束或按实际有效期失效；停止录音不等于云端历史节点立即删除。不为“收尾”擅自清理会话、修改保留策略或删除云端数据。

## 8. 交接与完成定义

执行者返回：目标日期、执行机器/分支、有效模型与 Context 策略、任务状态、本场 session ID/本地目录、实际可用的观看路线、保存/哈希/解码结果、故障缺口、未验证的现场项目和下一步。观看 token 仅交付给本次获准接收者，不写 Git；不自动替用户向他人发消息。

明确区分：**页面已准备 → 新 session 已创建 → 字幕链路已验证 → 手机路线已验证 → 本场已保存**。未执行的阶段不填通过；打开网页不能代表整场完成。

## 9. 实现依据

- [启动与预检](../experiments/local-live-poc/scripts/sunday-live.sh)、[停止脚本](../experiments/local-live-poc/scripts/stop-sunday-live.sh)
- [操作页与麦克风/session 生命周期](../experiments/local-live-poc/src/App.jsx)、[Gateway 客户端](../experiments/local-live-poc/src/gatewayClient.js)
- [健康与会话 API](../experiments/local-live-poc/backend/gateway.py)、[增量存储与最终哈希](../experiments/local-live-poc/backend/session_store.py)
- [LAN viewer](../experiments/local-live-poc/backend/viewer_server.py)、[公网发布器](../experiments/local-live-poc/backend/firebase_publisher.py)
- [只读 scorer](../experiments/local-live-poc/scripts/score-soak-e2e.py)、[既有 readiness 证据与未完成现场门槛](../experiments/local-live-poc/benchmarks/SUNDAY_READINESS_20260904.zh.md)
