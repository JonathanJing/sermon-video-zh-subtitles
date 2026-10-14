# 同行 1.26.18 App Store 素材

## 更新说明

简体中文：

> 本次更新新增本周证道海报入口：在首页查看本周海报，轻点即可打开完整海报和内容页面。

English:

> This update adds the weekly sermon poster: view this week's poster on the home screen, then tap to open the full poster and its content page.

## 截图

本轮截图由 `TongxingScreenshots / Release` 在正式内容源中通过真实界面流程生成。中英文界面均选择已发布的简体中文内容，展示首页海报入口和完整海报详情；未使用 fixture。六个设备／语言组合的 UI 测试均通过，PNG 尺寸及 SHA-256 见忽略目录 `artifacts/tongxing-ios/formal-1.26.18-build58/screenshots/capture-manifest.json`。

| 设备 | 尺寸 | 语言与场景 |
|---|---:|---|
| iPhone 18 Pro | 1206 × 2622 | 中英文首页、海报详情 |
| iPhone Duo 外屏 | 1398 × 2034 | 中英文首页、海报详情 |
| iPad Pro 13 英寸 (M5) | 2064 × 2752 | 中英文首页、海报详情 |

Apple 当前要求 iPhone 动态岛中尺寸至少一张截图，iPad 应用还需提供 13 英寸 iPad 截图；本轮 iPhone 18 Pro 与 iPad 图达到相应尺寸。图片为 RGB PNG，无 Alpha 通道。

Apple 已公布 Duo 外屏和内屏截图规格，但 App Store Connect 2026-09-09 更新说明仍表示 Duo 素材上传稍后开放。当前截图集 API 的 `ScreenshotDisplayType` 允许值也没有 Duo 类型；官方规格说明写明自 2027 年 4 月起才要求提交 Duo 截图。因此 Duo 图作为设备截图保留，不把它冒充已上传的商店素材。内屏模拟器 framebuffer 本轮保持黑屏，未作为可用截图。

参考：[App Store Connect 截图规格](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)、[App Store Connect 更新说明](https://developer.apple.com/help/app-store-connect/release-notes/)、[截图集 API 类型](https://developer.apple.com/documentation/appstoreconnectapi/get-v1-appstoreversionlocalizations-_id_-appscreenshotsets)。
