# 同行 App Store Page Header 动画候选

当前交付为 **v4 四语言本地可评审素材**，未上传、送审或替换 App Store 页面。原生 App 和 Firebase 内容均未改动。v1/v2 的中英文问候句截图候选和 v3 字体修复前候选保留为历史，不作为当前成片。v4 修正英文副标语中的中文字体，避免缺字方框。

## 设计与真实证道来源

沿用墨绿、鼠尾草绿与暖白，以及“一起听懂，一路同行”品牌语言。10 秒循环：书页图标 → 完整证道语句及英语对照 → 回到图标。四个版本的品牌文案、字体、字幕分别本地化为中文、英文、韩语和西语；整句长时间停留，不在中途切换另一句。波形是装饰性动效，不代表实际音频波形。

用户要求使用有意义的真实证道内容，因此 四语言版改用 **真实已发布证道文字的创意排版**，并非 App 截图、连续录屏或原生 UI。源为 Eric Geiger 2026-10-04《耶稣审判并保守》，同一个源句 `0-u325`，原文轴约 23:01：

> but there's no suffering that will separate you from the love of God that is in Christ Jesus our Lord.

已发布译文原样保留，未进行新的证道翻译：

- 中文：但没有任何苦难能使你与神的爱隔绝；这爱是在我们的主基督耶稣里的。
- 韩语：하지만 어떤 고난도 우리 주 그리스도 예수 안에 있는 하나님의 사랑에서 여러분을 떼어 놓지 못합니다.
- 西语：Pero ningún sufrimiento podrá separarte del amor de Dios en Cristo Jesús, nuestro Señor.

三个译文对应相同 sourceUnitIds、textGroupId 和英语原句；英文版主文为英语原句，下方中文对照，其余版本为目标语主文、英语对照。完整保留原句，没有省略号或截句，字幕中 `23:01` 是源句位置，不是这条编辑动画的时间。引文作为讲员证道语句展示，不冒充某个圣经译本的逐字经文。

本轮从 Firebase Dev 实际 HTTP 重新读取目录、三个 release/content 及 English reference，校验目录→发布包→内容哈希和源身份。发布包均标记 `published_http_verified` / `human_reviewed`，English reference 为 `human_approved`；这描述既有收据字段，并不代表本轮重新完成了人工内容审核、真机或现场验收。

## 交付与复现

当前忽略目录：`artifacts/tongxing-ios/page-header-v4/`。

- `tongxing-page-header-{zh,en,ko,es}.mp4`：3840×1646、30 fps、10 秒，H.264 / yuv420p，无音轨。
- `*-preview.mp4`：1920×824 本地观看代理，不用于提交。
- `*-poster.png`：3840×1646 RGB 静态封面。
- `index.html`：四语言播放对照、源句与来源说明。
- `sermon-quote.json` / `sources/`：所选完整源句与已发布原始 JSON、哈希及状态。
- `caption-layout.json` / `manifest.json` / `verification.json`：完整排版、来源、尺寸和循环编码证据。

工具为 `scripts/render_tongxing_page_header.py`，需要 Pillow、NumPy、ffmpeg、ffprobe。中文使用本机 PingFang SC，韩语使用 Apple SD Gothic Neo，英西语使用 Arial；字体不随仓库分发。

```sh
python3 scripts/render_tongxing_page_header.py \
  --quote "$TONGXING_VERIFIED_QUOTE_JSON" \
  --logo firebase/dev/public/brand-icon.png \
  --font "$TONGXING_PINGFANG_TTC" \
  --output artifacts/tongxing-ios/page-header-new
```

`--quote` 消费同目录下的 `sources/` 原始 JSON，并独立核对哈希、目录选择的发布包、源身份、审核状态和逐字引文。不允许模拟测试页。所有语言都必须在不截断的情况下排入卡片；不能排入则报错，不能静默删词。`--screens` 保留 v1/v2 的双语真实截图裁切路径，与 `--quote` 互斥。默认拒绝覆盖主视频；`--stills-only` 可先看排版。工具不连接上传、审核或商店发布接口。

## 验证及剩余边界

Apple [视频规格](https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications)规定 Header 为 3840×1646、30/60 fps、5–30 秒、MP4/MOV/M4V。本轮为 MP4、30 fps、10 秒。

Apple [Header PSD 模板](https://developer.apple.com/go/?id=photoshop-product-page-header-template)的 `Art Safe Area` 为左 1097、上 493、右 2743、下 1154。所有品牌文字、完整字幕卡与波形均在该区域，边缘书页轮廓仅作装饰。最终裁切仍应在 Connect Preview 检查。

以 ffprobe 核对四条主视频的尺寸、帧率、帧数、时长、像素格式及无音轨；ffmpeg 全片解码检查；逐个检查韩语、西语及中英文的编码后稳定画面，排版回执确认整句无删改、无超宽或高度截断；封面 RGB 无 alpha。循环渲染首尾完全相同，压缩后首尾差异另记，不能宣称编码逐像素相同。

当前为本地素材候选。未进行韩语／西语市场文案的母语人工验收；正式提交前仍须绑定拟上架版本及语言能力，确认内容可用性，完成 Connect 预览、接受、审核和线上读回。规格及本地视觉检查通过不等于 Apple 审核通过。

### v4 本轮实际检查收据

四条主视频均为 300 帧，ffmpeg 全片解码退出码 0；编码首尾平均 RGB 差异为中文 0.07698、英文 0.07716、韩语 0.07536、西语 0.07337（0–255 通道值）。四张封面均为 RGB、无 alpha。完整正文和对照句的换行拼接逐字一致，卡片内容高度最高 278 / 350 像素。

独立视觉复核确认英文副标语中文缺字已修复，四语言编码后稳定帧没有截句、缺字或安全区越界。In-app Browser 验证韩语和西语切换后视频 `readyState=4`、时长 10 秒、播放中、无媒体错误。当前四语言预览为 `http://127.0.0.1:8771/index.html`；它依赖本机预览服务，非公开部署地址。
