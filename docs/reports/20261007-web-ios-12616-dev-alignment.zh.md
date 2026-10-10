# Firebase Dev 网页对齐 iOS 1.26.16

2026-10-07，已发布到 [Firebase Dev](https://ai-for-god-sermon-audio-dev.web.app/)。

## 对齐基线与交付

- iOS：1.26.16 (57)，按 `BETA-RELEASE-1.26.16.zh.md` 的 IPA 冻结源码 `a1e64190f5af33104a3b8839562d8901955031bb` 核对；机器质检 v4 消费端未纳入此版本。
- 网页代码：`6fb595ac008c567ef599f144f24a32b0bb92c168`，分支 `codex/web-ios-12616-dev`，从 Dev 基线 `976eb2a7` 开始。
- Hosting：`sites/ai-for-god-sermon-audio-dev/versions/7f71393213c192eb`，发布完成 `2026-10-07T17:09:57.690246Z`。

网页现在提供带日期、讲员和类别的选篇列表；现场收听/字幕全文主导航；跟随播放、自由阅读、回当前句；独立完整文稿及英文对照；英文关键词定位；可收起的播放栏与集中定位工具；按界面语言显示并刷新内容类别。已有有效大纲、默想按原内容身份展示，缺失资源不生成替代文案。

离线能力覆盖已访问且成功缓存的文稿、大纲、默想和必要页面资源。音频仍需联网；原生锁屏、灵动岛、多窗口等不属于本次网页交付。网页只消费现有已发布内容，没有运行翻译、配音或新内容发布。

## 发布保全与回读

以发布前实际 Live 版本 `5410b3bbdfccf5e3` 的完整清单和配置生成封存包，替换 5 个已有 UI 文件并新增 4 个依赖。原有 450 个 public 文件保持原字节；没有删除资源。

部署后完整 Hosting 清单精确匹配候选包：459 public + 2 Firebase managed = 461 文件。450 个保留 public 文件和 2 个 managed 文件远端 gzip hash 与基线一致，Hosting 配置语义一致。9 个 UI 文件通过 HTTP GET 核对 SHA-256 和大小；`multilingual-v3.json` 保持原 SHA-256 `b776c2c4ddc68870af2284ea0e476e66354d08747a79afadbc4935816743b3b1`。

既有 `/downloads/19688e762c661a38-full-video-clock.mp3` 的 `Range: bytes=0-1023` 返回 206、1024 bytes，`Content-Range: bytes 0-1023/73077932`。核验开始、结束的 Live 版本一致。

## 验证

- `node --test experiments/sermon-dubbing-poc/web/*.test.mjs`：498 项，497 通过，0 失败，1 项既有跳过。
- `python -m unittest discover -s tests -p 'test_build_full_video_app_release.py'`：11 项通过；使用现有项目 `.venv/bin/python`。
- `git diff --check`：通过。
- 实际 Dev 浏览器：10 月 4 日中文证道加载 474 段字幕及 474 段完整文稿，类别为“正式播放版”；390×844 响应式检查无横向溢出。
- 00:19 字幕时间按钮定位主播放器到 19.29 秒，保持暂停；英文 `worthy` 返回 6 个真实文本结果，“跳到 05:26”定位到 326.45 秒，保持暂停。收起播放栏保持时间和暂停状态。
- 播放中手动滚动进入自由阅读，音频继续播放。随后暂停并回当前句，主播放器前后均为 331.945677 秒、`paused=true`，恢复跟随。
- Dev 浏览器模拟断网后重载：原标题、474 段字幕及 474 段完整文稿仍显示，离线提示准确。之后已恢复网络与默认浏览器尺寸。
- 设备与现场验收：`not_run`。上述浏览器结果不替代 iOS 实机或现场测试。

## 证据位置

本机忽略目录 `artifacts/web-ios-12616-dev-20261007/` 保存完整发布前基线、`candidate-v2/ui-update-plan.json`、`candidate-v2/deployment-attempt-v2.json`、`candidate-v2/post-deploy-verification.json` 和 `dev-mobile.jpg`。发布包使用 `scripts/prepare_dev_web_ui_update.py` 准备，再由现有 `scripts/guarded_hosting_publish.py` 执行；后者核对 Live 基线并持有远端发布租约。
