# review-web：人工审核页

生产到了要等人的步骤时打开的页面，每个步骤一页。设计和每一页的内容见[人工审核页与通知](../../docs/design/review-gates-and-notifications.zh.md)。

| 文件 | 步骤 |
|---|---|
| `index.html` | 本周审核总览 |
| `decisions.html` | 开工确认（`l0.decisions`） |
| `english.html` | 英文表批准（`l1.english-review`） |
| `speakers.html` | 讲员确认（`l1.speakers`，双人才有） |
| `track.html` | 整轨听审（`l3.review.<locale>`） |
| `study.html` | 学习内容批准（`l4.study`） |
| `publish.html` | 发布授权（`l4.publish.authorization`） |
| `confirm.html` | 发布后确认（`l4.device-confirm`） |

每页一个同名的 `.mjs`。`gate.mjs` 是共用部分：读取任务、显示它绑定的版本、保存草稿、提交决定、播放音频。`coverage.mjs` 计算整轨实际听过多少，`theme.js` 在绘制前套用深浅色。没有构建步骤，也没有第三方依赖。

## 预览

```bash
python3 -m http.server 8797 --bind 127.0.0.1 -d apps/review-web
```

打开 `http://127.0.0.1:8797/index.html?demo=1`。带 `demo` 参数时读 `demo/` 下的合成数据，音频用提示音代替，提交不发请求，只显示将要提交的内容。

## 与生产机的接口

不带 `demo` 参数时，页面用相对地址访问同源的三个接口，由 [`tools/ops/review_gate_server.py`](../../tools/ops/review_gate_server.py) 提供：

| 请求 | 返回或提交 |
|---|---|
| `GET api/gates?production=<名称>` | 总览，[`sermon-review-index-v1`](../../schemas/sermon-review-index-v1.schema.json) |
| `GET api/gate?production=<名称>&gate=<步骤>` | 一个审核任务，[`sermon-review-gate-v1`](../../schemas/sermon-review-gate-v1.schema.json)；媒体文件在任务的 `assetsBase` 下 |
| `POST api/decisions` | 一个决定，[`sermon-review-decision-v1`](../../schemas/sermon-review-decision-v1.schema.json)；返回决定编号、提交人和处理状态 |

页面提交的是决定，不是收据：生产机核对决定里的哈希与当前文件一致后才生成收据。媒体接口需要支持 Range 请求，否则 iPhone 上音频可能无法播放或拖动。

## 改页面时

遵守 [Web 前端现代化策略](../../docs/web-frontend-modernization-policy.zh.md)：不写内联样式、内联脚本和内联事件；不引用外部域名的资源；深色优先。`tests/test_review_web_pages.py` 会检查这些，并用 schema 校验演示数据；`tests/review-web.test.mjs` 测听审覆盖率的计算。
