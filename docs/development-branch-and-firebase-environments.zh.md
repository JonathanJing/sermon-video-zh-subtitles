# Dev 分支与 Firebase 环境隔离

状态：本文件定义日常开发进入生产 `main` 前的晋升路径。它不代表某次 App、Firebase 或现场验收已经完成。

## Git 分支门禁

正常路径固定为：

```text
feature/* 或 codex/*
        │ Pull Request
        ▼
       dev ── Python／生产合同／Firebase 合同／iOS 构建验证
        │ Pull Request（只允许此来源）
        ▼
       main ── 已发布生产基线
```

- `main` 和 `dev` 都禁止直接 push、force-push 和删除；管理员也遵守保护规则。
- 两个分支的 PR 都必须基于目标分支最新提交，并通过 `unittest` 和 `native-client`。
- `main` 额外要求 `promotion-policy`，普通功能只能由 `dev` 晋升。紧急修复也先合并到 `dev`；若确需例外，必须显式修改保护规则并留下原因，不能静默绕过。
- `main` 要求线性历史并使用 squash merge。`dev` 不要求线性历史：普通功能 PR 仍使用 squash／rebase，但每次生产晋升后必须通过一个从最新 `dev` 建立的临时 `sync/*` 分支合并 `main`，再用受检查的 `sync/* → dev` PR 把新的 `main` tip 纳入 `dev` 祖先链。
- 当前仓库为单维护者流程，因此 PR 本身是强制门禁，但批准人数为 0；CI、对话解决和 `main` 线性历史仍是硬条件。增加第二位维护者后，应把批准人数提升为 1。
- 合并到 `main` 只证明代码门禁通过；Firebase HTTP、iOS/TestFlight、设备和现场验收继续分别留证。

### 晋升后的回同步

1. 三项 required checks 通过后，将 `dev → main` PR squash merge。
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
| Production | `main` | 现有 `ai-for-god` | `ai-for-god-sermon-audio.web.app` | 已批准的周次发布资产 |

2026-09-21 已建立 Dev Firebase project `ai-for-god-sermon-audio-dev`（project number `548454657719`），默认 Hosting site 为 `https://ai-for-god-sermon-audio-dev.web.app`。这只证明环境资源存在；多语言 fixture、HTTP 验证、iOS 设备验收和现场验收仍须分别留证。

执行边界：

- 当前 `deploy_firebase.py` 已强制显式传入 `--project` 和 `--site`，并先校验完整发布清单；继续保留这个 fail-closed 接口。
- Dev 和 Production 使用不同的 project ID、site ID、短期凭据／服务身份和预算告警。不要在仓库提交 `.firebaserc`、token 或 service-account key。
- `dev` 自动部署只能指向 Dev project；Production 部署只接受 `main` 的已验证 commit，并保留现有人工发布授权、HTTP 哈希和 MP3 Range 验证。
- 多语言功能先在 Dev App 验证 locale 选择、资源缺失降级、音频切换和旧中文周次回归；通过不等于自动发布 Production。

## 建立 Dev App 的接受标准

1. 新 Firebase project 和独立 Hosting site 已创建，并标记为非生产环境。
2. 使用一个不含私人数据的多语言 fixture 完成部署，记录 project、site、Git SHA 和 build-report SHA-256。
3. 核验 `weekly.json`、所有发布文件哈希、MP3 `Range: 206`、安全响应头及未知／私有路径 `404`。
4. Web 和 iOS 都验证中文生产基线没有回归；韩语、西班牙语和越南语只显示实际存在且具有显式审核状态的资源。
5. Dev 验收收据通过后才创建 `dev -> main` PR；Production 发布仍生成独立 HTTP、设备和现场证据。
