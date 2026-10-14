# 复盘：20261014-dev-180s-e2e-20261014T032153Z

数据见同目录 INDEX.md 和 manifest.json。目的：在 dev b73df41a（已合并 #398）上，用一次真实 Dev 部署验证 Hosting 版本回执的解析。不调用模型，不占 Spark，不花 API 费用。

## 实际覆盖范围

- 片段模拟交付：`run_dev_180s_beta_e2e.sh --execute`，`CLIP_SPEC` 为 10-12 片段（clip-spec v1，自动迁移到 v2），`BASELINE_CACHE` 为 20261014 三语运行核验过的 Dev baseline。
- L1–L3 都是模拟输入，按 `simulationOnly` 标记，不是机器质检或人工审核的内容。
- 先跑了一次不带 `--execute` 的本地预检（e2e-20261014T032129Z），通过后才正式执行。

## 结果和结束信号

- 交付工作流 `pass`；浏览器冒烟 `pass`（`--no-session`）；测试页 `mockup-dev-clip-e2e-20261014T032153Z`。
- 两次部署的 firebase-tools 回执仍是 `projects/548454657719/sites/…/versions/<id>`；`deployment-attempt-v2.json` 直接记为 `deployed`，`newVersion` 为 `sites/…/versions/7a141e958a2b42f5`（资产）和 `…/ffa7471d8089a19a`（目录）。不需要对账，#398 修复有效。

## 耗时

build-inputs 9 秒、baseline 7 秒（缓存命中）、预检 3 秒、执行 173 秒。上一次（e2e-20261013T034422Z）为 9、20、3、171 秒。

## 错误

无。

## 占用资源之后才暴露的错误

无。

## 遗留状态

Dev 上新增两个 Hosting 版本，当前线上为 `ffa7471d8089a19a`；隔离测试页只在 v4 目录中，v3 人工投影的默认页未变。

## 外部可见的变化

- Dev Hosting：两次部署，证据见 `workflow/*/deployment-attempt-v2.json`。
- 生产：无变化。
- 设备播放、场地验收：`not_run`。

## 后续

无新增。
