# 同行项目 CI/CD 执行 Backlog

更新：2026-09-29。顶层优先级、状态和稳定 ID 以 [Dev 统一 Backlog](backlog.zh.md) 为准；本文展开 `DEV-CICD-*` 的工作边界与验收，不记录某一周的实时完成状态。

## 目标与现有基线

本项目有四条不同交付线。CI 负责自动检查代码与确定性生产合同；CD 负责从选定候选部署到指定环境并留下可复核的结果。内容人审、TestFlight 安装、Web／iOS 设备和礼拜现场各有独立收据。

| 交付线 | 何时运行 CI | CD 的目标与独立验收 |
|---|---|---|
| iOS App 代码 | 原生代码、共享目录／Release schema 或客户端行为改变的 PR | 按需制作并上传安装包；TestFlight 真机与 App Store 状态分别记录。已有 App 支持的每周内容更新不重新发版。 |
| Firebase Web 页面 | 页面、路由、静态资源、目录 adapter 或 Hosting 配置改变的 PR | 先在独立 Dev 项目验证页面／目录／播放，再以绑定代码和线上基线的候选部署 Production；逐文件 HTTP 与实际页面操作分开。 |
| 后端 API 与 producer 代码 | 反馈／会话 API、权限、Layer 1–4 producer 或共享合同改变的 PR | 部署实际改变的服务并验证授权、写入／读回和失败路径；每周生产入口仍消费经审候选，不把代码合并当作内容发布。 |
| 每周证道内容 | producer 变动时跑快速模拟流程；每次周产检查来源、包、hash、审核和文件清单 | 按当周发布计划，将已批准包追加到 Dev／Production；记录线上资产、Web、同版本 iOS 设备及现场的各自结果。 |

当前 [Python CI](../.github/workflows/python-tests.yml) 已包含 Web 和反馈 API 测试，[iOS CI](../.github/workflows/tongxing-ios.yml) 会按原生／合同改动选择 Swift 或模拟器检查；固定 `unittest`／`native-client` 检查仍须返回结果。[分支与环境流程](development-branch-and-firebase-environments.zh.md)规定 `dev`／`main` 分离，`main` push 不自动部署，约 700 MB 的内容候选使用本机受控 CD。已有 [`run_multilingual_cd.py`](../scripts/run_multilingual_cd.py) 要求显式 `--execute`、代码和候选 hash，但其当前 schema 范围不能直接证明新 v3 周更已发布。

## P0：下一次完整周产需要的交付边界

### `DEV-CICD-001`：发布身份与收据

依赖：`DEV-E2E-001` 的快速演练、`DEV-L4-001` 的 Dev 更新、相应周次的 Layer 1–3 审核，以及正式 v3 发行入口。此项串起证据，不替它们生产文字、音频或客户端代码。

- [ ] 统一发布计划至少记录 `environment`、Firebase project/site 或后端服务、代码 SHA、当前线上基线、变更清单及回退指针。内容发布另绑定 `pageId`、各 locale 上游包与批准收据 hash、候选清单 hash、预期新增／替换／保留文件；纯功能部署明确记录内容未变。机密、私有媒体和本机绝对路径不进入公开包。
- [ ] 预检拒绝错项目／站点、旧代码提交、过期或变化的线上基线、未批准的正式资产、候选清单外文件、意外覆盖历史页，以及同站点并发发布。仅在原绑定改变时重取受影响审核，不重复已有效的人审。
- [ ] 发布先处理不可变资产、逐语言 Release，最后更新可变 catalog；发布后校验公开文件 GET／SHA、音频 Range、语言深链。HTTP、Web 播放、iOS 同版本设备和现场状态分别写入收据；未测的保持 `not_run`。
- [ ] 用一个有效 fixture 和错误环境、旧基线、缺失审核三个失败变体演练；正确候选到 `published_http_verified`，失败变体均阻断。保留旧 catalog／完整快照的恢复入口，回退后仍重新核验。

## P1：把日常开发的检查与交付做顺

### `DEV-CICD-002`：按改动运行 CI

依赖：现有 `DEV-GOV-001` 分支门禁；该项只调整测试选择与合同覆盖，不改动保护分支的检查名。

- [ ] 建立路径到测试的矩阵：iOS／Swift、Firebase Web、反馈与会话 API、Layer 1–4 producer、共享 schema／catalog。未知路径或工作流自身改动走完整检查；纯文档仍完成结构、链接与固定 required checks。
- [ ] 共享 catalog、Release、播放 URL 或审核声明变动时，用同一 fixture 验证 Web adapter 与 iOS decoder；覆盖旧版本兼容、缺资源和错 hash 的拒绝路径。
- [ ] PR CI 使用短小、确定性的 fixture；付费模型、整篇 TTS、真实媒体下载、生产凭据和部署不在每次 PR 上重复运行。producer 改动至少运行模拟链接到 Layer 1–4 的快速 `DEV-E2E-001`，明确它只证明模拟路径。
- [ ] 用 iOS-only、Web-only、API-only、共享合同、producer-only、docs-only 和未知路径的测试 PR／等价事件矩阵证明路由；检查失败报告保留提交 SHA、执行／跳过项和具体失败，不以通知邮件代替日志诊断。

2026-09-30 路由回归补充（`DEV-CICD-002` 仍为 `in_progress`）：iOS workflow 的共享路径扩展到 catalog v3／Release v2 及其后续版本、legacy weekly catalog family、实际 v3／v2 producer 和 Web 合同 adapter。Git diff 禁用 rename 合并，删除或移动旧合同仍触发检查。真实 Git fixture 和工作流内原脚本覆盖已知路径、混合改动、删除／重命名、手动运行及 draft／失败／取消／跳过汇总；未知 scope 拒绝通过。 后续补充保守 fallback：未知顶层路径、未列入矩阵的文件类型、所有 `.github/` 输入和空 diff 选择 `native`，混合改动取更广范围；使用 `--no-renames` 保留移走文件的原路径。已明确的 backend／producer／Web／API 源码及纯文档路径可保留 `none`，既有共享合同优先走 `contract`。`native` 在非 draft 的 dev PR 上运行 Core／storage 合同检查，在 main PR 上运行模拟器检查；draft 仍跳过，不声称自动验收。Python 的非文档改动已运行完整两 shard／Web／API／producer 模拟套件，本批不改变其范围。19 项路由／文档 gate／分片测试通过；未来新增表面须补矩阵，不把该路径分类当语义兼容证明。

本批只修正测试选择，不修改 draft 的 macOS 跳过策略、required check 名称、客户端协议或发布行为。`native-client` 成功且 `contract-validation`／`ios-validation` skipped 仍不是 Swift／模拟器通过。未知路径走全检查的策略、同一跨端合同 fixture 和真实设备验收仍待后续，不能据本批关闭矩阵全部验收。

### `DEV-CICD-003`：页面与后端功能交付

依赖：`DEV-CICD-002`、独立 Dev 项目／服务与 `DEV-CICD-001` 的发布身份。按 Hosting 页面、反馈／会话 API、Cloud Run 服务各自实际范围实施，不让一个成功的健康检查替另一服务的业务验证。

- [ ] 页面改动在 Dev 用合成数据检查首页、深链、目录读取、语言／音轨切换、反馈入口及旧周回归；后端改动用测试身份完成授权、请求、实际写入与读回及拒绝路径，记录可清理的测试数据。
- [ ] Production 入口只接收对应 `main` 代码版本、目标配置、Dev 验收和最新线上基线；部署后分别保存 Hosting HTTP／页面结果与 API 业务 smoke。反馈 API 的路由 `400` 只能证明输入校验，不当作会话闭环。
- [ ] 保存 Hosting 上一完整版本和后端上一可用 revision／配置，定向演练失败回退及回退后读回；同站点发布串行。Cloud Run 或其他后端没有实际部署时，状态保持未部署。

### `DEV-CICD-004`：iOS 安装包交付

依赖：`DEV-CICD-002` 的原生／合同检查及 `DEV-IOS-001` 的实际客户端能力；每周仅内容变化时不触发新包。

- [ ] 候选记录源代码 SHA、App 版本／build、Xcode／签名身份、构建产物 hash、模拟器测试报告和上传回执；敏感签名材料不进入 Git 或 CI 日志。
- [ ] 上传 TestFlight 后读取 Apple 处理状态，再在指定真机安装同一 build 验证目录刷新、下载、离线、播放及相关系统表面。`uploaded`、`processed`、`installed_and_tested`、`App_Store_live` 分开记录。
- [ ] 只有新 schema、语言能力或播放器功能需要客户端更新时，才与周更内容建立最低兼容版本约束；旧 App 应有明确降级，不把网页播放当作原生验收。

## P2：运行位置的选择

### `DEV-CICD-005`：runner 迁移评估

现阶段不以 GitHub Actions 自动部署取代本机受控 CD。只有先解决以下约束，才考虑把已验证的执行入口迁到 runner：

- [ ] 大媒体候选的不可变存储与恢复、完整 hash、目标环境的短期凭据、批准收据、同站点串行与超时恢复，在干净 runner 上重现；不依赖本机 ignored `artifacts/` 路径。
- [ ] 对 Dev 和 Production 分别验证凭据范围、发布授权、预检、线上读回及回退。迁移前后使用同一候选和同一状态定义，不能把 runner 成功写成设备或现场通过。
- [ ] 若未来自动创建新的 Firebase project，首次 Hosting 部署前加入显式站点创建／存在性检查；现有固定 Dev／Production 站点无需因 2026-09-28 Firebase Hosting 站点按需创建通知而重建。

## 执行顺序与状态口径

1. 先完成 `DEV-E2E-001` 的模拟视频链接 → Layer 1–4 → Dev 测试页路径，和 `DEV-CICD-001` 的发布身份／预检；两者支撑下一次周产。
2. 再完善 `DEV-CICD-002` 的定向 CI，优先补共享 schema 的 Web／iOS 合同与后端 API 业务测试。保持现有固定检查名。
3. `DEV-CICD-003` 按实际服务逐一接入 Dev／Production smoke 与回退；`DEV-CICD-004` 在需要新 App build 时使用。
4. 有真实的候选、收据与恢复证据后再评估 `DEV-CICD-005`。CI 通过、代码合并、Dev HTTP、Production HTTP、设备与现场始终是不同状态。
