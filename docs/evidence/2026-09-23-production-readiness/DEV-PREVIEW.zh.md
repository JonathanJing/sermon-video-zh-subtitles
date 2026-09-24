# 多语言 Production 阅读器的 Firebase Dev 预演

范围：用 2026-09-20 已审 2:58 三语样片预演未来周更网页，同时保留 Dev 六句实验页和 Production 已公开的九周中文旧页。此发行不包含 9 月 27 日整篇，也不批准 Production 部署、原生 iOS 或现场验收。

## 构建合同

`scripts/multilingual_dev_preview.py` 接受两个完整快照：

1. `assemble_multilingual_hosting.py --production-reader --promote-home` 生成的已验证 Production 布局候选；样片 stage、v2 catalog、三语 release、资源及 Firebase 配置 SHA 都由上游冻结。这里先复核该候选的 `firebase.json`／`.firebaserc` 哈希和目标站点，再读取它的公开目录，不调用 Production deploy。
2. 上一次完整 Dev Hosting 发布的 `public` 目录。构建器要求旧正式样片 catalog 与候选逐字节相同；所有同名文件仅允许 `index.html`、`app.js`、`formal-dev-adapter.mjs`、`weekly.json` 四处不同。旧 POC 的 18 条音频及其他文件逐个保留；四个冲突文件存为 `dev-poc.*` 别名，独立 `/dev-poc.html` 保留机器 POC 标签与六句默认页。

候选首页为正式阅读器的 Dev 预览，显示本周新整篇未发布。旧中文九周在 `/legacy-reader.html`；该预览的 Dev project 没有旧版反馈 API，因此 `engagement.json.enabled=false`，不显示反馈或匿名统计入口。Prod 原文件及发行包不改。`firebase.json` 固定 Dev Hosting site `ai-for-god-sermon-audio-dev`，没有 `/api/**` 转发，且添加 `noindex`。

## 执行

使用受控的完整归档路径代入绝对路径，不从干净 Git checkout 假设媒体存在：

```bash
.venv/bin/python scripts/multilingual_dev_preview.py build \
  --production-candidate /absolute/path/to/reviewed-production-layout-candidate \
  --dev-base-public /absolute/path/to/complete-current-dev-public \
  --out /absolute/path/to/new-dev-preview-candidate

.venv/bin/python scripts/multilingual_dev_preview.py preflight \
  --candidate /absolute/path/to/new-dev-preview-candidate \
  --out /absolute/path/to/dev-preflight.json

.venv/bin/python scripts/multilingual_dev_preview.py deploy \
  --candidate /absolute/path/to/new-dev-preview-candidate \
  --preflight /absolute/path/to/dev-preflight.json \
  --out /absolute/path/to/deployment.json --execute

.venv/bin/python scripts/multilingual_dev_preview.py verify \
  --candidate /absolute/path/to/new-dev-preview-candidate \
  --out /absolute/path/to/http-verification.json
```

部署器要求不超过 30 分钟、覆盖旧 Dev 每个文件的线上 GET/大小/SHA 预检；发布仅指向 Dev 项目。发布后再次读取候选全部文件并复算线上 SHA，核对已知文件类型的 `Content-Type`、目录缓存，再查三条音轨 Range 206 和三语深链。浏览器点击播放、旧页下载、手机/设备与现场需单独记录。

## 本轮构建与本地核对

- 源 Production 布局候选报告 SHA-256：`eea22c48d94e4976b3fafd44313bd3233248afc7f2e9eb16c6282dc7efe3947a`；最终 Dev 预览报告 SHA-256：`03dd49385e8d3bb18f96b52d795e9b031cfca7340f3d9bc32621af95df2bddda`。
- 候选 121 个文件、708,820,221 字节；上次 Dev 公开目录 59 个文件，逐文件线上预检已通过。原 Dev POC 路由跳回正式样片的问题在隔离入口修正；韩语界面与西语内容独立、中文内容切换、六句 POC 默认页和旧九周及 PDF/MP3/SRT 入口均在 Hosting 模拟器实际打开。Dev 预览旧页的反馈与匿名统计入口已关闭。
- `tests.test_multilingual_dev_preview` 与相邻 Hosting 测试共 19 项通过；`node --check` 和 `git diff --check` 通过。模拟器的本地音频 Range 行为不能代替 Firebase 线上 206 验证。

## Firebase Dev 发布与线上核验

- 2026-09-24 01:17 UTC 发布到 [`ai-for-god-sermon-audio-dev.web.app`](https://ai-for-god-sermon-audio-dev.web.app/)；项目与 Hosting site 均为 `ai-for-god-sermon-audio-dev`。部署收据 SHA-256：`0410a1241235bf98c828793af9e98eac075583b906e947e66fbcecb3fdbdf1d2`。
- 01:28 UTC 的最终独立 HTTP 收据状态为 `pass`，SHA-256：`760ac9b74ad97f60abe0679cf7923d824e2a957c0ee7342a089df0ee2240e017`。线上 121 个文件逐一 GET、核对大小、SHA 和对应 `Content-Type`；目录 `no-store`，中、韩、西三条 WAV 的 Range 请求均为 206；三种深链均为 200。该收据仍把浏览器、设备、现场验收标为 `not_run`，浏览器观察另行记录。
- 真实 Dev 浏览器已打开[中文](https://ai-for-god-sermon-audio-dev.web.app/pages/2026-09-20-revelation-clip/zh-Hans)、[韩语](https://ai-for-god-sermon-audio-dev.web.app/pages/2026-09-20-revelation-clip/ko)、[西语](https://ai-for-god-sermon-audio-dev.web.app/pages/2026-09-20-revelation-clip/es)页面，分别见 45、44、44 组和 2:58 音轨，点击播放后时间向前推进；韩语界面下西语内容、音轨与 URL 保持西语。旧 `/dev-poc.html` 仍显示六句机器实验，旧 `/legacy-reader.html` 仍显示九周中文及 PDF/MP3/SRT 下载入口；旧 `/?week=<page-id>` 在线转入旧阅读器，新样片 `/?week=2026-09-20-revelation-clip` 进入三语阅读器。浏览器点击仅证明加载与短时播放，不代表重新完成全文听审、实体手机或现场验收。

完整候选、旧 Dev 快照、部署与最终 HTTP 收据保存在本机忽略目录 `artifacts/multilingual-dev-preview/2026-09-23-production-layout/`；最终收据文件为 `http-verification-all-content-types.json`，浏览器观察记录独立存为其中的 `browser-verification.json`。下一周发布需重新生成 Production 布局候选，并从当时完整的线上 Dev 版本建立新快照。旧发行目录及新候选都是 ignored media；不要把 708 MB 媒体提交 Git。
