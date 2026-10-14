# 每周更新海报 Beta

候选 1.26.17（58）新增原生「本周更新」卡片及海报 Sheet。冷启动、下拉刷新、回到前台时检查发布目录；回到前台的检查只获取新快照，不替换正在收听的页面、音轨和进度。用户点「打开本周内容」才明确切换。关闭提示或看过海报后，同一页面／语言／发布包不再重复提醒；保留「本周海报」入口。图片失败时保留标题与内容入口。

本机通知点击仍校验 Beta Dev 的页面、订阅语言和发布包 SHA，成功后展示对应页面的海报。通知目标使用独立状态，默认页面检查不覆盖通知海报。此候选没有接通远程 APNs；配置见 [APNs 步骤](APNS-SETUP.zh.md)。通知横幅中的富媒体附件也未实现。

## Firebase 数据

新增可选 `/weekly-announcements-v1.json`，schema `tongxing-weekly-announcements-v1`，不改 existing catalog/release schemas。每条包含 id、pageID、locale、releaseSHA256、sourceIdentitySHA256、title、publishedAt 和 poster（url、sha256、bytes、width、height）。客户端仅显示能与当前已发布内容绑定的条目；机器质检仍遵循已有 v4 发布包声明，不成为人工批准。

图片限同源 HTTPS `/posters/` 下 PNG/JPEG、8 MiB、8192 单边与 2000 万像素，校验字节数、SHA、实际尺寸。离线只复用重新校验过的缓存。404 表示服务端关闭本功能，不复活旧目录缓存。已读凭据为 App 私有 `weekly-update-seen-v1.json`。

每周发布页面后，用已有、完整海报 receipt 生成目录：

```sh
python3 scripts/build_weekly_announcement_sidecar.py \
  --catalog "$CURRENT_CATALOG" --release "$CURRENT_RELEASE" \
  --poster-receipt "$POSTER_RECEIPT" --poster-file "$POSTER_PNG" \
  --page-id "$PAGE_ID" --locale "$LOCALE" --origin "$CONTENT_ORIGIN" \
  --out "$ANNOUNCEMENT_PUBLIC"
```

如只有发布元数据改变，须核对来源身份与 content SHA 未变，再显式使用 `--allow-metadata-rebind`；记录旧／新 release SHA。脚本不部署，不修改上游证道内容。完整 public snapshot 合入目录和三语图片后重新 seal，用已有 guarded Hosting publisher 发布并读回。不得只部署四个文件而删除现有站点；私有 binding receipts 不放 public。每周素材生成与发布目前仍须执行该步骤，尚未接成无人值守任务。

首次支持本功能需要升级 App；之后每周标题和海报通过 Firebase 更新即可。Firebase 网页 UI 本轮 `not_applicable`，没有照搬原生 Sheet。

## 2026-10-07 已验证

- Xcode 27 / iOS SDK 27.0 原生 Beta 构建通过。
- Core 3 项、Infrastructure 2 项、Python producer 3 项通过。
- iPhone 17 Pro / iOS 27：2 项交互测试通过；关闭后冷启动保持已读、海报缺失仍可打开、查看海报保持播放。
- 3 项 hosted 状态测试通过：相同发布包保持音频与进度；同页面新发布包清理旧音频；默认与非默认通知海报状态隔离，已读凭据合并持久化。
- iPhone Duo / iOS 27.1：1 项真实 Dev 内容测试通过，中／韩／西三语图片已核对并捕获。初始 XCTest PNG 为黑帧，不能作为视觉证明；后续 Device Hub 实际显示与 simctl 指定活动 display 的非黑截图单独保存。
- Dev Hosting 从 `7f71393213c192eb` 到 `b3f972eb12785d0f`，原 461 文件 hash 不变，仅新增 sidecar 与三张 PNG。四 URL GET/SHA 读回通过，原 catalog/default 不变。
- 图片沿用已验证本周正式海报，二维码指向正式站；App 按钮打开 Dev 页。非订阅语言没有海报则不显示卡片。

证据保存于忽略目录 `artifacts/weekly-announcements/` 及本轮 `.xcresult`。机器审核修复两项功能问题后通过；人类界面确认、真机新 Beta 安装、远程推送实发仍为 not_run。TestFlight 分发记录在归档后另行追加。
