# 同片段三语试听 · 开发候选

2026-10-01：修复 iOS 试听没有暂停的缺陷，并统一 iOS／Firebase 的内容与操作顺序。网页适配状态为 `required`，已完成并发布 Firebase Dev；Production 保留本地同内容候选。本轮尚未上传新的 TestFlight 包。

## 展示与操作

按讲员展开：英文原声 → 同片段视频 → 中文／한국어／Español → 所选语言的一条合成音频 → 折叠的英文与译文 → 来源与审核提示。三语文稿都有必要保留，便于核对意义，但每次只展开当前语言，避免三份全文堆叠。

播放按钮变为暂停；再次播放从暂停位置继续。更换讲员、语言或收起 Demo 会停播，不自动开始下一条。音频复用唯一 `PlaybackController`，没有独立音频播放器或试听历史。短视频从 Firebase Dev 同源地址取得，经完整字节与哈希校验后缓存，再由 App 内系统视频控件播放／暂停及拖动进度；首次播放需要下载整个短片，不跳到外部视频页面。视频展示期间主播放器的系统播放命令也被阻止，关闭后保持暂停。

文件下载、播放器准备和音频会话错误都有文字提示；取消下载或准备中的试听不会迟到自动播放。More 的视频呈现由父层容器持有，不挂在可复用的 Form 行上。大字号时音频时间分行，语言选择保持可点击。

## 共用内容契约

两个客户端优先读取同源 `/voice-demos/speaker-clips-v2/catalog.json`，schema 为 `sermon-speaker-clip-demo-catalog-v2`。六讲员、十八三语样音，各讲员包含一个 `clipId`、英语文本 SHA-256、当前原视频区间及英文 MP3／同片段 MP4。每条译文及合成音频绑定相同英文文本与片段；播放前校验媒体字节数和 SHA-256。源音频／视频时长与区间容差最多 0.5 秒，音频上限 5 MB、视频 20 MB。

只有新目录 HTTP 404 才回退旧目录；无效绑定、坏哈希或其他 HTTP 错误不能静默退回。旧版文稿与原声并非同一片段，明确标为独立样音，不提供虚构的匹配视频。旧 Dev 四语目录只显示中文、韩语、西班牙语；不改变旧目录的审核证据。

候选固定文稿见 [speaker-clip-demo-scripts-v2.json](../../experiments/sermon-dubbing-poc/speaker-clip-demo-scripts-v2.json)。当前媒体在被忽略的 `artifacts/speaker-clips-v2/20261001/public/voice-demos/speaker-clips-v2/`：6 英文 MP3、6 视频、18 合成 MP3，共 8,997,619 字节。Catalog SHA：`ea3723eb3f10003db06d09fa81eed473fac17aaa3b8ec32bea29cfee04de25a2`。

Eric 原公开视频后来剪辑过；当前匹配区间为 1148.40–1161.36 秒，历史归档区间 1751.20–1764.16 秒作为独立 provenance 保留。六位讲员的原声与视频音轨机器包络比对均通过，不能只靠旧时间点推算。英文仍标 `machine_screening_only`，译文经机器语义检查；新样音 `humanListeningStatus=pending`，人工翻译确认、听感确认和音频 ASR 筛查尚未执行。共享术语表中的书卷名称规则已核对，未发现将普通书卷名称误扩写为系列标题。旧音色审批不批准这些新片段；本轮不重跑正式证道四层生产。

## 验证与发布边界

- iPhone Duo／iOS 27.1 模拟器：目录、播放暂停、提前暂停防迟到播放、视频互斥、证道书签不被试听覆盖及 UI 交互，共 17 个定向测试通过；1 个既有 live 检查未开启而跳过，不能计为通过。两个成功结果均无 runtime warning。
- 实际目录经 SwiftUI 解码并生成浅色、深色、大字号 PNG；静态渲染不证明真实讲员音频的听感。UI 自动化音／视频为标明的静音、黑色夹具。
- 内容 producer：8 个测试通过；18 WAV 哈希、24 音频与 6 视频完整解码通过，六份生成清单身份已核验。
- Web：16 项 Node、8 项 staging、23 项 UI 包装／部署白名单守护测试通过。Chrome 本地真实 Eric 原声／三语合成／视频已验证播放暂停；两环境本地候选的 Catalog 和 30 个媒体文件相同。
- Firebase Dev：`765122c66333a3ad` 已发布，36 个新增／替换文件全部线上 raw SHA／字节与 MIME 核验通过，其中 30 个媒体。303 个旧路径完整保留，301 个旧 Hosting gzip hash 不变，只替换 `/voice-demo.css` 与 `/voice-samples.mjs`；34 个新增文件，总计 337。当前 Dev 使用 production reader，按真实入口应用 `voice-samples.mjs`；页面与 4 条旧视频重定向配置保留。回退版本为 `c2bb5dff5ef8d34b`。服务器返回配置仅对象字段顺序变化，递归排序对象且保留数组顺序后语义完全一致；诊断和同版本恢复收据保留，不创建第二个版本。
- 真实网络 iOS：新增两个显式开启的 Live Dev 测试通过，0 跳过、0 失败、xcresult runtime warnings 为空。原声进度前进到 00:04 后暂停；App 内视频显示真实 Eric 画面，关闭后保持暂停。另一个 hosted AVPlayer 测试验证同一视频网络哈希、854×480 解码帧、12.9667 秒时长、播放超过一秒及暂停后时间差为零。结果：`artifacts/tongxing-ios/2026-10-01/voice-demo/live-dev-test.xcresult`；PNG 和公开测试收据在 `live-dev-attachments/`。
- 完整证据保存在 `artifacts/speaker-clips-v2/20261001/provenance/candidate-evidence.json`、`artifacts/tongxing-ios/2026-10-01/voice-demo/` 和 `artifacts/voice-demo-web-20261001/`。最终三种静态预览及目录 SHA 在 `artifacts/tongxing-ios/2026-10-01/preview/20261001T123323-5175cfa5/manifest.json`。

本轮 Firebase Dev 已上线：[Dev 试听入口](https://ai-for-god-sermon-audio-dev.web.app/)。正式 Firebase、Beta 1.2.0(47) 与正式 App 尚未纳入这次修复。Hosting 的六段视频对 12 次 Range 请求均返回完整 200，而非 206；本实现先完整校验并缓存短片，随后在原生／浏览器本地媒体中定位，不宣称服务器已支持分段流播。HTTP 和发布证据在 `artifacts/voice-demo-web-20261001/dev-rest-overlay/`（`http-receipt.json`、`release-receipt.json`、完整旧/新文件清单）。晋升时按 [Beta 流程](BETA-PROMOTION.zh.md) 冻结本轮源码、同一份媒体清单与部署目标，重新记录新 build 号；不要改写已上传的 47 记录。新样音的人审状态保留 pending，不以构建／页面播放成功替代人工听审或真机验收。

## 可复现命令

```sh
python3 -m unittest discover -s tests -p test_speaker_clip_demos.py
node --test experiments/sermon-dubbing-poc/web/speaker-clip-demos.test.mjs
python3 apps/tongxing-ios/scripts/preview.py --files VoiceDemoSection.swift \
  --voice-demo-catalog artifacts/speaker-clips-v2/20261001/public/voice-demos/speaker-clips-v2/catalog.json \
  --variants light,dark,dark-large --simulator "$TONGXING_SIMULATOR_UDID"
python3 scripts/stage_speaker_clip_demo_ui.py --help
```

素材 producer 和 Hosting overlay 的输入、缓存身份及不可覆盖规则分别由 `scripts/render_speaker_clip_demos.py`、`scripts/build_speaker_clip_demos.py` 和 `scripts/stage_speaker_clip_demo_ui.py` 实现。模型／媒体产物不提交 Git；overlay 命令只生成新的候选目录，不部署。
