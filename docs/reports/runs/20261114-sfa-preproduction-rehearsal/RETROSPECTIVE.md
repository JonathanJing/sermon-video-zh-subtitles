# 复盘：20261114-sfa-preproduction-rehearsal

数据见同目录 INDEX.md 和 manifest.json。本轮是 2026-11-15（第 10 周）正式生产前的流程预演，不是发布运行；没有部署、没有付费翻译调用。

## 结论先行

- **类型**：预演 / dry run（`test`），不是 `four_layer_release`。
- **最终状态**：可以在今晚按同一套代码开工。本地发布链路跑到第一次部署前的 `publish-check`，三语资产、线上基线、候选快照与哈希绑定全部通过；英文对照在当天线上基线上干跑通过（每语 460 blocks）。Spark 三句 TTS 冒烟通过，队列、容器、checkpoint、拉回、合并都验证过。
- **代码已锁定**：`dev` 的 `931a9682`，附注标签 `sfa-prod-20261115` 已推到 origin。生产 checkout 是无 `.git` 的 Synology 镜像；按 612 个生产相关文件逐个比对，0 缺失、0 内容差异，树哈希 `3b5b1a038d7e62377107333298a56991c6b5fd3d2f9374612e330c3259a08fec`。清单在本机忽略目录的 `20261115-rehearsal/code-lock.json`。
- **证据边界**：没有调用 `publish`/`verify`/`stage2`/`readback`，所以没有线上新页面、没有 HTTP 回读、没有设备或现场验收；DeepSeek 付费翻译没有执行（无 `--execute` 时脚本要求调用，没有免费干跑）；Bark 推送键不在本机，`notify` 只做了 plan。

## 总时间

自动汇总（核对后保留）：

- `20261115-rehearsal-start-zh`（journal）：墙钟 1h03m39s；计算 0m00s，等待 0m00s，返工 0m00s（3 次重跑）

说明：这段墙钟跨了预演从裁切、发布链路到 GPU 冒烟的全过程，不是一次连续脚本；journal 只记了 `l1.start`、`l1.preflight.setup`、`l3.finish` 三个阶段的起止，计算时间为 0 是因为本轮大多是只读校验和短脚本。真正的参考时间是：10 单元裁切 0.4 s、三语 `assets` 12.6 s、`baseline` 75.7 s、`stage1`+`publish-check` 数秒、视频重渲 37.2 s、TTS 冒烟 1m09s（含会话与容器）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | 复用 20261108 已批准英文包 | — | 0 | — | 460 单元 | — | 0 | `20261108-sermon-source/layer1/english-source.json` |
| L1 词级对齐（MFA） | 复用 | — | 0 | — | — | — | 0 | 同上 |
| L1 英文机器评审 | 复用（人审已批准） | — | 0 | — | — | — | 0 | 同上 |
| L2 初译 | 复用 20261108 三语译文 | — | 0 | — | 460 句 ×3 | — | 0 | 三语 clone 的 `translations.jsonl` |
| L2 独立审核 | 复用 | — | 0 | — | — | — | 0 | `review.json`、`audit/` |
| 文本质检（回译） | not_run | — | 0 | — | — | — | 0 | DeepSeek 无免费干跑；本轮不执行付费调用 |
| L3 配音（TTS） | Qwen3-TTS 1.7B Base，Eric checkpoint `75d28ce6…` | batch 1 | 1 个容器、3 句 | 1m09s 含会话；容器内 3.77 + 0.71 + 0.71 s | 3 × 0.96 s，24 kHz | 4.10× 实时（不含加载） | 0（本地 GPU） | `20261115-rehearsal-start-zh/tts/tts-log.jsonl` |
| L3 回转写筛查（ASR） | 未跑（2026-10-28 起退役） | — | 0 | — | — | — | 0 | — |
| 音频质检 | not_run（人工整轨听审是唯一音频门） | — | 0 | — | — | — | 0 | — |
| L4 构建与发布 | `sfa_publish.py`，production 站点 | — | 0 次部署 | `assets` 12.6 s；`baseline` 75.7 s | 3 × 460 cues；MP3 42.9 MB/语 | — | 0 | `20261115-rehearsal/publish/` |

TTS 内存：`tts-log.jsonl` 首尾 `MemAvailable` 111.5 → 111.6 GiB，`cudaReservedBytes` 峰值 4032 MiB；容器退出后会话 `finish` 恢复 `llama-server`、`spark-api`、`spark-agent`、收集器与定时器，模型健康。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L4 预检 | `firebase` 不在 PATH，`npx --no-install` 也没有 | 本机只留了 npx 缓存，没有全局 CLI；`publish` 走 `firebase deploy` | 预检（未占 GPU、未部署） | 安装 `firebase-tools 15.29.0`，验证登录与项目可访问；发布命令未执行 | `firebase --version`、`firebase login:list`、`projects:list` 通过 | 环境修复，未改仓库 |
| L4 预检 | Synology 镜像少 3 个受版本控制文件：`firebase/dev/.gitignore`、两处 `.well-known/apple-app-site-association` | Synology 同步排除点目录 | 预检 | 从锁定提交补回；`baseline` 已从线上文件带 AASA，但规范覆盖文件现在也在 | 612 文件复检 0 缺失；`baseline` 仍含 AASA | 环境修复 |
| 开工 | `prepare_clip` 报 “clip would start before the media” | 默认 `--margin-before 1.0`，而单元 0 从 0.0 开始 | 预检（0.4 s，未占 GPU） | 传 `--margin-before 0 --margin-after 8`，与 11-08 一致 | 10 单元裁切、三语分发、setup 预检全 pass | 今晚命令模板已更新 |
| Spark 会话 | `begin` 报 `unmanaged_running_container`（h3image） | 未登记的 SGLang 容器 | 预检（未停服务） | 与用户确认后停掉 h3image 与 `h3-image-studio.service`；生产后再启 | 容器数 0 后继续 | 运营步骤 |
| Spark 会话 | `begin` 报 `unmanaged_model_or_worker_process` | `h3-image-studio.service` 的进程被识别为 model | 预检（未停服务） | 停掉前端服务 | 同上 | 运营步骤 |
| Spark 会话 | 停 `spark-api` / `llama-server` 后单元进入 `failed`（OOM-kill），`begin` 报 `effect_requires_reconciliation` | systemd 停止时进程被 OOM killer 终止，`ActiveState=failed` 不等于 `inactive` | 预检（未占 GPU） | `systemctl --user reset-failed <unit>` → `reconcile` → `resume-begin`；两轮后 `exclusive_ready` | 会话 `exclusive_ready`，118.8 GiB 可用；冒烟通过 | 今晚可能复现，步骤已写进清单 |
| L4 门禁 | 线上 11-08 页面跑 gate 失败：`catalog.defaultPageId` 指向另一页 | 之后有别的页面发布并成为目录默认页；gate 要求被测页就是默认页 | 预检（只读） | 不作为缺陷；今晚在 stage2 之后立即跑 gate，此时默认页才是本页 | 线上当前默认页 gate = pass | 今晚顺序约束 |
| 发布链路 | `stage-english-reference` 对旧的 `baseline-english` 快照失败：目录 source identity 不匹配 | 那是 11-08 发布过程中的历史快照，不是当天线上状态 | 预检（只读） | 改用当天 `baseline` 干跑，460 blocks ×3 通过 | `f908b0ee…` | 使用当天基线 |
| 通知 | `notify` 没有真正推送 | 登录钥匙串没有 `org.sermonvideo.production-progress` 条目 | 预检 | 只做 dry-run；不进门禁 | `notify --run` plan=1 | 今晚如要推送需先放键 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 把 `firebase` CLI 与登录、AASA 点目录、h3image/前端服务、`reset-failed` 处理写进开工前固定检查 | 本轮四个问题都在预检阶段发现，任何一个留到发布或 GPU 后都会白占时间 | 每期省 10–30 分钟返工 | 主代理 | 本轮已写进清单 |
| 预检 | 给 `prepare_clip` 在 unit 0 起点为 0 时给出明确的边距提示，或在锚点清单里记录推荐边距 | 默认 1.0 s 直接失败 | 少一次 0.4 s 失败与重跑 | 工具维护 | backlog |
| 流程 | 在 `sfa.py start --plan` 输出里提前检查 `h3image`/未登记容器与 `failed` 单元 | 这三类都在 `begin` 才暴露 | 缩短开工等待 | 工具维护 | backlog |
| 流程 | 为 DeepSeek 阶段提供不调用 API 的 plan 输出 | 没有 `--execute` 时直接报 “call required”，本轮无法验证窗口与预算路径 | 预演能覆盖 L2 调度 | 工具维护 | backlog |
| 质量 | 预演使用上期已批准译文与收据副本，并明确标 `REHEARSAL-FIXTURE` | 避免把机器生成的 approved 收据误当人审 | 保持标签诚实 | 主代理 | 本轮已标 |

## 实际覆盖范围

- **L1**：复用 20261108 已人工批准的英文包与锚点；没有下载、没有 ASR、没有重跑对齐。`preflight --stage full` 在三个 clone 上 pass，`sourceUnitId` 覆盖、收据哈希、决策记录都核对过。
- **L2**：复用三语已批准译文与复核记录；`build_speech` 重跑后 `translations.jsonl` 与 `speech.jsonl` 字节不变，`spokenTextWithDigits` 为空；`spoken_forms` 13 条、`consistency_check` 为 advisory warn（无本期 rules 文件）。
- **L3**：三句真实 TTS 冒烟（Eric，batch 1），拉回 3 个 wav 后与其余 7 个已存在 wav 合并成 26.9 s 音轨；`maxLag` 0.82 s。没有跑整期 460 句，没有跑落后回环的 DeepSeek 精简。
- **L4**：`validate`/`preflight`/`check-title`/`assets`/`baseline`/`stage1`/`publish-check` 全部通过；`publish`、`verify`、`stage2`、`readback` 未执行（没有部署授权，也没有线上新字节）。英文对照用当天线上基线干跑通过，每语 460 blocks。gate 在线上当前默认页 pass；11-08 页因默认页已变而失败，是预期顺序约束。

## 遗留状态

- 代码：`sfa-prod-20261115` 标签已推 origin；生产镜像与锁定提交一致。不会因为 origin/dev 后续提交自动改变；今晚开工前若要跟随新提交，必须重新锁定。
- Spark：`h3image` 容器与 `h3-image-studio.service` 仍停着（用户决定生产后再启）；`llama-server`/`spark-api`/`spark-agent` 已由会话 `finish` 恢复，`llama-server` 健康。
- 本机：`20261115-rehearsal/` 下有三语 clone、发布资产/基线/候选快照、冒烟 run 与 `code-lock.json`，都在忽略的 `artifacts/`，未进 Git。
- 通知：Bark 键不在本机，`notify` 只能 plan；今晚若要真推送，需先在登录钥匙串放键并用 `test-push` 确认。
- 未结束的 job：无；Spark 容器 0，会话 `closed`。

## 外部可见的变化

- **只有 git 标签**：`sfa-prod-20261115` → `931a9682`（annotated tag，已推送）。没有页面部署、没有 release、没有目录、没有英文对照上线、没有 TestFlight 或任何设备验收；这些均为 `not_run`。

## 今晚开工清单（第 10 周）

1. `git fetch origin dev`，确认 `origin/dev` 仍是 `931a9682`（或明确决定改用新提交并重新锁定）；生产 checkout 用锁定哈希复检。
2. 确认 Spark 上 `h3image` 容器与 `h3-image-studio.service` 已停；再 `begin --minimum-available-gib 96`。若停 `spark-api`/`llama-server` 后单元为 `failed`：`systemctl --user reset-failed <unit>` → `reconcile` → `resume-begin`，不要直接重开新会话。
3. 开工命令显式带 `--margin-before 0 --margin-after 8`；先 `--plan`，再真实裁切与 `preflight --stage setup`。
4. TTS 前跑完整 `preflight --stage full`；同步 run 先 `lag_loop --check-only` 再决定精简范围。
5. 发布前确认收据 `approved` 且哈希绑定当前 `track.wav`；`publish` 每次都要用户对话授权；stage2 后立刻跑带 `--require-guide --require-alignment` 的 gate，此时本页应已是目录默认页。
6. 生产结束后按 `~/h3image/web/deploy/spark-h3.sh` 启 h3image（需要先给足内存），再 `systemctl --user start h3-image-studio.service`。
