# 每周制作前：后端四层快速 Dry Run

**Dry run 的范围是模拟收到视频链接，检查 Layer 1–4 的后端交接，最后在 Firebase Dev 生成测试页面。** 之前的 [Dev App 页面预演](firebase-dev-weekly-dry-run.zh.md)只覆盖页面、语言与播放；它是本流程的 Layer 4 前端检查，不能代替这条后端演练。

## 当前可运行的短流程

`scripts/backend_four_layer_dry_run.py` 使用仓库内 6 秒固定夹具。模拟链接固定为 `.invalid` 域名，不发网络请求。它在本地生成短 WAV、固定英文词时间和三语文字；通过真实的 Layer 1 锚点/English Source Package 构建器、三语 shadow lane planner、正式渲染器的 1 倍速排程函数，最后输出独立的 `preview_only` 页面和报告。接链、媒体夹具、Layer 1、shadow 规划、每个语言及每个文字／音频单元、Layer 4 均记录开始、结束、耗时和失败原因；失败注入可定位断点。

```bash
PY=/absolute/path/to/repo/.venv/bin/python
BASE=/absolute/path/to/last-verified-complete-dev-candidate
FEATURE=/absolute/path/to/latest-ci-green-production-layout-public
OUT=/absolute/path/to/ignored/dry-run-run

"$PY" scripts/backend_four_layer_dry_run.py --out "$OUT/backend"
"$PY" scripts/firebase_dev_weekly_dry_run.py build \
  --dev-base-candidate "$BASE" --feature-public "$FEATURE" \
  --backend-run "$OUT/backend" --preview-id 2026-10-04-backend-flow \
  --out "$OUT/dev-candidate"
"$PY" scripts/firebase_dev_weekly_dry_run.py preflight \
  --candidate "$OUT/dev-candidate" --dev-base-candidate "$BASE" \
  --out "$OUT/dev-preflight.json"
"$PY" scripts/firebase_dev_weekly_dry_run.py deploy \
  --candidate "$OUT/dev-candidate" --preflight "$OUT/dev-preflight.json" \
  --out "$OUT/dev-deployment.json"
"$PY" scripts/firebase_dev_weekly_dry_run.py verify \
  --candidate "$OUT/dev-candidate" --out "$OUT/dev-http.json"
```

`--fail-at intake|layer1|layer2:<locale>|layer3:<locale>|layer4` 可模拟一个断点。失败仍保存 `run-report.json`，但构建器拒绝把失败产物发到 Dev。更改固定夹具、某语言文字或排程后，应使用新输出目录和新 preview ID；现有历史页面与正式 v3 目录保留。

## 门禁和证据边界

- Layer 1 真实构建结果仍是 `blocked`，`humanApproval=false`。演练只投影一个标记 `simulationProjection=true` 的 shadow 规划视图，供真实 lane planner 测试三语分流；它不是正式 English Source Package。
- Layer 2 的三语文字是固定夹具，Layer 3 的 WAV 是测试音。它们只使用 `sermon-dry-run-*` shadow 格式，不写正式 Candidate、Speech Job、Audio Package 或人工审核收据。真实翻译模型、TTS、全轨听审和同步听审并未执行。
- Layer 4 只复制 `public/flow/` 到 Dev 的 `/dry-run/<id>/flow/`；App 演练页提供入口。正式 `/multilingual-v3.json` 与 `/releases-v2/` 不修改。部署前完整校验 Dev 基线，部署后逐文件 HTTP／SHA，并检查模拟页可访问。Production、iOS 与现场验收均不从此推断。
- `run-report.json` 保留每个步骤的时间、状态、源哈希、各语言交接哈希、模拟边界和外部调用次数。公开 `flow/report.json` 只用于展示模拟状态；没有正式审批或发布资格。

## 尚需接入的生产共用编排

当前 Supervisor 只覆盖 `dual_pdf`，并无同一个正式入口贯通四个 package。这个短流程验证轻量共同函数、顺序、分语言隔离、失败阻断和 Dev 发布链路；它**不证明**正式 Layer 2/3 producer 在新周会成功。下一步把来源接入、模型响应、TTS 和发布器整理为可注入端口，使固定响应通过与正式运行相同的控制循环；增加最近一次真实批准包的只读 hash 回放和故障场景，再将此 dry run 设为每周开始前的自动门禁。任何模拟收据都不得成为正式审批或 Production 发布依据。

## 2026-10-04 首次 Dev 实跑

- 固定模拟链接生成 23 条步骤事件（含 12 条逐单元事件），每条均有 `startedAt`、`endedAt`、`elapsedMs`。所有下载、ASR、翻译、TTS、Firebase 外部调用计数为 0；Layer 1 正式人审门禁保持 `pending`。
- 失败注入 `layer2:ko` 能停止 Layer 4，失败产物被 Dev 构建器拒绝；真实 HTTPS 域名与更改后的 WAV 哈希也被拒绝。定向 unittest 通过。
- 使用当前完整 Dev 候选生成 `2026-10-04-backend-steps`；发布前核对旧 229 文件，发布后核对完整 236 文件的 HTTP 大小与 SHA-256，Dev App 测试页和模拟结果页均可访问。测试页：<https://ai-for-god-sermon-audio-dev.web.app/dry-run/2026-10-04-backend-steps/index.html?week=2026-09-27-weekend-sermon-drive-530&contentLang=zh-Hans>。
- 本地原始报告和 Dev 收据位于 Git 忽略目录 `artifacts/backend-four-layer-dry-run/2026-10-04-per-unit/`。浏览器内容观察与 HTTP 校验不等于模拟音频的主观试听、正式整篇运行、iOS 或现场验收。
