# 同行网页与 iOS：中英对照

中文是主阅读内容，英文用于核对参考。网页和 iOS 采用相同规则：

- 收听页保留中文当前字幕；全文页完整显示中文。
- 每个来源内容块的最后一句中文字幕下显示「英文对照」，默认收起；点击后在下方展开完整英文。
- 英文用次级文字层级，支持选择复制；手机上纵向排列，避免双栏压缩正文宽度。
- 展开、收起不定位音频；仅时间按钮定位，时间仍属于中文音轨。
- 缺少英文或关联时明确提示，不回译、不按数组位置或时间猜配。

## 数据与发布

沿用 iOS 已有的可选 `sermon-bilingual-transcript-v1` 扩展，不改变外层 `sermon-weekly-catalog-v1`。`weekly.json` 的每篇内容可包含：

```json
{
  "transcript": {
    "schemaVersion": "sermon-bilingual-transcript-v1",
    "blocks": [{
      "blockId": "0",
      "english": "Source passage.",
      "chinese": "中文段落。",
      "sourceTextOrigin": "job.blocks",
      "reviewState": "reading_quality_pass"
    }]
  }
}
```

[`build_weekly_app.py`](../experiments/sermon-dubbing-poc/build_weekly_app.py) 从已验证的冻结 `job.blocks` 导出原有中英文，按显式 `blockId` 关联音轨字幕。一个内容块可以有多句配音字幕；英文只显示一次。数据保存来源和已有审校状态，`reading_quality_pass` 只表示继承文字 QA，不代表人工逐字核对。没有对应记录时使用 `unspecified`。

[`catalog.mjs`](../experiments/sermon-dubbing-poc/web/catalog.mjs) 与 [`BilingualTranscript.swift`](../apps/tongxing-ios/Core/Sources/TongxingCore/BilingualTranscript.swift) 使用一致的身份关联规则；拒绝重复或未知段落身份，兼容历史内容没有 `transcript` 或字幕没有 `blockId`。新构建的每个 weekly job 自动带出双语数据；仅保留旧目录条目的发布不会自动补写旧条目，旧内容需要从相应冻结 job 重新导出页面数据。无需重跑模型或音频合成。

上线包含两部分：更新网页与目录数据；发布含折叠界面的新 iOS 构建。旧 iOS 若已支持该数据扩展，可读取新增英文，但仍按其旧界面直接展开显示。缓存目录需刷新才会得到新增英文。

## 本轮验证

2026-09-12：20 项 Python 导出与页面测试、30 项网页数据与播放器测试、5 项 Swift 数据契约测试，以及 1 项 iOS 模拟器 UI 测试通过；iOS 编译通过。UI 测试验证英文默认收起、展开与收起、界面语言切换和播放位置保持。

网页合成示例已检查桌面和 390px 手机宽度，实际 7 篇冻结内容的 463 个英文块均可与字幕关联。随后经用户明确授权，实际证道也完成了本机桌面与 390px 手机宽度的英文展开和长段落换行检查，临时服务已关闭；此次实文预览不代表音频定位验收。证据保存在忽略目录 `artifacts/bilingual-reference-20260912/`；本轮不等同于线上部署、TestFlight 更新或真机验收。
