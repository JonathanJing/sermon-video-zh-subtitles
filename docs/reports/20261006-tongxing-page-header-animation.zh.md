# 同行 App Store Page Header 动画候选

本轮交付为本地可评审素材，未上传、送审或替换 App Store 页面。原生 App 和 Firebase 内容均未改动。

## 设计与素材

沿用墨绿、鼠尾草绿与暖白，以及“一起听懂，一路同行”品牌语言。10 秒循环：书页图标 → 真实双语字幕卡 → 另一句双语字幕卡 → 回到图标。英文版本使用 `Understand. Walk together.`；字幕内容保持中文与英文对照。波形仅为装饰性品牌动效，不代表原音波形或连续播放录屏。

字幕取自 2026-10-06 的 iPhone Duo / iOS 27.1 BetaDebug 实际截图 `04a-full-transcript-zh-en-pairs.png`，源码为 `65b56bb83d70bb81e18cdb236f5f9cd1efb4ea55`。选取 00:01、00:07 两张完整字幕卡，未改写字幕；源图、来源 Manifest 和 SHA-256 保存在素材目录。截图中的时间并不对应这条 10 秒编辑动画的时间。

候选 v1 的字幕交叉混合造成文字重影，v2 已改为先淡出旧卡、再淡入新卡。中英主标题分别排版，静音可理解；没有灵动岛、定位成功、锁屏实时字幕或固定定位耗时的宣传。

## 交付与复现

本次忽略目录：`artifacts/tongxing-ios/page-header-v2/`。

- `tongxing-page-header-zh.mp4` / `tongxing-page-header-en.mp4`：3840×1646、30 fps、10 秒，H.264 / yuv420p，无音轨。
- `*-preview.mp4`：便于本地观看的 1920×824 代理，不用于提交。
- `*-poster.png`：3840×1646 RGB 静态封面，取稳定字幕画面。
- `index.html`：本地播放与中英文对照。
- `manifest.json` / `verification.json`：来源、尺寸、循环与编码证据。

工具为 `scripts/render_tongxing_page_header.py`，需要 Pillow、NumPy、ffmpeg、ffprobe；可使用宿主提供的 Python 依赖运行时。字体参数为本机 PingFang TTC（SC Regular/Medium），字体不随项目分发。英文采用系统 Arial。以下路径由本机已核实的资产取得，不把占位符当成真实输入：

```sh
python3 scripts/render_tongxing_page_header.py \
  --screens "$TONGXING_PROMO_SCREENS" \
  --logo firebase/dev/public/brand-icon.png \
  --font "$TONGXING_PINGFANG_TTC" \
  --output artifacts/tongxing-ios/page-header-new
```

默认拒绝覆盖已存在的主视频；`--stills-only` 用于先检查排版。工具不调用上传、送审、商店发布接口。

## 验证及剩余边界

Apple [视频规格](https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications)规定 Header 为 3840×1646、30/60 fps、5–30 秒、MP4/MOV/M4V。本轮使用 MP4、30 fps、10 秒。

下载并解析 Apple [Header PSD 模板](https://developer.apple.com/go/?id=photoshop-product-page-header-template)的 `Art Safe Area` 图层：左 1097、上 493、右 2743、下 1154。品牌文字与字幕卡位于此区域；边缘的书页轮廓仅作装饰，可裁切。实际 App Store 裁切仍须在 Connect 的 Preview 工具检查。

以 ffprobe 核对主视频的尺寸、帧率、帧数、时长、像素格式及无音轨；ffmpeg 全片解码检查无错误；检查编码后稳定画面以及首尾帧差异。循环渲染首尾帧完全相同；压缩后差异值单独保存在验证回执，不宣称逐像素相同。

当前为 Beta / Dev 界面候选。正式提交前须绑定拟上架正式版本，确认相同字幕能力与内容可用性，再进行 Connect 接受、预览、审核及线上读回。素材尺寸通过不等于 Apple 审核通过。
