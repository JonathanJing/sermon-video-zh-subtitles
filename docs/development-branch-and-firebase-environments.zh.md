# Dev 分支与 Firebase 环境隔离

状态：本文件定义日常开发进入生产 `main` 前的晋升路径。它不代表某次 App、Firebase 或现场验收已经完成。

## Git 分支门禁

正常路径固定为：

```text
feature/* 或 codex/*
        │ Pull Request
        ▼
       dev ── 持续集成，新的后端与前端迭代继续进入这里
        │ 每周冻结一次代码候选
        ▼
 release/YYYY-Www ── 只含已进入 dev 的变更
        │ Pull Request；短发布窗口也可直接 dev → main
        ▼
       main ── 可部署的代码基线；内容发布仍需独立收据
```

- `main` 和 `dev` 都禁止直接 push、force-push 和删除；管理员也遵守保护规则。
- 两个分支的 PR 都必须基于目标分支最新提交，并通过 `unittest` 和 `native-client`。`native-client` 是固定名称的必需检查：普通后端／Web／周次变更不启动 Mac；共享发布合同与进入 `dev` 的原生代码运行原生包测试；只有晋升到 `main` 的原生代码变更或显式 `workflow_dispatch` 才运行 iOS 模拟器构建和测试。草稿转为 Ready for review 会重新触发检查；正式代码候选的完整 iOS 验证必须对应待晋升的最新提交。
- `main` 额外要求 `promotion-policy`。它只接收同仓库 `dev` 或 `release/YYYY-Www`；release 分支须包含当前 main，且相对 main 的每个代码补丁已进入 dev。需修复候选时先把变更并入 dev，再带入 release 分支；不得直接在 release 分支加入未审补丁。短发布窗口可继续使用 `dev → main`，不要长期打开一个随 dev 每次提交更新的晋升 PR。
- `main` 要求线性历史并使用 squash merge。`dev` 不要求线性历史：普通功能 PR 仍使用 squash／rebase，但每次生产晋升后必须通过一个从最新 `dev` 建立的临时 `sync/*` 分支合并 `main`，再用受检查的 `sync/* → dev` PR 把新的 `main` tip 纳入 `dev` 祖先链。
- 当前仓库为单维护者流程，因此 PR 本身是强制门禁，但批准人数为 0；CI、对话解决和 `main` 线性历史仍是硬条件。增加第二位维护者后，应把批准人数提升为 1。
- 合并到 `main` 只证明代码门禁通过；每周内容无需为了换 catalog 而制造 Git 提交或重新构建 iOS。Firebase HTTP、iOS/TestFlight、设备和现场验收继续分别留证。

### 晋升后的回同步

1. 三项 required checks 通过后，将 `dev → main` 或 `release/YYYY-Www → main` PR squash merge。release 分支冻结后 dev 可继续下一周开发；若 release 有问题，先在 dev 修复再更新候选。
2. 从最新 `dev` 创建临时 `sync/main-to-dev-<date>` 分支，在该临时分支 merge 最新 `main`；禁止直接把 `main` 作为回同步 PR 的 head，因为 strict/up-to-date 要求 head 已包含当前 `dev` tip。
3. 创建 `sync/main-to-dev-<date> → dev` PR；它仍须通过 `unittest` 和 `native-client`。
4. 这条回同步 PR 使用 merge commit，不能 squash。merge commit 只用于把 production tip 纳入 `dev`，不承载新的功能修改；完成后删除临时 sync 分支。
5. 回同步完成后再从最新 `dev` 创建新的功能分支。

这一步解决长期分支的祖先关系：若 `main` squash 后不回同步，`main` 和 `dev` 会拥有内容等价但 SHA 不同的提交；下一轮在 strict/up-to-date 门禁下将需要 force-reset `dev`。本流程明确禁止这种重写历史的恢复方式。

## Firebase 必须分 Dev 与 Production

Firebase 官方建议每个开发环境使用独立 project。听译 App 应建立新的 Firebase project，例如 `ai-for-god-sermon-audio-dev`，而不是把 `dev` 构建发布到生产 project `ai-for-god` 的另一个 preview channel。独立 project 可以隔离 Hosting、Functions／Cloud Run rewrite、Auth、数据库、Analytics、IAM、配额和误删除风险。

| 环境 | Git 来源 | Firebase project | Hosting site | 数据 |
|---|---|---|---|---|
| Dev | `dev` | 新建 `ai-for-god-sermon-audio-dev` | 独立 `*-dev.web.app` | 合成／匿名测试数据，不复制私人生产数据 |
| Production | `main` | 现有 `ai-for-god-caption-dev` 项目中的独立 Hosting site | `ai-for-god-sermon-audio.web.app` | 已批准的周次发布资产 |

2026-09-21 已建立 Dev Firebase project `ai-for-god-sermon-audio-dev`（project number `548454657719`），默认 Hosting site 为 `https://ai-for-god-sermon-audio-dev.web.app`。同日先部署四语言 Web mock，再用 2026-09-20 证道的六个英文源句替换默认页面，完成英文 Layer 1 来源对照页，以及中文、韩语、西班牙语、越南语的 Layer 2 机器翻译候选、Eric Geiger 声音克隆 POC、估算字幕时间和独立路由。英文页使用同一 source window 的原始讲员音频和来源时间轴，不经过 Layer 2/3。根页面、各语言路由、目录、发布包、内容、脚本、样式和音频分别验证。

这次部署建立的是 Web 交互和 Dev Hosting 验证，不是 canonical 四层发布：`multilingual.json` 仍使用 `sermon-multilingual-demo-catalog-v1`，所有文字与音频均保持 `humanApproval=false`；越南语 ASR 相似度 `0.195652`，在 `0.85` 门线下明确显示 `requires_review`。正式 iOS Layer 4 reader 应继续拒绝把 demo catalog 解释成 `sermon-multilingual-catalog-v2`。人工文字审核、母语听审、真实时间对齐、iOS 设备和现场验收仍须分别留证。可复跑与晋升边界见[多语言片段 POC 固化流程](multilingual-fragment-poc-solidification.zh.md)。

执行边界：

- 当前 `deploy_firebase.py` 已强制显式传入 `--project` 和 `--site`，并先校验完整发布清单；继续保留这个 fail-closed 接口。
- Dev 和 Production 使用不同的 project ID、site ID、短期凭据／服务身份和预算告警。不要在仓库提交 `.firebaserc`、token 或 service-account key。
- 代码 PR 和每周内容发布分开。Firebase PR 预览如启用，只能使用独立 Dev project 的合成 fixture；正式 Dev 页面继续要求已审产物。预览渠道仍连接其所属项目的真实后端，不得用 Production project 预览未经审查的变更。
- 正式 Dev／Production 内容发布使用 `scripts/run_multilingual_cd.py` 的显式入口：先逐文件核对线上基线，随后部署并完成 HTTP/SHA、音轨 Range 与语言深链核验。`--execute` 只接受干净、与远端同 SHA 的 `dev`／`main` checkout，以及明确输入的代码 SHA 和候选报告 SHA。`main` push 本身不自动部署；签名 iOS 包／TestFlight 也只在原生 App 发版时单独构建。
- 发布收据、候选目录和媒体均保留在 ignored artifacts，不上传到 Git。GitHub Actions 目前负责代码门禁；约 700 MB 的内容候选使用本机受控 CD。未来若迁到 GitHub runner，必须先定义候选存储、凭据、环境审核和同站点串行部署，不能把本机路径写进云端工作流。
- 多语言功能先在 Dev App 验证 locale 选择、资源缺失降级、音频切换和旧中文周次回归；通过不等于自动发布 Production。

## 建立 Dev App 的接受标准

1. 新 Firebase project 和独立 Hosting site 已创建，并标记为非生产环境。
2. 使用一个不含私人数据的多语言 fixture 完成部署，记录 project、site、Git SHA 和 build-report SHA-256。
3. 核验 `weekly.json`、所有发布文件哈希、MP3 `Range: 206`、安全响应头及未知／私有路径 `404`。
4. Web 和 iOS 都验证中文生产基线没有回归；韩语、西班牙语和越南语只显示实际存在且具有显式审核状态的资源。
5. Dev 验收收据通过后才创建 `dev -> main` PR；Production 发布仍生成独立 HTTP、设备和现场证据。

## 每周内容与代码发布顺序

1. 功能 PR 进入 `dev`；原生代码改动先跑包测试，周迭代晋升到 `main` 时才跑完整 Mac 模拟器验证，也可显式手动触发。周次文字、配音和媒体文件放在忽略目录，不由 Git push 自动发行。
2. 从 `dev` 冻结代码候选；需要继续开发时切 `release/YYYY-Www`。完成 `main` 晋升后，在干净的 `main` checkout 上构建 Production 候选。
3. 已审三语 Stage 用 `assemble_multilingual_hosting.py --production-reader` 叠加到完整旧站点；默认保留旧中文首页并加三语入口。若同周也有旧中文周次更新，先按 `weekly_release.py prepare` 得到完整 legacy release，再用 `refresh_multilingual_hosting_with_legacy.py` 把它合入已经发布且通过 HTTP 核验的多语言候选。两种产物都只写新目录。
4. 记录候选 `build-report.json` SHA 与 `main` SHA。执行 `run_multilingual_cd.py --mode production --candidate <候选> --out <新收据目录>` 先生成预检与计划；核对目标后用新的收据目录加 `--execute --expected-commit <main SHA> --expected-build-report-sha256 <SHA>`。包含旧中文周次更新的候选，两次调用均加 `--legacy-release <同一已准备的发行>`；入口会先准备／部署反馈 API，保留其独立待核验状态。Dev 同理使用 `--mode dev` 和 `dev` SHA。发布后另做浏览器／设备验收。
5. 旧 `deploy_firebase.py` 若发现 Production 已有 v2 catalog，默认拒绝用 legacy-only 包覆盖；只有明确回退时才使用 `--allow-multilingual-rollback`。未来周更应走多语言叠加路径，保留旧 `weekly.json` 和所有已发布三语文件。

本流程的本地锁只协调同一台机器上的发布命令；Firebase Hosting 没有此处使用的原子 CAS。同站点发布窗口仍须避免来自其他机器或控制台的并发部署，预检超过 30 分钟必须重做。
