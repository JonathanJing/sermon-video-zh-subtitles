# 中文圣经来源

会众页右侧经文栏需要显示讲道中提到的完整经文章节。当前开源 POC 使用：

- 译本：新标点和合本（简体） / Chinese Union Version (simplified)
- eBible ID：`cmn-cu89s`
- 详情页：<https://ebible.org/find/details.php?id=cmn-cu89s>
- 下载包：<https://ebible.org/Scriptures/cmn-cu89s_vpl.zip>
- eBible 页面标注授权状态：Public Domain

浏览器不直接加载整本圣经。我们用 `scripts/build_scripture_index.py`
生成小的经文切片，只包含当前讲道识别到的引用：

```bash
python3 scripts/build_scripture_index.py \
  --out web/scripture-cmn-cu89s.generated.js \
  --ref "Numbers 16" \
  --ref "Numbers 16:48"
```

如果已经下载了 eBible zip，可以加 `--zip /path/to/cmn-cu89s_vpl.zip`。生成的
前端文件会包含来源 metadata 和请求的经文引用。

不直接使用 `wd.bible` 作为可再分发文本来源。它的 CUNPS 页面显示
`Copyright © 1995 Hong Kong Bible Society. Used by permission`，说明
`wd.bible` 自己获得了展示授权，但这个授权不会自动转给本项目。

UI 署名使用：

`中文圣经：新标点和合本（简体） · eBible.org cmn-cu89s · Public Domain`
