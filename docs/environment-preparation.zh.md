# 多语言证道生产环境准备

本文按“共享英文来源 → 目标语言文字 → 目标语言音频 → 多语言发布 → 海报收尾”排列准备事项，供首次搭建和每周开工前核对。它描述当前仓库接线和权限边界，不代表任何 key、模型、Spark、Firebase 站点或设备已通过本机实测。

四层生产的唯一输出及失效规则见[四层接口合同](multilingual-production-interfaces.zh.md)。遇到政策冲突时，以当次已冻结的运行身份和当前项目政策为准；历史报告不替代当前预检。

## 一、总览：凭据、工具与 Skills

### 凭据与授权

| 凭据／身份 | 用途 | 什么时候需要 | 存放与边界 |
|---|---|---|---|
| OpenAI `tongxing-dev-runtime` 项目 key | Dev、Beta、实验中的来源转写及接入 OpenAI API 的文字生产 | 这些阶段使用 OpenAI API 时 | `.env.openai` 中的 dev 项目 ID/key；仅由显式环境启动器注入 |
| OpenAI `tongxing-prod-runtime` 项目 key | 正式内容的转写及接入 OpenAI API 的文字生产 | 正式生产的相应 API 阶段 | `.env.openai` 中独立的 prod 项目 ID/key；不得与 dev 共用 |
| ChatGPT 登录的 Codex CLI | Supervisor 和已配置为 CLI 的工作 | Supervisor 或明确选择 Codex CLI 的角色 | CLI 用户认证；不是 OpenAI API key，也不提供 API 账单归因 |
| YouTube Data API key | 需要该 API 的 YouTube 元数据或下载辅助流程 | 仅在调用路径确实要求时 | 按现有 Secret Manager resource reference 读取；不是每条来源都需要 |
| Google Cloud/Firebase 部署身份 | 读取线上 baseline、部署 Hosting/Functions、执行线上 HTTP 回读 | Layer 4 实际发布时 | Dev 与 Production 项目分开授权；不提交 token、` .firebaserc` 或 service-account key |
| Cloud Storage 身份 | 上传 bucket 视频或读取相应对象 | release profile 使用独立视频 bucket 时 | 区分 Dev/Production bucket、对象路径和权限 |
| SSH 身份及主机密钥 | 连接 DGX Spark 或经 relay 执行 MFA/TTS/ASR | 本次 producer 需要远端 Spark 时 | 使用既有 SSH/Tailscale 配置并校验 host key；不关闭主机验证 |
| Apple 下载徽章素材 | 海报第一次准备时取得官方徽章 | 生成海报时 | 生成器缓存官方素材并记录哈希；不需要 Apple API key |
| Apple 开发者/签名身份 | iOS 客户端发版、TestFlight 或特定设备安装 | 仅当发布范围包含 iOS 发版时 | 与网页内容发布分开；普通 Layer 4 Hosting 发布不需要 |
| 通知服务凭据 | 发送邮件或其他外部通知 | 仅在用户明确要求且流程启用通知时 | 当前周生产模板默认禁用 SendGrid；默认在 Codex 内报告 |

**不需要为新 Layer 2 常规策略另建 Gemini/Astra key；本地 Layer 3 Qwen TTS/ASR 不靠 OpenAI key；Codex 内置 ImageGen 不要求单独图片 API key。** Sunday live captions 是独立 `live_session`，不自动并入本文的预制四层流程。

### 本机和远端工具

- 仓库 checkout、Git、Python 虚拟环境及仓库依赖；按对应任务安装 `requirements.txt` / `requirements-test.txt`。
- `ffmpeg`、`ffprobe`：媒体解码、格式、时长及完整性检查。
- `yt-dlp`：适用来源的媒体获取；使用 cookies 或私人来源时必须符合来源授权，不把 cookies 写入 Git 或日志。
- MFA 与语言模型：Layer 1 词级对齐优先检查 Spark MFA 环境，MacBook 仅在规定的基础设施/runtime 故障下备用。
- DGX Spark：相应 CUDA 容器／运行时、模型权重、检查点、GPU broker、worker/dispatcher、传输适配器及远端 job 根目录。SSH 可达不代表模型、设备或 producer 可用。
- Node.js：运行页面构建或音频定位索引所需脚本时。
- Firebase CLI / Google Cloud CLI：当前 CD 工具运行外部部署命令、检查指定 Firebase/GCP 项目时。
- Swift 命令行工具及 macOS AppKit、CoreImage、Vision：本机合成海报时。
- Xcode、iOS 设备和必要签名：只在客户端构建／真机验收范围内准备。

### Codex Skills 与项目说明

Skills 是 Codex 的操作说明，不是外部运行凭据，也不能代替仓库 producer 门禁。

| Skill / 说明 | 对应步骤 |
|---|---|
| `dgx-spark-connect` | 远端 Spark 连通、模型服务、GPU 和导出文件状态检查 |
| `imagegen` | 基于已核实的本周证道 brief 生成无文字海报主视觉 |
| `live-caption-zh-fallback` | 只服务 Sunday live / 离线字幕备份；不作为预制 Layer 1–4 的默认路径 |
| [MFA 生产说明](mfa-production.zh.md) | Spark/Mac MFA、路径身份、缓存与受限 fallback |
| [模型运行政策](production-model-runtime-policy.zh.md) | Layer 2 模型、后端、预算绑定和凭据启动方式 |
| [周更发行说明](tongxing-weekly-release.zh.md) | Layer 4 页面发布、HTTP 核验、App 验收及海报顺序 |
| [海报格式规范](tongxing-weekly-poster-format.zh.md) | 画布、二维码、徽章、免责声明和海报 QA |
| [海报内容 brief](tongxing-weekly-poster-content-brief.zh.md) | 如何从本周证道内容形成主视觉概念和 prompt |

## 二、配置 OpenAI Dev/Production 项目

### 本地 `.env.openai`

用两个不同的 OpenAI Project 和项目范围 key：`tongxing-dev` / `tongxing-dev-runtime`、`tongxing-prod` / `tongxing-prod-runtime`。照[双 Project 配置说明](openai-minimal-project-setup.zh.md)创建被忽略的 `.env.openai`，权限设为 `600`，填入以下四项；不要将 key 发到对话、贴进命令、日志或 Git：

- `OPENAI_DEV_PROJECT_ID`
- `OPENAI_DEV_API_KEY`
- `OPENAI_PROD_PROJECT_ID`
- `OPENAI_PROD_API_KEY`

配置预检只检查文件格式和选路，不证明 key 有效、Project 归属、模型权限或账单限额。对真实调用另行在供应商控制台核对权限、预算预警与上限。

```bash
python3 scripts/run_with_openai_environment.py --environment dev --check
python3 scripts/run_with_openai_environment.py --environment prod --check
```

真正调用必须由该启动器选择环境。开发、Beta 和实验使用 `dev`；正式内容生成使用 `prod`。不要用改 `.env`、在 producer 命令明文传 key 或覆盖旧 Secret Manager 引用来切换环境。长期 controller/supervisor 在启动整个进程时选定环境；旧 job 不自动迁移。

## 三、按生产流程准备

### 1. Layer 1：共享英文来源与锚点

**输入**

- 有权使用的完整媒体及其来源 ID/URL、服务日期。
- 操作员确认的证道窗口，媒体 SHA-256、字节数和实测时长。
- 冻结英文 ASR final、与源音频绑定的词级对齐、锚点 manifest。
- 需要翻译时，source package 必须达到 `ready_for_translation` 并绑定所需范围与审核收据。

**需要的资源**

- 媒体在本地或已配置远端可读取；`ffprobe` 可读取容器和时长。
- 来源 ASR 若通过 OpenAI，启动对应 dev/prod Project key；YouTube API key 仅在其特定来源路径要求时启用。
- MFA 所需声学模型、词典、可选 G2P 模型及匹配版本；优先检查 Spark MFA 运行时及远端路径，Mac fallback 只用于获准的基础设施/runtime 故障。
- SSH host/key 与可选 Tailscale relay；记录实际连接和模型身份，不能只依据静态配置声称可用。

**产物与检查**

- 完整来源媒体身份、批准窗口、不可变 ASR、词级对齐、anchor manifest、English Source Package 和对应审核收据。
- 媒体 hash、对齐 provider、模型/词典版本、执行主机与缓存身份可追溯。
- 任何来源或时间线身份改变都使下游失效；机器 source judge 不替代人工范围和来源审批。

### 2. Layer 2：每个目标语言的文字

**模型与运行方式**

- 新 dev 与正式运行：`gpt-6.1-sol` high 初译，`gpt-6.1-sol` medium 独立复核，经 OpenAI API。
- Supervisor：`gpt-6-luna` medium fast，经 ChatGPT 登录 Codex CLI。它与 OpenAI API key 是不同的认证面。
- 使用对应 locale 的语言插件、共享术语表、canonical Layer 2 controller、预算 config/authorization、ledger、候选组装和准入检查。

**准备内容**

- Layer 1 English Source Package、anchors、语言 policy、glossary 和每个 locale 独立输出目录。
- 每个正式 API dispatch 都绑定来源、policy、plugin、locale、预算及输出目录；Standalone API 请求需使用 canonical controller 接受的预算授权路径。
- 预留结构化候选、逐组初译/复核收据、用量/耗时账本、语言插件结果及人工审核工作表的存储空间。

**停止与交接**

- 初译或 reviewer 标记失败/不确定时，保存证据，使用新 revision 重跑规定的 translator/reviewer/plugin/admission 链。
- 机器复核不是人工文字批准。候选未通过当前 plugin/hash gate 不可进入正式 Layer 3。

### 3. Layer 3：目标语言音频与同步

**模型与执行资源**

- 准备与 speaker registry 对应且用途授权的 TTS checkpoint、Qwen TTS/ASR 权重、运行容器/依赖、GPU 设备、broker/worker、dispatcher 和 Spark 输出目录。
- 对正式 canonical renderer，确认本任务必须显式提供的模型路径、transfer adapter、job 目录、checkpoint map 和相关音频 operation policy；项目策略不代表所有 producer 已有自动跨机 dispatch。
- 本地 `ffmpeg`/`ffprobe` 用于音频完整解码、格式/时长检查。模型推理使用 Spark 为默认路径；只在确认的基础设施/runtime 故障时按规则 fallback，且设备/精度改变应使用新执行身份。

**输入与准入**

- 通过门禁的同 locale Target-Language Candidate、Layer 1 anchors/source package、语言音色注册及绑定的人工文字批准或支持路径上的有效机器质检收据。
- 运行前对照 candidate hash、plugin identity、checkpoint、代码和配置；身份不匹配就停在 Layer 3 preflight，不派发 TTS/ASR。

**输出与检查**

- 保存逐句/逐单元 TTS 输出、renderer manifest、文件 hash、真实时长、解码结果、回转写 ASR 筛查、同步排程和完整 Audio Package。
- ASR 是筛查，不等于试听通过。正式人工路径须全文 1 倍速听审并对照视频同步，裁决 ASR 疑点；机器豁免路径须使用与当前实现、设置、候选及音频绑定的校准/QC 收据。
- 每个发布语言都要有同 locale 音频包，或在发布计划/producer/client 明确支持时产生显式 `audio_unavailable`。

## 四、Layer 4：多语言页面发布与播放

### 4.1 发布包和部署前资源

对每个 `pageId + targetLocale` 准备：

- 审核后的 Layer 2 Candidate 和 Layer 3 Audio Package，所有上游 hash 和人审/机器披露状态一致。
- 标题、系列、来源日期、经文、讲员、完整翻译、字幕、音频、英文对照、定位索引、页面和 Release Package。
- 本次 release plan 的 locale join 要求；只有计划明确要求时，等待多个 locale 同时发布。
- 正式站完整基线快照、当前 catalog、可回退 catalog、每个既有文件的 path/hash map 和旧站 Firebase 配置。

机器审核发布必须按适用的 release/catalog 版本产出 machine_checked 状态、逐项依据及披露，并提供人工投影 catalog；不得把 release v4 与 v3 projection 混淆。普通人工批准路径使用合同指定的正式 package/catalog 版本。纯文字 release 只有在 release plan、producer 和 Web/iOS 客户端都支持时才使用。

### 4.2 Firebase/GCP 环境

- Dev 与 Production 使用不同 project、Hosting site、短期凭据/服务身份和预算告警。
- 正式部署入口 `scripts/run_multilingual_cd.py` 显式指定 `--mode dev` 或 `--mode production`；不要依赖默认 project、当前 Firebase alias 或本机 `.firebaserc` 推断目标。
- `--execute` 对代码 checkout 有严格要求：Dev/Production 对应分支干净、commit 与远端一致，并传入代码 commit 与 `build-report.json` SHA。
- Bucket 视频配置还需要正确的环境 bucket 权限、不可变对象路径、完整视频、字节数/hash、Content-Type 和 baseline `firebase.json`；不能将视频文件悄悄塞进 Hosting manifest。
- 发布约 700 MB 内容候选走本机受控 CD，而不是把本机媒体路径塞进 GitHub Actions。

### 4.3 候选、预检、执行和 HTTP 收据

先在当前干净、已核实的 checkout 上按对应 release builder 生成新候选。对 bucket profile，官方组装形状如下：

```bash
.venv/bin/python scripts/assemble_multilingual_v3_update.py \
  --base-public artifacts/<完整线上基线>/public \
  --stage-public artifacts/<本周已审资产>/public \
  --stage-manifest artifacts/<本周已审资产>/stage-manifest.json \
  --base-firebase-json artifacts/<完整线上基线>/firebase.json \
  --video-file artifacts/<本周已审完整播放视频>.mp4 \
  --out artifacts/<本周候选目录>
```

纯 Hosting 视频配置不传 `--video-file` 和 `--base-firebase-json`。**这是现有旧版 v3 周更组装示例，不是所有 Layer 4 release 的通用组装器**；它只写 catalog v3，遇到 v4 基线会拒绝。按本周 canonical delivery contract 选择实际 builder/schema：例如四产物发布和机器质检发布使用各自要求的 release/catalog 版本。构建后以对应的只读 inspector 核对完整线上基线、历史文件保留、资产清单、release/catalog 绑定、代码 commit 与 build report hash。检查成功仍不等于上线许可。

正式 CD 先只做预检，不带 `--execute`：

```bash
.venv/bin/python scripts/run_multilingual_cd.py \
  --mode production \
  --candidate artifacts/<本周候选目录> \
  --out artifacts/<本周-production-cd收据目录> \
  --expected-commit <40位代码commit> \
  --expected-build-report-sha256 <build-report.json的64位SHA256>
```

Dev 把 mode 和绑定候选换成 `dev`。核对 environment、项目/site、线上完整 baseline、候选哈希和 release plan 后，才在同一输入上加 `--execute`。CD 应输出 `preflight.json`、`deployment.json`、`http-verification.json` 和 `cd-receipt.json`；若预检失败或未能确认实际部署身份，不继续执行。

发布后必须核验：

1. 每项 catalog、Release、页面、全文、字幕、英文参考、定位索引、音频文件的 HTTP GET、长度和 SHA。
2. 每条 MP3 的 Range 响应、`206`/`Content-Range` 与首段字节。
3. Bucket 配置的视频对象完整 hash/size/Content-Type、GET、首尾 Range/CORS、同源旧 URL 精确 302 和浏览器播放/拖动。
4. 更新后仍保留全部旧周/旧资源；catalog 指向本周准确 pageId、语言包和文件。

只有本轮候选与 HTTP 收据绑定且通过，页面才记录 `published_http_verified`。HTTP 不代表设备/现场成功。iOS 客户端需在实际安装版本中刷新目录、打开每种发布语言、核对披露和离线/播放行为，分别记录构建版本、设备、时间、pageId、locale 和结果。已发布页面可以进入海报阶段，不必等待无关现场验收。

## 五、发布后海报流程

### 5.1 海报前置条件与范围

- 读取本轮**已发布并通过 HTTP 核验**的目录、精确 `pageId`、站点 origin 和发布语言。不得用文件夹日期或“最新周”猜测页面。
- 默认三语 release plan 生成中文 `zh-Hans`、韩语 `ko`、西语 `es` 三张；只含中文的 release plan 只生成中文。只通过 `--locales` 缩小范围，不通过它制造尚未发布的 locale。
- 当前海报文案承诺可收听音频；`audio_unavailable` 纯文字语言暂不生成正式海报，应排除并留待办。
- 正式 origin 固定为 `https://ai-for-god-sermon-audio.web.app`。Dev/Beta 打样需用对应 Dev origin 并传 `--non-production-proof`，产物标记为非正式。
- 海报生成不依赖 OpenAI/Gemini/Apple API key；Codex 内置 ImageGen 生成一次无文字主视觉，Python/Swift 本机程序负责文字、二维码、徽章和导出。

### 5.2 先准备 brief，再生成图片

对当周已核对全文提取主题、核心完整句和视觉证据，按[海报内容 brief](tongxing-weekly-poster-content-brief.zh.md)展开 prompt；保持固定模板但使画面对应本周内容。不要让 ImageGen 写标题、日期、经文、免责声明或二维码，也不要把未展开的 `{{字段}}` 直接作为 prompt。

先运行多语言海报生成器的准备模式，不传 `--art`：

```bash
.venv/bin/python scripts/build_multilingual_sermon_posters.py \
  --release artifacts/weekly-release/<已发布发行目录> \
  --page-id '<本周完整pageId>' \
  --origin https://ai-for-god-sermon-audio.web.app \
  --out artifacts/sermon-poster/<日期>/multilingual
```

这一步准备来源绑定的语言 brief/prompt，不会调用图片生成。使用 `imagegen` Skill 生成无文字共享主视觉，并把实际使用的完整提示词与原始图片保存在该 run 的 ignored artifacts 中，例如 `shared-art.png` 和 `exact-imagegen-prompt.txt`。同一主视觉复用于各语言；若调整构图或 prompt，应保留新的身份和证据。

### 5.3 本地合成

必须沿用相同发行目录、pageId、origin、locale scope 和输出目录：

```bash
.venv/bin/python scripts/build_multilingual_sermon_posters.py \
  --release artifacts/weekly-release/<已发布发行目录> \
  --page-id '<本周完整pageId>' \
  --origin https://ai-for-god-sermon-audio.web.app \
  --art artifacts/sermon-poster/<日期>/shared-art.png \
  --art-prompt artifacts/sermon-poster/<日期>/exact-imagegen-prompt.txt \
  --out artifacts/sermon-poster/<日期>/multilingual
```

需要英语参考图时，传入绑定来源 `sourceIdentitySha256`、中文 `contentSha256` 且含已核对英文文案的 `--english-reference` JSON。参考海报仍是中文内容/音频的宣传参考，不创建英语 release 或 App announcement。

每个正式 locale 预期输出 1200×1800 高清 PNG、600×900 预览和 `poster-receipt.json`；总目录含 `poster-manifest.json`。网页二维码绑定准确 URL：

- 中文：`?week=<pageId>&contentLang=zh-Hans&lang=zh`
- 韩语：`?week=<pageId>&contentLang=ko&lang=ko`
- 西语：`?week=<pageId>&contentLang=es&lang=es`
- App Store 码固定到同行正式下载页。

内容文字来自已发布 catalog/Release，不由 ImageGen 或渲染脚本临时翻译。机器质检语言显示其实际披露；英文参考图标记不适用于英语 App announcement。

### 5.4 海报 QA 和可恢复边界

对每语言的高清图和预览图分别执行：

1. 独立解码二维码；每张图恰有网页码和正式 App Store 码，完整 URL 与页面、语言绑定逐字一致。
2. 浏览器访问网页码目标，检查 pageId、内容语言、界面语言和对应播放资产；检查 App Store 码落在正式同行页面。
3. 目视检查标题、系列、日期、讲员、经文、语言披露、App 原文免责声明、徽章比例、留白、裁切与码清晰度。
4. 检查 receipt 绑定的 release/catalog、HTTP 验证、主视觉、prompt、模板和徽章哈希。
5. 全部图片实际目视后，使用完全相同的渲染参数再运行并传 `--visual-reviewed`，写入图片目视 QA 收据。它不授予内容人审或音轨听审通过。

若 receipt 显示页面或输入 hash 变化、文件被改写、换了主视觉/prompt/模板/语言范围，使用新输出目录生成新版本；不覆盖旧产物。只失败的语言允许单独重做，不重发已核验页面或重跑 Layer 1–3。

### 5.5 上传、线上核验和设备状态

图片生成器**没有上传功能**。按仓库 AGENTS，未收到上传指示时只交付本地 PNG、预览和 receipts，不部署、不发消息。获得上传指示后，单独准备该环境的完整 Hosting baseline 和当前文件 map/config，仅追加目标语言图片与 sidecar，保持其余文件 hash/catalog 不变。Dev 与 Production 要各自绑定自己的 release SHA 和部署收据。

上传后分别检查：图片与 sidecar HTTP GET/SHA、完整 Hosting inventory、索引中的 pageId/locale/release SHA。随后单独记录客户端是否读取索引、是否能打开/显示海报以及真机扫码结果。HTTP 图片可读不能证明当前 App 版本已经实现海报索引读取器；印刷和外部发送也分别验收/授权。

## 六、开工前快速验收表

| 检查项 | 通过证据 | 未通过时停在 |
|---|---|---|
| OpenAI 路由文件格式 | 启动器 `--check`；真实权限另查供应商侧 | 使用 API 的 Layer 1/2 阶段前 |
| 来源与媒体身份 | source ID、完整媒体 SHA/时长、人工窗口收据 | Layer 1 |
| MFA/Spark | 实际 SSH/relay、runtime/模型/checkpoint/路径预检 | 付费转写或远端模型派发前 |
| Layer 2 budget/policy/plugin | 冻结 policy、预算授权、controller ledger、候选准入收据 | Layer 2 dispatch 或 Layer 3 前 |
| Layer 3 runtime/voice | 同身份检查点、GPU/worker/dispatcher、TTS/ASR/音频收据 | Layer 3 dispatch |
| Layer 4 baseline/auth | 项目/site、干净远端一致 commit、完整线上 baseline 和本地候选检查 | `--execute` 部署前 |
| 发布后 HTTP | 逐文件 GET/SHA、音频 Range、bucket 视频 Range/redirect（适用时） | `published_http_verified` 前 |
| 海报输入与二维码 | 发布目录、HTTP receipt、精确 pageId、两尺寸二维码解码和目视检查 | 海报交付前 |
| 海报上传与客户端 | 环境绑定上传收据、HTTP inventory、App 索引/显示或真机证据 | 分别记录上传/设备状态 |

正式运行后依项目规定导出脱敏 run digest；运行日志、媒体、凭据和海报大图保留在 ignored artifacts，不把本地绝对路径、私有收据或密钥写进公开包。
