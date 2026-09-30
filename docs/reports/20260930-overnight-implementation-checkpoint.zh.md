# 2026-09-30 实施与剩余证据检查点

本报告是有日期的工程证据对照，不是部署或验收收据。基线 `dev` 为 `f95346ab3f7068f7f9dff3db57edd37d79f14d29`。截至 10:10 UTC，#122–#144 都是未合并的 draft PR；#121 是先前已有的非 draft 前置。没有本轮生产部署、App Store 发布、真实付费跑批或人工/设备/现场 sign-off。

## 精确提交与远端检查

下表记录读取时的 head。#121–#143 的两个 Python 分片及 `unittest` 汇总均通过；这些 PR 的 `ios-validation` 和 `contract-validation` 都是 skipped，`native-client` 成功只证明路由。新 head 需重查；旧审查不自动覆盖后续提交。#144 在 250 项本地 Stage 0 组件及后端模拟通过后推送，远端检查另见 PR，不据此称其远端已通过。

| PR | 精确 head | 实现范围 |
|---|---|---|
| [#121](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/121) | [29c41cb4c600](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/29c41cb4c600ae49bce036f699996ea26de16d6d) | feat: start dependency-aware accounting v3 |
| [#122](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/122) | [f5a09e441335](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/f5a09e4413357d8f665ffe4cbfe3b29eac927601) | feat: validate dependency accounting and project pipeline evidence |
| [#123](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/123) | [e5b0be2590b7](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/e5b0be2590b70c12ea8bce57cb0308994ce320db) | feat: add deterministic control over existing durable release jobs |
| [#124](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/124) | [bf5203c72998](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/bf5203c72998841b75c6e2cc4ff00dfad4678659) | feat: connect L2 and L3 producer dependency spans |
| [#125](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/125) | [68fc85cedc3d](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/68fc85cedc3dfbc4f19d31c6176849b226e46be0) | feat: define canonical lanes and bounded decision contracts |
| [#126](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/126) | [e495df8a282d](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/e495df8a282dd3972ff6394779f2e4d509f4e73a) | test: cover worker and controller crash windows |
| [#127](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/127) | [6116d3eceb6e](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/6116d3eceb6e293f9ab72395a7a36da29dd4507b) | feat: inspect canonical Source and Text packages read-only |
| [#128](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/128) | [a3cb50970a02](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/a3cb50970a022a27aa773fcf2ea3fe8335c4a439) | feat: inspect canonical audio artifacts and listening receipts |
| [#129](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/129) | [ec19cd4ea873](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/ec19cd4ea873b9daf7f1a8503f39238cce667a08) | feat: inspect canonical release candidates through shared preflight |
| [#130](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/130) | [da89e26a3c07](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/da89e26a3c075f96f0ee5307d35fee8a4ad54d71) | test: collect head-bound Stage 0 component evidence |
| [#131](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/131) | [983d59554e3c](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/983d59554e3cc93070c0c9097731eb3c94b7ee9d) | feat: reserve bounded decision attempts with durable receipts |
| [#132](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/132) | [eb526a52dde5](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/eb526a52dde5f8940985e6d4c40f9742033d6bca) | feat: add local fingerprint session diagnostics |
| [#133](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/133) | [c2c677bdee3c](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/c2c677bdee3c24e4745f48c50bc5ffd4d22b083a) | test: verify frozen fingerprint numerical baseline |
| [#134](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/134) | [fbf34431afd6](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/fbf34431afd6ffc63411626146875fe576f99874) | feat: account for bounded decision work and durable commits |
| [#135](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/135) | [f835df6502e3](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/f835df6502e31427273b0b633195476aea99dc0e) | fix: route current shared contracts to native validation |
| [#136](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/136) | [3a5eecdf717e](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/3a5eecdf717e1d1a9d89ecb2a9969493335b6a89) | fix: persist job directory ancestry before side effects |
| [#137](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/137) | [4a8e9327d93b](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/4a8e9327d93bb04decbcb32b514875fc62f2bcbe) | fix: enforce shared release evidence in Web and native clients |
| [#138](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/138) | [9c04115eb746](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/9c04115eb7464235b1aecdb124946349d248017b) | feat: verify fingerprint index before microphone capture |
| [#139](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/139) | [d82870b1103e](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/d82870b1103edb3e722a51b408863f6c8680ef0e) | fix: broaden CI for unclassified paths and workflow inputs |
| [#140](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/140) | [f3c95cff89c0](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/f3c95cff89c07409957e41cbcd843be988f5292a) | feat: share hash-bound Layer 4 asset assembly with simulation |
| [#141](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/141) | [9137756d98ec](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/9137756d98ec7fed528c015c6c487083e792e6a5) | fix: validate source readiness before paid translation |
| [#142](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/142) | [dd89ebe83fb9](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/dd89ebe83fb9b3373c73d42bf2b48eab09b78126) | fix: validate catalog targets with shared client fixtures |
| [#143](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/143) | [499c6e7067d7](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/499c6e7067d7aeeb91d01b2b7891637c937adbbb) | fix: persist paid model cache intent before responder |
| [#144](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/144) | [bbd88b559141](https://github.com/JonathanJing/sermon-video-zh-subtitles/commit/bbd88b5591417f9853caf7d61126a0f43aa1a601) | 周更组装绑定准入manifest/base snapshot |

依赖链：#144→143→141→140→136→134→131→130→129→128→127→126→125→124→123→122→121。独立客户端链为 #142→137→135；#139也依赖135。FIELD链 #138→132；#133独立于这些执行改动。都以 dev 为 PR base；依赖不意味着已合并，不应无视顺序直接集成。

## 已复现修复的本地证据

- #137：producer 140/141/160 字符 pageId 的三语包共用30-case fixture；旧Web拒绝6个合法长ID，修复后224 Web、9 legacy、11 Python、58实际Swift Core通过（6 skipped）。
- #138：deferred Worker预检后必须新点击录音，真实capture函数由gesture-sensitive stub检验拒绝后重试；212 Web、17 build通过。没有Safari设备复现或验收。
- #141：缺media/非法window/失配derived identity即便刷新policy hash也在模型调用前拒绝；102相关测试、229 Stage0组件加后端模拟通过。
- #142：错误release路径返回正确bytes/hash仍须在fetch前拒绝；31-case target fixture由Web/native/schema共用。257 Web、9 legacy、15 Python、59实际Swift Core通过（6 skipped）；text-only准入不是Web文字阅读功能验收。
- #143：started intent、raw、result与目录链持久化，未知结果不重调；旧代码5个assertion失败，修复后7项新回归、99相关测试及236 Stage0组件通过。仅fsync次序/故障注入，不是物理断电实验。
- #144：旧代码3个快照变化反例可复现；39相关测试、250 Stage0组件和后端模拟通过。保持本地staging范围，无真实发布/回滚。

测试数量属于各批自己的范围，包含重复执行，不能相加成独立覆盖数量。Stage0报告仍是 `component_checks_passed_stage_incomplete`，`stage1PromotionAllowed=false`，生产模型用量未由组件harness实测。

## 38项逐项对照

本次只把已有实现的6个顶层项从待启动改为 `in_progress`；没有任何整项变成 `complete`。其他状态沿用原backlog，不把有代码的子项扩展为整项验收。

| 顶层项 | 状态 | 本轮实现/证据 | 仍需满足 |
|---|---|---|---|
| `DEV-GOV-001` | `verified_baseline` | 不新增合并/晋升 | 后续合并权限和受保护分支检查；提交祖先数量不代表 runtime 功能差异 |
| `DEV-L1-001` | `in_progress` | #127/#141 Source identity、window、derived identity 准入 | 真实整篇媒体/文本/锚点及独立人工审核 |
| `DEV-L2-001` | `in_progress` | #124 真实 producer spans；#141/#143 准入/持久性 | 三语真实模型/插件/人工批准与局部恢复完整交付 |
| `DEV-L3-001` | `in_progress` | #124 cache admission/receipt decode 计量；#128 只读正式验证 | 整篇自然语速、回转写、听审与同步；可移植包 |
| `DEV-L3-002` | `in_progress` | 本批未运行自然表达 A/B | 真实声学锚点/overrun 修订与听感验收 |
| `DEV-WEEK-001` | `pending` | 本批未实现统一周产交付冻结入口 | 整篇/三语/App/二维码/设备矩阵及自然时长预检 |
| `DEV-L4-001` | `in_progress` | #140 共用资产复制；#144 快照保护 | 真实新周 Dev 基线、追加、HTTP/Range、恢复 |
| `DEV-L4-005` | `in_progress` | #140 后端模拟调用共用资产复制 | 通用新周 Dev 预演与真实批准包回放 |
| `DEV-E2E-001` | `in_progress` | #130 Stage 0；#140 共用 Layer 4 copy；#144 累计250项组件 | Canonical durable 全流程仍不完整；真实包与故障后完整恢复 |
| `DEV-CICD-001` | `pending` | #144 支撑快照绑定子项，未实现统一发布计划 | 环境/代码/站点/基线/批准/回退统一身份与入口 |
| `DEV-L4-003` | `in_progress` | #129 formal-dev release 只读检查；原 #115 审计保留 | 私有正式人审链审计接入真实发布入口及候选验证 |
| `DEV-L4-004` | `in_progress`（2026-09-27 开始） | #144 v3 候选复制绑定 | 真实 v3 新周发布/回退、Web与同版本iOS刷新 |
| `DEV-IOS-001` | `in_progress` | #137/#142 共用Release/catalog target decoder夹具 | 三语真机下载/离线/播放/系统媒体；跨轨合同 |
| `DEV-FIELD-001` | `in_progress` | #132诊断；#133数值基线；#138索引先验与新录音点击 | 真实声学/盲测/距离噪声设备；15秒协议、AGC及离线 readiness |
| `DEV-TRACK-001` | `in_progress` | #122/#124/#134 dependencies、usage、Weekly投影 | 真实同一周全部span/等待/重试/token覆盖与ETA |
| `DEV-REVIEW-001` | `pending` | 本批未实现远程私有审核后端 | 认证权限、事务、版本冲突、不可变收据及真实两位审核者 |
| `DEV-LIVE-001` | `in_progress` | 保持独立live_session，未作新现场验证 | ASR final、翻译延迟、fallback真实回放/现场证据 |
| `DEV-PROD-001` | `blocked`（后续内容部署门禁） | 无本轮 merge/deploy | 逐次Production授权、批准包、Dev验证/回退/基线 |
| `DEV-VOICE-001` | `in_progress` | #128复用既有voice gate；未换模型/音色 | 授权范围、checkpoint/hash与干净环境媒体恢复 |
| `DEV-L4-002` | `in_progress` | #140/#144不可覆盖复制与旧快照保护 | 真实catalog最后发布、单locale回退与旧资产验证 |
| `DEV-IOS-002` | `in_progress` | 仅本地Core合同测试；没有新系统UI验收 | iPhone WebView、锁屏、耳机、中断、Live Activity、无障碍 |
| `DEV-CICD-002` | `in_progress` | #135/#139路由矩阵；#137/#142跨端夹具 | 全语义兼容矩阵、真实非draft iOS/contract运行与人工兼容性签署 |
| `DEV-CICD-003` | `pending` | 本批没有新服务部署 | Dev权限/写回/页面smoke，Production授权与回退 |
| `DEV-CICD-004` | `in_progress` | Apple 1.1.0 distribution仅历史状态，非本批代码验收 | 目标SHA/产物/上传回执、指定真机安装与系统行为 |
| `DEV-TRK-002` | `pending` | 合成组件回归不算第二周 | 第二真实周次全链路及恢复/缓存/ETA对照 |
| `DEV-SPD-001` | `pending` | 未提升并发或改变生产模型策略 | 同源同质量基线上的并发/模型路由A/B |
| `DEV-SPD-002` | `in_progress` | #122 projector/critical path/slack/Weekly；#124实际producer spans | 真实代表片段到整周依赖/耗时/usage基线 |
| `DEV-SPD-003` | `in_progress` | #126crash；#130Stage0；#143/#144真实本地路径故障注入 | 完整canonical Stage0、真实2–3分钟/10分钟/历史整篇 |
| `DEV-SPD-004` | `in_progress` | #126crash；#143paid response恢复；既有L2/L3cache复用 | canonical逐组/单元恢复接线，真实不受影响调用/重合成均为0 |
| `DEV-SPD-005` | `in_progress` | #122冲突感知usage去重；#134决策开销；#143避免未知结果重付费 | 真实整周去重token、质量/成本/返工与A/B，无节省百分比 |
| `DEV-SPD-006` | `in_progress` | #123legacy controller；#125canonical/bounded；#127–134验证/预算 | canonical dispatch、生产decision/atomic admission、heartbeat/backpressure、迁移receipt |
| `DEV-LOCALE-001` | `in_progress` | 没有新母语者验收 | 五语核心界面/权限/错误/VoiceOver/长文本复核 |
| `DEV-USAGE-001` | `waiting_evidence` | 保留既有三维统计口径，无新真实读回 | 实体iPhone播放/关闭/撤回及跨端原始收据 |
| `DEV-EXP-001` | `in_progress` | 未新跑Gemini实验 | 独立实验素材/盲测，不成为生产额外审核门槛 |
| `DEV-EXP-002` | `pending` | 未新跑TTS challenger | 单独授权的实验与质量/成本比较 |
| `DEV-EXP-003` | `pending` | 未扩展Cloud Run/笔记/金句 | 明确范围与真实权限/部署/回放证据 |
| `DEV-EXP-004` | `pending` | 未运行新模型Harness A/B | 相同任务质量/状态/token基线及实验批准 |
| `DEV-CICD-005` | `pending` | 未迁移runner或增加凭据 | 先完成本机受控CD、恢复/权限/不可变大媒体的干净runner复现 |

## 后续门槛与执行顺序

先补 canonical durable dispatch、生产 bounded responder/atomic admission、stage-specific heartbeat与资源 backpressure、版本迁移收据及完整恢复。继续复用现有 jobs/locks/cache，不创建并行作业系统。私有审核后端及统一发布身份仍是独立未完成项。

完整 Stage0 后，按冻结设计先选择有授权和预算的2–3分钟真实片段，冻结 Source/policy/voice/approval身份，验证冷暖缓存与三语恢复；人工角色分别签署后再进入连续10分钟A/B及完整历史视频。最后还需第二个真实周次。代码、合成测试、历史人审、旧head审查和Apple distribution状态均不能替代这些门槛。

额外付费、凭据/权限扩展、真实对外内容发布须报告具体批准需求；本轮没有据此请求或执行。merge/auto-merge/production/App Store发布不在本轮授权内。

## 10:24 UTC 整合快照与原生本地验证补充

`649dc9081cb7227358cff9704b022d814328e905` 是独立 detached 本地 QA 快照：以 #144 为基础，组合 #132/#133/#135/#137/#138/#139/#142 的已审核独立修改，无文本冲突。它未 push、未 merge、未部署，不替代各原始 PR 的 review 或 exact-head CI。输入 SHA 与逐文件组合记录保存在本机 `evidence/stack-composition.json`，结果摘要在 `evidence/stack-validation-summary.json`；QA 工作区保持干净。

| 实际验证 | 结果与边界 |
|---|---|
| Root Python 两分片 | 1,947 项，6 skipped；1,941 实际通过。首轮 20 项受 sandbox 的进程检查/loopback 限制，仅这 20 项授权重跑后全部通过，原失败日志保留。 |
| Web / Feedback API / Dubbing Python | 280 / 61 / 343 通过。Dubbing 首轮 5 项 loopback 权限错误，授权重跑后通过。 |
| Swift Core | 59 实际执行通过，6 条件式真实/冻结内容测试 skipped。 |
| Swift Infrastructure | 39 实际执行通过，5 真实站点 smoke skipped。 |
| 现有 iOS 27.0 模拟器 | PlaybackController 17 + AudioAlignmentController 20 = 37 通过；xcresult 中 0 failures / skips / runtime warnings。 |
| 现有 iOS 17.5 模拟器 | 同一 37 项通过；xcresult 中 0 failures / skips / runtime warnings。 |
| 四层 backend dry run | pass；外部下载、ASR、翻译、TTS、Firebase 调用均为 0。 |

两个模拟器按顺序执行，使用独立 DerivedData/result 目录；没有创建/抹除设备，没有签名、安装到物理设备或发布。合成音频、mock capture 和模拟系统中断不能替代真实 iPhone、Safari 拒绝后重试、麦克风/房间声学或锁屏耳机验收。GitHub draft `ios-validation` / `contract-validation` 仍 skipped；本地执行证据单列。

截至本补充，#144 `bbd88b55` 的 exact-head Python 两分片与 aggregate 已通过。#145 是文档改动，aggregate 通过而测试分片 skipped，不能拿该结果代表新 runtime 测试。

### 仍可实施与仍需外部证据

可独立继续：canonical 四层 durable adapter/dispatch、production bounded responder 的锁内 admission、stage-specific timeout/heartbeat、资源 backpressure、版本迁移 receipt，以及 shared catalog/page 与 text-only Release 的更多真实消费端契约覆盖。当前 shadow inspection 和注入式 responder 测试尚未完成这些能力。

外部门槛保持：受预算与批准约束的 2–3 分钟/10 分钟/完整历史视频运行、内容/完整听审 sign-off、第二个真实周、物理设备和现场盲测。没有关闭这些项或把现有 Apple 1.1.0 分发状态算作新代码验收。

## 10:57 UTC 消费端覆盖与交付边界补充

新增实际行为：#146 `dc4da99d646c9c494480166e16c1bdd17dbcf67c` 在 Web 请求 Release 前校验 catalog 头与页面结构，33 个共用 header/page 边界夹具同时经过实际 Swift decoder 和 Python schema。#147 `2eb7d1ba1c2ac757bb42da2c740dbd425648655b` 让新 fingerprint Worker 重新验证并复用最后一个公共索引的 CacheStorage 字节，限制单一条目与 32 MiB 大小；没有存储 PCM/查询特征。两者 exact-head Python 两分片与 aggregate 均通过，draft iOS/contract jobs 仍 skipped。

在本地 QA 快照 `ccdcf38f7afc3144d09ada4532b57111d7e0f0b7` 将这两批接到前述 `649dc908` 组合上后，无文本冲突；本次重跑相关 Web 327 项、Python 15 项以及 Swift 新增的 1 项参数化测试（33 个 case）通过。之前整套 Root Python/模拟器数目只属于 `649dc908`，不冒充在新快照上重新全跑。

#147 的实际 Chrome 154 临时 profile/loopback 验证通过：冷加载验证后持久化 → 索引路由返回 503 时，新 Worker 从实际 CacheStorage 读取并验证 → 故意损坏缓存后拒绝并移除。页面/模块路由保持可用，没有请求麦克风；不等于全浏览器断网、重启恢复、Safari 或物理设备验收。

### 哪些改动需要怎样交付

| 范围 | 实际改动 | 到达用户的必要步骤 |
|---|---|---|
| 后端/本地产线 | Python DAG/Weekly accounting、controller/shadow inspection、预算/作业/付费 cache 持久性、Source 准入、Layer 4 资产与快照保护 | 代码审查并按授权合入、在对应运行环境启用；这些后端改动本身不要求重编 iOS，但仍受合同兼容与阶段验证约束。 |
| Web 客户端 | catalog/Release 校验，现场诊断、索引预检、新录音点击、公共索引 cache | 审查并部署新的 Web 资产后才改变网站用户行为。本轮没有部署；Web 资产也不会替换已安装 App 内编译的 Swift Core。 |
| 原生 Swift 客户端 | #137 的 `Core/Sources/TongxingCore/MultilingualCatalog.swift`：允许 producer 的合法长 opaque packageId；校验 HTTP/device/venue acceptance 状态与证据；Dev candidate 不得声称设备/现场验收。#142/#146 继承此代码，并增加测试夹具。 | **需要新 iOS binary，并经过适用的构建、设备验收、审核及发布流程，才能到达已安装用户。不能把整批称为“纯后端优化，不需新 App Store 审核”。** 本轮未执行上传、审核提交或 App Store 发布。 |
| 测试/生成工具 | Swift 共用合同 fixtures/tests、fingerprint golden 生成器、CI 路由和模拟验证 | 单独测试或生成脚本不直接改变已安装 binary；测试通过也不等于用户已收到改动。 |

以该组合对 `dev f95346ab` 的文件差异核实，新增原生 production Swift 改动仅上述 Core decoder；App 播放控制器/Infrastructure 的 production Swift 文件未改。模拟器运行覆盖既有播放与对齐回归，而不是新的物理设备证据。Apple 1.1.0 Ready for Distribution 属于既有构建状态，不能证明这些新提交已包含、已安装或已验收。

麦克风/指纹/字幕对齐的真实现场阈值、15 秒协议、AGC/时钟、噪声/距离和人工盲测门槛均未降低。FIELD-02 仍缺完整离线包 readiness、浏览器重启/驱逐、Safari/iPhone 与现场证据；内容/听审及设备 sign-off 仍待真实执行。

## 12:04 UTC：固定 L2 执行、恢复与新增集成证据

- #148 `bf0a404ace346583391bafd6ef3907fb01b9bdbe`：L2 真实 producer 的 Source/准入、group 准备、缓存验证、语义验证与 evidence 汇合均计入 deterministic leaf；不是只统计模型调用。#149 `b0f2b0bfb60c4353b692a84510c80f2e24b2fca3` 将真实 package validator 与现有 durable job receipts 联合检查，保留 unknown outcome、逐语隔离及只读证据。
- #150 `f66cdf641132cc678678f06bf17f222ec7f2d410`：显式 opt-in 固定 L2 controller/worker，既有 admission/output locks、固定 Astra→Sol、pinned plugin、每 run 一个 locale job、组内原 1–3 workers；每个模型调用前重验 Source/config/code。只生成 human-pending candidate，不做 TTS、页面或发布。三语合成成功路径与真实空 key 双进程/崩溃测试通过；282 项 Stage0 组件与模拟通过。
- #152 `386c27aaad9506a3aa7f97bc3a7f8a9c2d154cdd`：已有有效 candidate 但 worker 无最终成功状态时，显式按当前 revision 对账。原 request/state/log 不变；独立不可变收据与当前 validator 决定 canonical `artifact_reconciled`，不会把原命令写成 succeeded。15 项新回归、47 项相关测试、297 项 Stage0 组件与模拟通过。缺候选/未知付费结果、跨版本和 group repair 仍未解决。
- #151 `ed52a2bd00414c089925835c50fe53f7285b9b8b`：Web 现有 10 秒采集与自动恢复共享 15 秒占麦预算；启动计入预算、不足完整窗口拒绝、迟到缓冲拒绝。228 项 Web、20 项打包/部署保护通过；9 项新预算测试在旧实现全部失败。Chrome 154 合成输入运行真实 AudioWorklet，连续 10 秒 PCM 成功，短预算拒绝且两个流/contexts 清理；观察到约 5ms timer 调度超限，明确没有硬实时保证。没有物理麦克风/Safari 证据或连续 10→15 秒新协议。
- #153 `1b0f0af4c0520b8f76492c2c755d3a16566886e8`：补齐 3 个 source-monitor 测试遗漏的 YouTube/yt-dlp fallback mocks，加禁止未注入 extractor 的 guard；26 项测试离线通过。只改测试，生产采源行为不变。
- #154 `77eebd9139b2bef67392d644cbd2a9b042afb9f0`：27-case 纯文字 Release 共用矩阵，分别验证 schema、原生页面阅读与 Web 音频能力。三语 v1 同一 release 字节经实际 catalog producer 验证，无音频输出；v2 decoder 支持不冒充 v1 producer 支持。13 项 Python、324 项 Web、Swift Core 实际执行 61 项通过（67 reported，6 条件 smoke skipped）。只新增 fixtures/tests，未新增 production Swift 行为。

截至本检查点，#148–153 exact-head Python 两分片与 aggregate 均已核验 SUCCESS；#154 刚提交，CI 仍待核验。所有 draft 的 iOS/contract-validation 仍 skipped，native-client 仅路由汇总。父线程独立审查已确认至 #149；不能把这个旧审查范围延伸成 #150–154 已独立通过。

新本地集成快照 `410482d2f676dc11b7fbe54e44beea95254db6ef` 在前述 `ccdcf38f` 上组合 #148–151，零文本冲突；282 项 Stage0 组件、后端模拟及 336 项 Web 通过。它尚未包括 #152–154；更早 649dc908 的整套 Root Python 和两个模拟器各 37 项结果仍仅绑定原快照。本轮没有新 App/Infrastructure production Swift 改动，原生交付边界继续遵守上表。

### 仍可本地继续的实际工作

- L2 已完成付费缓存、但 evidence/candidate 尚未落盘的确定性恢复；必须避免重发未知请求。部分失败 group 的新 revision/repair 接线、完整跨进程 DAG/usage 仍欠缺。
- 固定 Layer 1/3/4 执行适配器、stage heartbeat/no-progress timeout、跨 run 资源限额、生产 bounded decision runner 与锁内 action admission；已有 reader/planner 不等于这些已交付。
- E6 videoDelivery/其他消费边界、已交付分支组合验证及最新 SHA CI/审查；FIELD 连续采集协议、完整离线包 readiness、生命周期/路由的本地故障注入。

### 仍需外部证据或明确运行授权

完整 canonical Stage0 尚未完成，stage1PromotionAllowed=false。批准/预算绑定的短片段→10分钟→完整历史视频→第二个真实周、工程/内容/发布/兼容/性能签字仍缺；没有用本地模拟签字。人工翻译审核、整篇1x听审、声音授权、物理 iPhone/Safari/耳机/锁屏/现场盲测与误跳/字幕误差门槛保持原要求。尚未执行付费验证、merge、Web部署、App Store构建上传或发布。
