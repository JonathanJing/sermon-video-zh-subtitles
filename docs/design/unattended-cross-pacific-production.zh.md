# 跨太平洋无人值守生产与远程审核

[逐句优先路线](../sentence-first-agent-production.zh.md) · [runbook](../../experiments/sentence-first-agent/AGENTS.md) · [发布门禁](../sentence-first-agent-publish-gate.zh.md) · [周更运行配置](../weekly-run-profile.zh.md) · [Firebase 环境隔离](../development-branch-and-firebase-environments.zh.md) · [本地计算策略](../local-production-compute-policy.zh.md) · [模型栈](../sentence-first-model-stack.zh.md) · [标题表](../series-sermon-titles.zh.md) · [术语表](../series-terminology.zh.md)

状态：**设计稿（2026-11-16）**。只写方案，不含代码改动，也不代表已有无人值守发布能力（[AGENTS.md](../../AGENTS.md) 明确：代码支持不是已校准运行或活跃无人值守发布者的证据）。§2 的实测是写作当天在 MacBook Pro 16 上取的。

> **2026-11-16 更正。** 初稿把当天的 SSH 超时记成「Spark 侧故障」，结论错了。当晚定位到三个本机根因：`~/.ssh/config` 把 `Host 192.168.1.152` 默认路由到一个已不在 tailnet 的跳板（`jonyopenclaw@100.73.116.52`），于是每条 `ssh` 都在 banner 交换处超时；`com.h3.spark-tunnel` 转发到 Spark 上并不存在的 8080；`com.jonathan.dock-wifi-watch` 被 launchd 标记 disabled，导致 Wi-Fi 与有线同网段双 IP。Spark 本身 5 天未重启、banner 10 ms、负载 0.14。§2 的结论仍然成立（LAN 链路会静默坏、无通知），但「Spark 坏了」不是事实。

## 1 目标

一句话：**周六晚上把录像放进 Drive，周日下午在中国用手机加一台笔记本审完并发布；中间不需要有人在美国的电脑前。**

三个必须分开的词：

| 词 | 谁做 | 在哪做 |
|---|---|---|
| 自动生产 | 机器 | 美国那台 Mac + Spark |
| 人工判断 | 人 | 公网上的审核页，两处 |
| 发布授权 | 计划预先给 | 落成文件，不再逐次对话 |

「无人」是错的提法。真正的目标是 **无电脑**：人不在电脑前，但可以在世界另一侧用手机和笔记本完成四次很短的操作。这个版本便宜得多，而且今天就够用（见 §9）。

不做（本轮明确不碰）：

- 正式四层流水线的无人值守（那条线的门与豁免成本已在 [10-11 复盘](../reports/20261011-weekly-release-resi-54475d42-retrospective.zh.md) 量化）；
- 把 TTS 搬出 Spark；
- 在云端重建整条链路（只在 §8.5 保留为降级路径的形状，不实施）。

## 2 拓扑与实测

| 角色 | 设备 | 位置 | 网络 | 职责 |
|---|---|---|---|---|
| 生产者 | MacBook Pro 16（M1 Max 64 GB，`jonathans-mbp-16`，100.114.213.70） | 美国 | 家宽 + Tailscale | 全部生产步骤、发布、持有产物 |
| GPU | DGX Spark（`192.168.1.152`） | 美国，同 LAN | 局域网 SSH | 逐句 TTS |
| 审核终端 | MacBook Pro 14（`jonathans-mbp-14`，100.91.174.45） | 中国 | 家宽 + 翻墙 | 深度审核、决定、看板 |
| 随身 | iPhone（`iphone181`） | 中国 | 蜂窝 + 翻墙 | 通知、一分钟级决定 |
| 受众 | iOS App / Web | 美国 | — | 观看已发布页面 |

2026-11-16 14:2x PT 实测：

- **Spark 不可用。** 22 端口 TCP 可连，SSH banner 交换超时；8080 拒绝连接。`com.h3.spark-tunnel` 的 launchd 状态为 `255`，`KeepAlive` 每 30 秒重试。表现为 sshd 无响应或限流，根因待查（§8.3 给出一个待验证的假设）。
- **MBP14 走中继。** Tailscale 显示 `relay "lax"`、`offline, last seen 1m ago`。三个节点都在同一 tailnet 上，但跨境走的是 DERP 中继，这就是「不保证能接触到这台电脑」的实测依据。
- **Synology Drive 不能当机器间通道。** `artifacts/` 为 254 GB，与仓库同在 `~/SynologyDrive` 下；同步规则 `max_size = 209715200`（200 MB）、`[Directory]` 段为空。结论：大于 200 MB 的视频不会同步，但 **254 GB 的小文件会同步**。

三条可以直接指导设计的结论：

1. Mac 与 Spark 之间是一条「能用但会静默坏」的 LAN 链路；**今天它就是坏的，而且没有任何通知**。无人值守的第一课不是加功能，是让这类故障在 5 分钟内出现在手机上。
2. **人的路径不能建在 Tailscale 上。** 三个节点在，但跨境中继不稳；Tailscale 只能作为「临时进去看一眼」的备用手段，不能作为审核路径的主干。
3. **MBP14 必须是独立 clone。** 不能让它加入同一个 Synology Drive 同步目录：那会搬 254 GB 产物，而且两台机器同时写 `artifacts/` 与 Git 工作树会冲突。审核素材只能走控制面，不能走文件同步。

## 3 生产线的真实形状

按 [runbook](../../experiments/sentence-first-agent/AGENTS.md) 的 §0–§11。以下「实测」取自 `artifacts/sentence-first-agent/20261108-*`（2026-11-07 那期，三语、461 句、整期同步）：

| § | 阶段 | 执行者 | 关键产物 | 现在的人工门 | 实测 |
|---|---|---|---|---|---|
| 0 | 冻结决策 | 人 + 代理 | `decisions.json`、`pages/<pageId>.json` | 六项逐个问 | 开工前 |
| 0.1 | 审听计划 | 代理 | `run.md` 表头 | — | 开工即发 |
| 0.3 | 发布意图七件套 | 代理 | `run.md` 清单 | 开工时填 | 11-07 漏 3 件 |
| 1 | Spark 独占会话 | 代理 | 会话 id | 有别人的会话要问 | 1–2 min |
| 2 | 裁音频、拆句 | `sfa.py start` | `clip.wav`、`sentences.jsonl`、`slices/` | 窗口 | 12–20 min |
| 2 | 英文来源（L1） | **代理即兴** | `anchor-manifest.json`、`english-source.json` | **英文表人工批准** | 19:47–20:02 |
| 3 | 讲员分配（双人） | `assign_speakers.py` | `speakers.json` | 确认 <0.8 的句 | 视形态 |
| 4 | 逐句翻译 + 独立审计 | 子代理 | `translations.jsonl`、`review.json` | — | 12 min |
| 5 | 口播规格 + 精简 | `build_speech`、`spoken_forms` | `speech.jsonl` | **认可精简稿** | 反复 |
| 6 | Spark 排队配音 | `spark_queue.py` | `tts/` | 改批量要问 | 46/51/29 min（batch 1/1/8） |
| 7 | 收尾 + 落后回环 | `finish_run`、`lag_loop` | `track.wav`、`review.mp3`、播放器 | 同步门 | 三语曾各全量重渲 22 min |
| 8 | 人工听审 | 人 | 审核收据 | **整轨或标记听审** | 21/17/15 min |
| 9 | 改句 | `repair_sentence` | 重配窗口 | — | 按窗口 |
| 10 | 发布 | `sfa_publish`、gate | 3 次部署 + 七件套 | **每次部署对话授权** | 13–25 min |
| 10.5 | 大纲与默想 | `build_study` | 学习内容 | `humanApproval` 只来自人 | 可选 |
| 11 | 收尾与报告 | `run_status`、导出器 | 报告 | — | — |

两个与「无人值守」直接相关的观察：

1. **这条线已经是可续跑的。** `spark_queue.py` 跳过已完成句、`state_check.py --write` 能从事件流重建状态、`prepare_clip.py` 幂等、`run_status.py resume` 记等待。这比正式四层线好做得多，断点续跑不需要新建抽象。
2. **唯一没有固定命令的环节是 L1。** 那次英文来源是代理现场做两遍 ASR（`whisper-1` 给时间轴、`gpt-4o-transcribe` 给文本）再合并，不是脚本。无人值守不能依赖即兴，这一环必须固化（§10 M1）。

## 4 四个断点

| # | 断点 | 今天的样子 | 后果 |
|---|---|---|---|
| ① | **会话即生产** | runbook 第一句：「所有工作在代理会话里直接完成」 | 会话一断、DSH 一重启、Mac 一睡，三小时停住 |
| ② | **审核面在本机** | `python3 -m http.server -d $RUN 8765` + `review-player.html`，素材在 `artifacts/` | 人不在电脑前就拿不到；而且 `run_status.py` 的 `_safe_url()` 会丢弃 `localhost/127.0.0.1`，这条链接连通知都发不出去 |
| ③ | **授权在对话里** | runbook：每次 `publish` 都要用户在对话里授权，一个发布意图最多 3 次部署 | 至少 3 次阻塞，全部落在深夜或你需要在线时 |
| ④ | **清单靠代理记** | 10-24 在听审前 84 分钟以 `human_reviewed` 上线、收据随后被覆盖；11-07 七件套漏了对齐、手册、统计目录 | 没人在旁边时，漏的是清单不是代码 |

## 5 门的分级：八个门收敛成两个检查点

| runbook 门 | 现在 | 无人值守后 | 人的时间 |
|---|---|---|---|
| §0 冻结决策（形态／语言／同步／发布／标题／窗口） | 对话逐个问 | 周六上午在审核页填一份计划，默认值取上周 | 5 min |
| §2 英文表人审 | 对话批准 | **检查点 A**：只推 diff + 20 句抽样 + 句界异常 | 与下面两项合并 |
| §3 讲员映射 | 确认 <0.8 的句 | 并进检查点 A 同一页 | 合并 |
| §5 精简稿认可 | 对话认可 | 并进检查点 A：只列被删的词与超预算句 | 10–15 min |
| §7 落后回环 | 手动跑 | 全自动：先 `--check-only` 估收敛，再局部重配 | 0 |
| §8 整轨听审 | 整轨 60–80 min | **检查点 B**：`flagged_only` + 随机 10 句 | 10–15 min |
| §10 每次部署授权 | 对话逐次 | 计划预授权（≤3 次部署），由 `sfa_publish.py` 校验 | 0 |
| §10.5 大纲与默想 | 人批 | 本轮不交付（页面无学习段），事后补 | 0 |
| §10 手机确认 | 人刷新 | 发布后自动 smoke，人第二天看 | 事后 |

门的三种语义（沿用正式线的提法，但在这条线上落地）：

- **`blocking`**：停住等人，超时升级通知。只保留「计划未填」与可选的「生产最终放行」。
- **`deadline`**：等到 T；没人理就按预设继续，**自动打 `humanApproval=false` + `review=auto_waived`，页面披露**。用于文字抽检、音频抽检、译文真疑问。
- **`record`**：只记录不停。用于 QC 失败行、时长警告、讲员低一致度句。

**`deadline` 的诚实边界。** 自动放行不等于人审通过：收据必须写 `reviewMode`（`whole_track`/`flagged_only`/`auto_waived`）与 `unheardAfterApproval`，页面照 [AGENTS.md](../../AGENTS.md) 不变量 1 显示披露。11-07 的收据写 `whole_track` 而实际是跟标记 21/17/15 分钟——runbook §8 自己写了「时间窗对不上就记 `flagged_only`」。**公网播放器顺手把这条诚信问题变成自动记录**：它记录真正播放过的句子，收据不再靠人回忆。

## 6 控制面

### 6.1 形状

```
Drive 公开文件夹
   │ 轮询（出站）
   ▼
launchd: sfa_supervisor (KeepAlive + 退避 + 熔断)
   ├─ 读计划（页面配置 + decisions + 授权）
   ├─ 起 DSH 会话执行 runbook §2–§10
   ├─ 每 60 s：status/status.json ──POST──▶ 控制面
   └─ 每 60 s：控制面决定 ──落盘──▶ run 目录（收据 / 授权 / 改句）
                                              │
[MBP14 + iPhone，中国] ◀──只读 + 写决定（出站）── 公网控制面
                                              ▲
                                      DSH 会话上传 review pack
```

两侧都只出站。这就是对「无法保证 Tailscale」的正面回答：**删掉入站需求，而不是把入站做得更稳**。

### 6.2 数据模型

一个 run 一个文档，字段尽量照抄 `run_status.py` 已有的快照结构，避免第二套状态模型：

| 字段 | 来源 |
|---|---|
| `productionId` / `runId` / `locale` | `status.json` 现有 |
| `runState`、`stages[]`（`state`/`waitingOn`/`actionUrl`/`expectedMinutes`/`etaSeconds`/`errorClass`/`resume`） | 现有 |
| `freshness`（`heartbeatAgeSeconds`、`stalled`） | 现有 |
| `decisions`（形态／语言／同步／发布／标题） | 现有 |
| `checkpoints[]`（id、kind、openedAt、deadline、resolution、receipt） | 新增 |
| `artifacts[]`（review pack、音频、哈希、URL、过期时间） | 新增 |
| `budget`（envelope、spent、hardStop） | 新增 |

计划不要新造格式：**它已经存在两处**——`experiments/sentence-first-agent/pages/<pageId>.json`（pageId、locales、runs、source、title、meta、titleCheck、verdict）与每个 run 的 `decisions.json`（form/sync/publish/title/window），`preflight.py` 已经在校验后者。无人值守只需追加三类字段：预算信封、部署授权（次数上限）、检查点策略（deadline 与默认决定）。

### 6.3 把「依赖翻墙」拆成三条通道

「减少对翻墙的依赖」不是一个决定，是三个独立通道，各有各的解法：

| 通道 | 境内默认可用？ | 取决于 | 结论 |
|---|---|---|---|
| 通知到达手机 | 是 | APNs（Bark 也走 APNs）、飞书/企业微信推送 | 不依赖翻墙 |
| 打开详情页（音频、逐句） | 不一定 | 静态页的宿主 | **唯一真正的翻墙依赖** |
| 决定回传（通过、改哪句） | 是 | 飞书自建应用长连接 | 不依赖翻墙 |

所以只要把「详情页」的宿主管好，整条链可以做到零翻墙；而且决定根本不走页面。

### 6.4 宿主：Firebase 能用的是哪一半

Firebase 是三种完全不同的网络路径，必须分开看：

| 组件 | 出口 | 境内可达 | 结论 |
|---|---|---|---|
| Hosting（`*.web.app` / `*.firebaseapp.com`） | Fastly 边缘（约 `199.36.158.x`），不是 Google 被封的网段 | **需实测，可能可用** | 若可用，直接复用现有 `firebase deploy` |
| Firestore / Cloud Functions | Google 域名 | 基本不可达 | 不能承担页面写回 |
| Cloud Storage | `storage.googleapis.com` | 不可达 | 音频不放这里 |

这带来一个很省事的组合：**若 Hosting 实测可达，审核页做成纯静态页**——页面不发任何 API、音频同域、决定走飞书（§6.5）。只需要一条 `firebase deploy`，不需要新宿主，也不需要新运维。

若 Hosting 不可达，按顺序选：

| 候选 | 境内可达 | 成本 | 备注 |
|---|---|---|---|
| Cloudflare Pages/Worker + R2 | 通常可用 | 近零 | 支持 Range；自定义域名 |
| 香港 OSS（`oss-cn-hongkong`） | 好 | 低 | 默认域名即可，不用备案 |
| 阿里云 OSS + CDN | 最稳 | 中 | 自定义域名要备案 |
| 香港/新加坡 VPS | 好 | 低 | 完全可控，自己运维 |

**十分钟实测清单**（在境内、关掉 VPN 的同一台手机上做完，结论写进本节）：

```text
1. 打开 https://ai-for-god-sermon-audio.web.app        # Firebase Hosting 能不能开
2. 打开同一页面上的任意 MP3，确认能边下边播           # Range 是否被中间设备破坏
3. 打开一个 Cloudflare 托管的测试页                    # 备选宿主
4. 在飞书里收一条卡片并点一个按钮                      # 决定通道
5. 打开任意 https://storage.googleapis.com/…          # 预期失败，确认 GCS 不能放音频
```

五项里 1 与 2 通过，就选 Firebase Hosting；只有 4 通过，就说明「决定走飞书、页面另找宿主」的拆分是对的。

### 6.5 决定通道：飞书自建应用 + 长连接

飞书开放平台的[长连接](https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case)是 SDK 内置的 WebSocket，**本机只要能出公网**就能收消息和卡片回调：不需要公网 IP、不需要域名、不需要内网穿透，也不用手写解密验签。

三条已核实的限制（2026-11-16 查开放平台文档）：

1. 长连接只支持**企业自建应用**（商店应用不行）；
2. 卡片回调必须走**新版 `card.action.trigger`**——[旧的「消息卡片回传交互」不支持长连接](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/step-1-choose-a-subscription-mode/configure-callback-request-address?lang=zh-CN)；
3. 收到事件后 **3 秒内**必须返回，否则触发重推。所以回调只写一条决定，绝不在这里跑生产步骤。

用法分两层：

- **快决**：卡片里放「通过 / 有问题 / 稍后」按钮，回调直接落成一条决定。
- **深审**：卡片里放纯静态详情页的链接；审完在飞书里回一句口令。

口令协议（短、幂等、可核对）：

| 口令 | 含义 |
|---|---|
| `A PASS` | 检查点 A 通过 |
| `A FIX s0031 s0088` | 只改这几句 |
| `B PASS played=52` | 按标记听完 52 句 |
| `B PASS whole` | 整轨听完 |

每条口令带 `productionId`，服务端校验飞书 `user_id`/`chat_id` 白名单，落成 `decisions.ndjson` 的一行；同一 `(productionId, checkpoint)` 只接受第一次，飞书重推天然幂等。

### 6.6 鉴权与过期

纯静态页没有服务端，**链接就是权限**。三条硬要求：

1. 路径随机且不可猜（`/review/<32 字节随机>/`），文件名也带随机后缀；
2. 素材跟着单次 `productionId`，7 天后重新部署一次把旧目录删掉；
3. 页面在 `robots`/`Referrer-Policy: no-referrer` 上不泄露路径，音频不放公开可枚举的位置。

放弃的东西要写明：静态页无法服务端校验收据哈希，也无法记录「逐句真的听了哪些」。收据由 Mac 侧用「口令 + 页面内容哈希」合成，`reviewMode` 记 `whole` 或 `flagged_only`，并加 `selfReported: true`——**不把人的自述写成机器留证**（[AGENTS.md](../../AGENTS.md) 不变量 1）。等哪天真有 CN 可达的 Worker，再升级成服务端记录。

## 7 审核终端

### 7.1 review pack

`finish_run.py` 已经产出 `review.mp3`（96 kbps）与 `review-player.html`；`review_sheets.py` 产出 CSV。远程需要的是一个包：

| 内容 | 体积量级（整期 36 min／语） | 说明 |
|---|---|---|
| `review.mp3` × 3 | 约 25 MB／语 | Range 流式，断点续播 |
| 疑点句切片 × N | 每句 3–8 s | 只上传被标记的句，手机秒开 |
| `pack.json` | 几十 KB | 句表、译文、口播稿、时间、标记原因、哈希 |
| 原声切片（可选） | 每句 3–8 s | A/B 用，`review_player.py` v2 已有该交互 |

一次性下载约 75 MB，MBP14 可以整包缓存；手机只流式取当前句。

### 7.2 交互

复用 `review_player.py` v2，不重写：按句播放、空格暂停、J/K 跳句、Enter 通过、X 标记、F 下一疑点、A/B 原声对照、逐句备注。远程版只加两件：

1. **只推疑点**：默认视图 = 全部疑点 + 随机 10 句，其余折叠。这是把 60 分钟压到 15 分钟的唯一办法，也和 `flagged_only` 的诚实标签一致。
2. **本地保存进度**：`localStorage` + 一键导出，跨设备靠导出文件，不靠服务端（静态页没有服务端）。

### 7.3 纯静态页的取舍

这一版刻意不做服务端写回，换掉的是三样东西：

| 放弃 | 得到 | 补法 |
|---|---|---|
| 服务端续审 | 从中国打开只依赖一次 GET + Range | 审定结果导出成小文件；换设备就导入 |
| 服务端收据 | 不用 CN 可达的 API、不用域名、不用证书 | 飞书口令 + 页面内容哈希，收据标 `selfReported: true` |
| 逐句留证 | 部署仍是 `firebase deploy` 一条命令 | 页面显示「已听 N 句」，口令里带 `played=N` |

**这是一次刻意的诚实降级**：宁可收据写「人自述按标记听完 52 句」，也不假装有机器留证。等有 CN 可达的 Worker 再升级。

### 7.4 离线包（网络最差时的兜底）

同一个 `pack.json` 打成一个自包含目录（`index.html` + 疑点句切片 + `pack.json`），经飞书文件消息或邮件附件发出。审完导出结论，连同口令一起回传。这条路径**零网络依赖**，只在页面打不开时用；它不改变收据语义，只是换一条投递方式。

## 8 可靠性

### 8.1 依赖链与单点

一次无人值守生产要 11 个环节同时成立。每一环的失败都必须在 5 分钟内被看见：

| # | 依赖 | 现在的失败样子 | 检测 | 自愈/降级 |
|---|---|---|---|---|
| 1 | Drive 出现新文件 | 文件在上传中就出现 | 大小稳定 2 次轮询 | 等；超时通知 |
| 2 | 匿名下载 1 GB | 大文件撞 virus-scan 确认页，拿到 HTML | 下载后比对大小与 SHA-256 | 走 confirm-token 流程重试 |
| 3 | Mac 开机、已登录 | 11-07 18:00 机器根本没开，18:25 才补跑 | 心跳缺口 | 自动登录 + `pmset` 定时唤醒 |
| 4 | login keychain 已解锁 | 重启后无人登录 → 读不到 Bark key | 通知发送失败 | 自动登录即解锁；失败即视为最高优先级告警 |
| 5 | DSH 会话存活 | 会话结束=生产结束 | `run_status` 停滞 | 监督者重开会话带 `resume` |
| 6 | Mac → Spark LAN | **今天就是坏的**（banner 超时） | SSH 探活 | 退避重试 + 通知；`reconcile` |
| 7 | Spark 资源不被抢 | `llama-server`／`h3-image-studio` 会自己回来 | `begin` 报 `unmanaged_running_container` | 定期按住 + 重开会话 |
| 8 | Claude CLI 已登录 | 翻译整段失败 | 阶段失败 | 开工 preflight 就查，别等到第 4 步 |
| 9 | Firebase token / ADC | 第 3 次部署失败 | 部署退出码 | 长期凭据；失败即通知 |
| 10 | Mac → 控制面 | 状态推不上去 | 推失败计数 | 本地落盘排队，恢复补推 |
| 11 | 人 → 控制面 | 页面打不开 | 检查点超时 | deadline 继续 + 升级到短信 |

### 8.2 监督者与退避

监督者只做四件事：起会话、看心跳、收决定、退避重试。**它必须是 launchd 的常驻进程，不是会话里的一个 bash。**

今天 Spark 的 SSH 卡死正好是一个反例：`KeepAlive` + `ThrottleInterval 30` 意味着**每 30 秒重连一次，永不停止**。假设（待验证）：高频重连撞上 sshd 的 `MaxStartups` 限流，banner 交换被挂住，于是每次重连都失败、又加速下一次重连。无人值守的监督者必须是**指数退避 + 抖动 + 熔断**：连续失败 N 次后停止重试、只发通知，等人或等下一次窗口。

同样要防的是「假死」：进程在、心跳没了。判据用 `status.json` 的 `freshness`，不用进程存在性。

### 8.3 Spark 侧的三个具体坑

1. **独占会话会被抢。** `begin` 停掉 `spark-api`／`llama-server`／`h3-image-studio.service`，但这些服务会自己回来；停止后单元可能进入 `failed`，需要 `systemctl --user reset-failed` → `reconcile` → `resume-begin`，不要新开会话。
2. **预算要在 `begin` 之后看。** `inspect` 看到的是带非独占服务的状态；`begin` 前数字不够不是故障。本线 TTS 预算是 96 GiB（24 + 9×8）。
3. **`--pool-replicas 8` 链路未打通**（`spark_session_job.py` 不接受 `tts-pool`）。双讲员仍按每讲员一条 `--voice` 排队，不要尝试并行。

### 8.4 预算与幂等

- **周信封，不是逐轮批准。** 10-11 那次生成了 82 份逐轮批准文件，全是引用聊天的仪式。无人值守改成一周一个硬上限，`budget_80%` 通知一次，触顶即停并报告。
- **未知结果停止派发。** 付费调用或远端 TTS 结果未知时，先对账再继续，不许自动开第二份（[AGENTS.md](../../AGENTS.md) 不变量 5 的现有规则，无人时必须由代码强制）。
- **改一句只重配一句。** `repair_sentence.py` 已按 `tts-batches.jsonl` 找窗口；无人值守要默认 `--single`，并把「改一句重配整个 8 句窗」的身份代价写进计划，不许悄悄全量重渲（11-07 三语各重渲 22 分钟）。

### 8.5 降级路径（不实施，只留形状）

真正绑死在美国的只有两件：1 GB 媒体与 GPU TTS。其余（转写、翻译、打包、发布）都能在云端跑。若 Mac 长期不可用，第一降级是 MBP14 用 MPS 跑 TTS（同 checkpoint，1.71–3.26× 慢，且是新执行身份，产物不能与 CUDA 部分拼接）；第二降级是 Cloud Run。本轮都不做，但接口设计不要堵死。

## 9 时间表

按 [runbook](../../experiments/sentence-first-agent/AGENTS.md) §0.1 自己的公式与 11-07 实测推。Drive 上传 T+0 = PT 周六 19:30 = **北京周日 11:30**（PST，+16 h）。

| T+ | 北京时间 | 发生什么 | 人 |
|---|---|---|---|
| 0–10 | 11:30 | 下载、校验、`sfa.py start`、开 Spark 会话 | — |
| 10–25 | 11:40 | L1 转写 / 句表 / 锚点就绪 | **检查点 A 第 1 次推送** |
| 25–55 | 12:00 | 三语翻译 + 独立审计 + 一致性检查 | 审 A（10–15 min） |
| 55–60 | 12:25 | `build_speech`、`spoken_forms`、精简 | — |
| 60–150 | 12:30 | TTS 串行（三语约 75 min）+ `finish_run` + `lag_loop` | — |
| 150 | 14:00 | 三语可审，review pack 上云 | **检查点 B 推送** |
| 150–175 | 14:00 | 补配被标句、重出播放器 | 审 B（10–15 min） |
| 175–195 | 14:25 | 七件套 + gate + ≤3 次部署 | — |
| 195–200 | 14:45 | smoke、手机确认 | 事后看一眼 |

**结论：不需要半夜，也不需要守在电脑前。** 境内周日下午两次手机操作（共 25–30 分钟）、MBP14 上一次深度审核，页面 15:00 前上线，离美国周日礼拜还有一整晚。

这张表是**估算，不是承诺**。11-07 的真跑是 2 h 10 min（19:38 → 21:48）到发布，多了海报、手册、统计目录共 27 分钟；10-23 的整期是 3 h 35 min。表中数值按 batch 8 与「先 `--check-only` 再局部重配」估算，首次真跑必须用 `timings.tsv` 校准后回写本节。

## 10 落地切片

每一片都能单独验收，且都不改变现有门禁的语义。

### M0 看门与播报（1 天）

- `sfa_supervisor` 骨架（launchd，退避 + 熔断）、`status_push`（POST `status.json`）、一个只读网页。
- **飞书自建应用 + 长连接**跑起来：一个进程、出站 WebSocket、不需要公网 IP；先只做「收到卡片按钮回调 → 写 `decisions.ndjson`」。
- 保留 Bark 与邮件作为第二通道。
- **验收**：在境内手机上收到卡片、看到当前阶段与 ETA、按下按钮后 Mac 侧在 3 秒内落盘一条决定；把 Spark 的 SSH 拔掉，5 分钟内收到通知。
- 这一片几乎全是复用 `run_status.py` 的现成字段；它也是唯一能提前证明「这套东西在境内能用」的一步。

### M1 接入与检查点 A（2–3 天）

- `review_pack.py`：生成 `pack.json` + 静态页，随 `firebase deploy`（或 Cloudflare）发布 `review.mp3` 与疑点句切片。
- 静态播放器（远程版）+ 飞书口令解析 + 监督者落盘。
- 计划表单（页面配置 + 预算信封 + 部署授权 + 检查点策略）。
- L1 固定化：把「两遍 ASR + 合并」变成一条命令，或改用 `srt_normalize.py`（有 SRT 时）。
- **验收**：不碰电脑完成英文表批准、讲员映射确认、精简稿认可。

### M2 检查点 B 与发布（2–3 天）

- 音频 review pack、`flagged_only` 收据自动生成、`reviewMode`/`unheardAfterApproval` 落盘。
- `sfa_publish.py` 读部署授权；七件套变成可执行 checklist（`sfa_publish_gate.py` 已有一半）。
- **验收**：整期真跑，从 Drive 上传到你手机上看到「已发布」，gate 带 `--require-guide --require-alignment` pass。

### M3 自愈与热修（持续）

- 会话死了自动重开带 `resume`；`repair_sentence.py` 接进审核页；每月凭据体检；周报自动出「计算／返工／等人／花费」四段。

## 11 未决问题

1. **监督者怎么起会话**：走 `remote-agent-watch` 的 DSH Remote API（已有、手机在用），还是写一个只跑固定命令序列的窄脚本、只把判断类步骤交给代理？（决定 M0 的形状）
2. **审核面宿主**：先做 §6.4 的十分钟实测——在境内手机上直接打开现有的 `https://ai-for-god-sermon-audio.web.app`。能开就用 Firebase Hosting（一条 `firebase deploy`，最省事）；打不开再选 Cloudflare / 香港 OSS / 阿里云。
3. **飞书应用类型**：确认你用的是**企业自建应用**（长连接只支持这一类），并决定用哪个群或私聊承接决定。
4. **发布授权粒度**：整批预授权（≤3 次部署），还是最后一次生产部署仍需人手点？
5. **MBP14 的角色**：只做审核终端，还是保留「降级生产者」（MPS TTS）的能力？后者要提前把 checkpoint 与 `.venv-sfa` 复制过去，且产物是独立执行身份。
6. **Drive 文件是否等于证道全文**：若几乎不需裁切，窗口确认可降级为 `record`，少一次手机操作。
7. **L1 用哪条路**：`srt_normalize.py`（需要滚动 SRT）还是固化两遍 ASR？这决定检查点 A 之前要多久。

## 附录 A 复现本文的实测

```bash
# Spark 状态（2026-11-16：22 端口通、banner 超时、8080 拒绝）
nc -z -G 3 192.168.1.152 22; echo $?
nc -z -G 3 192.168.1.152 8080; echo $?
ssh -o BatchMode=yes -o ConnectTimeout=4 achillesjing@192.168.1.152 hostname
launchctl list | grep spark-tunnel          # 状态 255

# Tailscale 节点与中继
/Applications/Tailscale.app/Contents/MacOS/Tailscale status

# Synology 同步上限与目录规则
grep -A2 -E "max_size|\[Directory\]" \
  ~/Library/Application\ Support/SynologyDrive/data/blacklist.filter

# 产物体积
du -sh artifacts                            # 254G

# run 状态快照（控制面的字段来源）
python3 experiments/sentence-first-agent/run_status.py status --run <run>
```
