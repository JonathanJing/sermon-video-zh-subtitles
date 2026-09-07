# App Store 真实界面截图

更新日期：2026-09-07。当前上传候选共 **8 张**：保留 build 4 的四张主收听页 `01-listen.jpg`，配合 build 5 根据当前线上目录新采集的四张中文全文页 `02-transcript.jpg`。iPhone / iPad 各含简体中文、英文两组，每组两张。**四张全文图已在 ASC 替换并核验**；此前 ASC 接收的 build 4 截图属于历史状态。

## 当前组合与检查

组合目录为 `artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/`，每组按 `01-listen.jpg`、`02-transcript.jpg` 排序。8 张均与各自来源文件字节相同。两种界面语言保留真实控件；英文界面不改变中文音轨或正文语言。

| 组别 | 实际设备 / 系统 | 竖屏像素 | 格式 |
| --- | --- | --- | --- |
| iPhone 6.9 英寸 | iPhone 17 Pro Max / iOS 27.0 模拟器 | 1320 × 2868 | JPEG，无 Alpha |
| iPad 13 英寸 | iPad Pro 13-inch (M5) / iOS 27.0 模拟器 | 2064 × 2752 | JPEG，无 Alpha |

尺寸依据保留于 [Apple 截屏规范](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)。本轮组合目录定向检查通过：8 张支持尺寸，核心文案字段无错误；格式、Alpha 与视觉检查来自各次采集记录。检查报告见 [combined-screenshot-material-check.json](../../artifacts/tongxing-ios/2026-09-07-app-store-build5/combined-screenshot-material-check.json)。本地检查不代表 ASC 接收或审核通过。

| 设备 / 语言 | 当前上传文件 | 真实来源与画面 | SHA-256 |
| --- | --- | --- | --- |
| iPhone 6.9 / 简体中文 | [01-listen.jpg](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/iphone-6.9/zh-Hans/01-listen.jpg) | build 4；原主收听页，00:00 待播放。 | `0e2c80dece581807f1135ecf143939cacbf06df6439d30168a278acddbf8224b` |
| iPhone 6.9 / 简体中文 | [02-transcript.jpg](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/iphone-6.9/zh-Hans/02-transcript.jpg) | build 5；当前目录中文全文、未提供英文提示，00:00 / 29:23。 | `3bd46db4040e802f3854e28ebd01af305c38b5b150128bcf069242cd8a22ac79` |
| iPhone 6.9 / English | [01-listen.jpg](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/iphone-6.9/en/01-listen.jpg) | build 4；原主收听页，00:00 待播放。 | `faccae8c205800521ecaa5746972adb26c100472035687cbb99b5a5b9c20a4d2` |
| iPhone 6.9 / English | [02-transcript.jpg](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/iphone-6.9/en/02-transcript.jpg) | build 5；当前目录中文全文、未提供英文提示，00:00 / 29:23。 | `7d7b388cd41f4db2d9d882a18e5483e47c4b33d091a64199f38b85aad32f6881` |
| iPad 13 / 简体中文 | [01-listen.jpg](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/ipad-13/zh-Hans/01-listen.jpg) | build 4；原主收听页，00:00 待播放。 | `d2bff05c5d240b45a0c1dadfe8fa1a8f0cda93053611852dee1a2bb25aebec7b` |
| iPad 13 / 简体中文 | [02-transcript.jpg](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/ipad-13/zh-Hans/02-transcript.jpg) | build 5；当前目录中文全文、未提供英文提示，00:00 / 29:23。 | `d95f9268e71f4fbade6cf992545d881915f38f10c5caabfcc6e5785ebb63e546` |
| iPad 13 / English | [01-listen.jpg](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/ipad-13/en/01-listen.jpg) | build 4；原主收听页，00:00 待播放。 | `fd0387652122c36b22ad358b07db281bd9d908e2a13979473f9e499af29b89c8` |
| iPad 13 / English | [02-transcript.jpg](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/ipad-13/en/02-transcript.jpg) | build 5；当前目录中文全文、未提供英文提示，00:00 / 29:23。 | `909b3db4dd755f8edc45685ad050f687d6077d9d4c9575c2f34f324e5bb65899` |

## build 5 四张全文页来源

原件保存在 `artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/{iphone-6.9,ipad-13}/{zh-Hans,en}/02-transcript.jpg`。文件大小、采集时间及逐图视觉检查见 [新截图清单](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/screenshot-inventory.json)，构建、目录与采集方法见 [新采集来源记录](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/capture-provenance.json)。

- App 版本 `0.1.0 (5)`，Xcode `27A5252f`，SDK `iphonesimulator27.0`；普通启动，未启用 fixture，`TONGXING_TEST_HOST=0`。应用路径 `/private/tmp/tongxing-release-20260907/Build/Products/Debug-iphonesimulator/Tongxing.app`。
- 可执行文件 SHA-256：`d852f8734ce1939a6980de9ac80c78696f73c0ec470e584d7a656ba3a50e4987`；`Tongxing.debug.dylib` SHA-256：`015f3c77c6acb64c42b08f211321af986d18f72ccc8cb5e4e66c3ae266b15995`。
- [线上目录](https://ai-for-god-sermon-audio.web.app/weekly.json)与两台模拟器缓存一致，SHA-256 为 `e88ac7c163307388dc1ee334d393c87f6c6ab9ffb6cf0171807d5c1d908b49ee`，含 6 篇。与权利/分级审计快照 `94f7c74afc1973c69b86d9b96490a435d9a4433a99ec22de026d97f644d92c8c` 相比，仅六篇 `title` / `sourceLabel` 共 12 个字段变化；来源 URL/ID、中文 cues、音轨、媒体哈希和时长相同。[差异记录](../../artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/catalog-diff.json)。
- 选中周次 `2026-09-06-archive_caption-frqebLEtyqw`，标题“当我怀疑神的计划时 · 当生活令人费解｜YouTube 版”，来源 [英文原视频](https://www.youtube.com/watch?v=frqebLEtyqw)。
- 音轨 `full_candidate__archive_caption__frqebLEtyqw`，标签“整篇待审”，SHA-256 `8672c7398848aeb36bedbc8c4fd534b9c15ea586dd55cd138917ac3babb62981`，时长 `1763.07` 秒。

四张新图均显示中文全文及当前缺少英文的说明，位置为 `00:00 / 29:23`，播放控件处于待播放状态。正常启动中文界面后，英文图通过 App 内“更多选项 → 界面语言 → English”切换。采集者已逐图检查；本轮没有启动音频、听音对齐或下载。

## build 4 主收听页与历史证据

当前保留的四张 `01-listen.jpg` 原件来自 `artifacts/tongxing-ios/2026-09-07-release/screenshots/`。它们是 build 4 与当时目录的真实截图；主收听界面没有因新增隐私入口而改变，因此沿用原图。它们不被改记为 build 5 或新目录截图。原始八张的大小、采集时间与哈希见 [历史截图清单](../../artifacts/tongxing-ios/2026-09-07-release/screenshots/screenshot-inventory.json)，构建和目录证据见 [历史采集来源](../../artifacts/tongxing-ios/2026-09-07-release/screenshots/capture-provenance.json)。

- App 版本 `0.1.0 (4)`，普通启动，未传入 `--ui-testing`；路径 `/tmp/tongxing-release-20260907/Build/Products/Debug-iphonesimulator/Tongxing.app`。
- 可执行文件 SHA-256：`d852f8734ce1939a6980de9ac80c78696f73c0ec470e584d7a656ba3a50e4987`；`Tongxing.debug.dylib` SHA-256：`82c3700506e57cb936358ae245bdec72206f3f5d04621d9a293d9b8efd482c25`。
- 当时两台 App 缓存目录 SHA-256：`6011d3640113768e50615b5895eed2975885acf769a74b5de175ad65893b1eb1`。
- 选中周次 `2026-09-06-live_archive-l8ucqF9uA9A`，标题“当我心存疑惑时（内容拟题）”，讲员 Jared Kirkwood，来源 [英文原视频](https://www.youtube.com/watch?v=l8ucqF9uA9A)。
- 音轨 `full_candidate__live_archive__l8ucqF9uA9A`，SHA-256 `3f7c06b8eff7357a44a80cbcd195621d20fcb7610d249aa0c971b4e50003f687`，时长 `32:47`；截图位置 `00:00`，待播放。

以下旧双语全文图仅保留历史证据，不进入当前组合上传目录：

| 历史文件 | SHA-256 |
| --- | --- |
| [iphone-6.9/zh-Hans/02-transcript.jpg](../../artifacts/tongxing-ios/2026-09-07-release/screenshots/iphone-6.9/zh-Hans/02-transcript.jpg) | `275ea73ca9e502caa623281e645fd7c4f89479fc319a80f300535f235579a241` |
| [iphone-6.9/en/02-transcript.jpg](../../artifacts/tongxing-ios/2026-09-07-release/screenshots/iphone-6.9/en/02-transcript.jpg) | `b23ae72b5aa32806b53f017b24e66df5d6fcfb87ad0b979617e69928b2b097ac` |
| [ipad-13/zh-Hans/02-transcript.jpg](../../artifacts/tongxing-ios/2026-09-07-release/screenshots/ipad-13/zh-Hans/02-transcript.jpg) | `c4be7f4e460e5e8018f5da0dcd593d180d3d375b0cdebb604296f9363bd9e026` |
| [ipad-13/en/02-transcript.jpg](../../artifacts/tongxing-ios/2026-09-07-release/screenshots/ipad-13/en/02-transcript.jpg) | `95cc5b04ed29f99b6f5b5a2587aefad9d368820b2a7ec8c60cf5c35829de2c79` |

历史双语图显示完整中文和英文来源块；对应全文时间按钮不代表当时正在播放。`evidence-build3/` 与 `evidence-build4-layout/` 保留早期构建和取景过程，不纳入当前 8 张候选。

## 采集方法与使用边界

两次均使用模拟器原生截屏输出完整分辨率 JPEG，保留实际系统状态栏、滚动位置和播放控制；没有缩放、拼接、重绘或覆盖文字。

```sh
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer xcrun simctl io "$TONGXING_SCREENSHOT_SIMULATOR_UDID" screenshot --type=jpeg "$TONGXING_SCREENSHOT_OUTPUT"
```

当前六篇目录没有英文全文块或听音对齐引用。界面保留待审与来源说明；截图不把候选内容改记为人工或现场验收完成。build 5 的 beta SDK 模拟器截图不代表正式 SDK Archive、IPA、Cloud 构建、ASC 替换或 App Review 接收；实际声学、后台及真机收听验收仍按发布记录处理。
