# App Store 商店截图：采集与上传（含 iPhone Duo）

2026-11-16 发布 1.26.35 时没做出 Duo 截图，当时误判为“本机没有模拟器图形界面”。实际是 Xcode 27 把 `Simulator.app` 换成了 `DeviceHub.app`，并且**折叠 Duo 就在 DeviceHub 的窗口按钮里**。本文记录可复现的方法，供下个版本直接使用。截图是展示素材，不证明功能、真机或审核结果。

## 关键事实（2026-11-16 实测）

- Xcode 27 的模拟器界面：`/Applications/Xcode.app/Contents/Applications/DeviceHub.app`。
  旧的 `Contents/Developer/Applications/Simulator.app` 已不存在；`open -a Simulator` 会失败。
- Device Hub 窗口底部姿态按钮：`Closed` / `Partially Open` / `Open`（另有 `Home`、`Screenshot`、`Record`、`Rotate Right`）。点击可用桌面无障碍完成，坐标以当次窗口为准。
- **Duo 展开时外屏不供电，截出来是全黑**；必须先点 `Closed` 折叠，`--display=1` 才有画面。`simctl` 没有折叠命令。
- 显示通道：`xcrun simctl io <udid> enumerate` 可列出；`--display=1` 是外屏 LCD，`--display=3` 是内屏。
- 导出方向会跟设备姿态走：折叠后外屏曾导出为横屏 `2034×1398`，而商店 `APP_IPHONE_DUO` 槽位要竖屏 `1398×2034`；`Rotate Right` 那一次点击没有改变导出方向，**每次截完都要核对 PNG 尺寸**。

## 槽位尺寸（现行 listing）

| 显示类型 | 尺寸 | 对应设备 |
| --- | --- | --- |
| `APP_IPHONE_67` | 1320×2868 | iPhone 18 Pro Max 模拟器 |
| `APP_IPHONE_61` | 1206×2622 | iPhone 17 / 18 Pro |
| `APP_IPHONE_DUO` | 1398×2034（外屏竖屏） | iPhone Duo，`--display=1`，需折叠 |
| `APP_IPAD_PRO_3GEN_129` | 2064×2752 | iPad Pro 13 英寸 |

Duo 内屏导出为 `2007×2853`（展开、竖屏姿态）。**内屏尺寸是否被 `APP_IPHONE_DUO` 槽位接受尚未验证**；下个版本先做外屏，若内屏被接受再加一张。

## 采集步骤

```sh
# 1. Release 构建（生产内容源；Debug/BetaRelease 不是商店内容）
apps/tongxing-ios/scripts/ios.sh build --scheme Tongxing --configuration Release

# 2. 装到 Duo 并启动
UDID=<iPhone Duo 的 UDID>
APP=artifacts/tongxing-ios/<日期>/cli/DerivedData/Build/Products/Release-iphonesimulator/Tongxing.app
xcrun simctl boot $UDID 2>/dev/null
xcrun simctl install $UDID "$APP"
xcrun simctl launch $UDID com.jonathanjing.tongxing.dev

# 3. 统一状态栏（商店图惯例 9:41）
xcrun simctl status_bar $UDID override --time "9:41" --batteryState charged \
  --batteryLevel 100 --wifiBars 3 --cellularBars 4

# 4. 打开 Device Hub 并选中 Duo，点 Closed 折叠；用 idb/桌面操作把界面切到要展示的页面
open /Applications/Xcode.app/Contents/Applications/DeviceHub.app

# 5. 截外屏并核对尺寸（必须是 1398×2034）
xcrun simctl io $UDID screenshot --display=1 duo-outer.png
# 6. 内屏：切回 Open，再截 --display=3
xcrun simctl io $UDID screenshot --display=3 duo-inner.png
```

每张截图都要读图确认：状态栏 9:41、界面语言、页面内容（证道或播客）、没有弹窗或半透明动画。采集完把设备恢复 `Open`，`xcrun simctl status_bar $UDID clear` 可清掉状态栏覆盖。

方向不对时按这个顺序试：先 `Open` → `Rotate Right`（可能需要多次）→ 再 `Closed` 截图；仍不对就换 `Partially Open` 对比。以 PNG 实际尺寸为准，不改图去凑尺寸。

## 上传

```sh
.venv/bin/python tools/ops/upload_appstore_screenshots.py \
  --version 1.26.36 --locale zh-Hans --display-type APP_IPHONE_DUO \
  --images duo-outer.png duo-inner.png \
  --receipt artifacts/tongxing-ios/<日期>/duo-receipt.json --dry-run
# 确认后把 --dry-run 换成 --execute
```

- 只允许改 `PREPARE_FOR_SUBMISSION` 状态的版本；已提交审核的版本要先走新的提交。
- 工具流程：定位版本与本地化 → 删除旧截图集（Apple 每个本地化 + 显示类型只允许一个集）→ 新建集 → 逐张 reserve／上传／patch → 轮询 `COMPLETE` → 写收据（含每张 SHA-256）。任何一张不是 `COMPLETE` 就以非零退出。
- 2026-11-16 用同一流程在 1.26.35 上替换了简中／英文 `APP_IPHONE_67` 各 3 张，全部 `COMPLETE`；当时的临时脚本在忽略目录，本工具是它的提交版本。

## 当前状态与下个版本要做

- 1.26.35 (81) 已提交审核：`APP_IPHONE_67` 是新的 3 张（当前字幕／证道与播客面板／字幕全文，简中+英文）；`APP_IPHONE_DUO`、`APP_IPHONE_61`、`APP_IPAD_PRO_3GEN_129` 仍是旧素材。
- 下个版本的截图任务：
  1. Duo 外屏竖屏两张（首页 + 证道与播客面板），替换现有两张海报图；
  2. 用同一 Release 构建重放 6.1 寸与 iPad 尺寸的截图（可选，不影响审核）；
  3. 内屏若被槽位接受，补一张展开态截图。

## 证据位置

忽略目录 `artifacts/tongxing-ios/production-1.26.35/`：`shots/`（原始截图，含 Duo 折叠后的 `duo-outer-folded.png` 2034×1398、内屏 `duo-display-3.png` 2007×2853）、`final/`（上传成品与收据）、`final-state.json`（版本、Build、各本地化截图数量）。

## 已知限制

- 纯 headless 环境（无桌面会话）只能截“有电”的显示；折叠需要 Device Hub 的 GUI，CI 里做不到。
- 截图是模拟器画面，不是真机；文字渲染、动态岛/灵动岛区域和真机状态栏可能不同。
- 商店素材变更属于展示层，不改变二进制、审核状态或功能验收。
