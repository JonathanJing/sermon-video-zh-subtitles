# 复盘：20261014-post-393-three-locale

数据见同目录 INDEX.md 和 manifest.json。本轮接续 [20261013-post-merge-start-tools](../20261013-post-merge-start-tools/RETROSPECTIVE.md)，在 dev 12b5a1f8 上运行（已合并 #393，韩语读法规则 v4）。Spark 上的代码为 `repo-12b5a1f8`，质检实现哈希 `ba7e28cd…`。

## 实际覆盖范围

- **L1、L2**：复用上一轮的英文来源和三份 Layer 2 候选（中文用 r2 修订）。L2 代码改动不影响已生成候选；质检授权绑定来源、锚点、政策，不绑定候选。
- **文本质检、L3、音频质检**：三语在新实现哈希下全部重做，每语一个新预算根和新 state。新的 Layer 3 配置绑定读法规则 v4，三语的配音作业都重新生成。
- **L4**：三语机器质检页发布到 Dev 隔离测试页 `mockup-dev-clip-v4-20261013`。
- `humanApproval=false`，`review=waived`。Layer 2 的人工门按用户的隔离测试授权默认放行，不是人工审核。

## 结果和结束信号

| 语言 | 文本质检（校准） | 初筛 | 音频质检（校准） |
|---|---|---|---|
| ko | text waiver（92/92） | machine_screened pass | audio waiver（177/177） |
| es | text waiver（95/95） | candidate requires_review | audio waiver（179/179） |
| zh-Hans | text waiver（91/91） | machine_screened pass | audio waiver（177/177） |

- 上一轮失败的韩语句子"그렇기 때문에 8장을 보면"，这次读成"팔장"，通过。
- 西语初筛把部分单元标为待复核，音频质检放行；与上一轮相同。
- **Dev 交付**：工作流 `diagnostic_dev_http_verified`，九个阶段全部 `succeeded`；浏览器冒烟 `pass`（`--no-session`）。
- **Spark 会话**：`clip-v4-20261013` 第一次 begin 即成功，已 `finish`，状态 `closed`。

## 耗时

| 阶段 | 本轮 | 上一轮 |
|---|---|---|
| 文本质检＋校准（每语） | 102–114 秒 | 96–115 秒 |
| Spark 每语：渲染、压缩、初筛、打包 | 85–87、16–17、37–40、3–4 秒 | 相同 |
| 音频质检（共用根） | 133–163 秒；校准预取 3.1–3.2 秒 | 131–154 秒 |
| 三语质检与 L3 合计 | 约 20 分钟（串行） | — |
| L4 工作流 | 255 秒，其中两次部署各约 52 秒；回读 4.2 秒 | 约 4.5 分钟，另因 CDN 传播停两次 |

发布后回读一次通过，没有因 CDN 传播停下（#379）。

## 错误

1. **Hosting 版本回执格式。**
   - 现象：firebase-tools 15.30.2 返回 `projects/548454657719/sites/…/versions/<id>`，`deployed_version` 只接受 `sites/…`。两次部署都成功，却被记为 `outcome_unknown`。
   - 处理：按规则不重发，用 `guarded_hosting_publish.reconcile()` 对账。确认线上版本就是这次部署的版本，v3、v4 目录与封存一致，然后释放发布锁，续跑工作流。
   - 修复：#398，并加了回归测试。
   - 背景：这项严格校验是合并评审时（54bf6d70）新加的，这次是第一次在真实部署上运行。
2. **CI 偶发失败**：#393 的 `test_groups_run_concurrently_in_the_worker` 一次失败，靠 50 毫秒睡眠观察并发，与 #393 无关，重跑通过。已另开待办任务。

## 占用资源之后才暴露的错误

版本回执问题只能在真实部署后暴露。#398 的测试固定了实测的 CLI 输出格式。Dev 部署前可以先用 `firebase-tools --version` 记录版本，CLI 升级时重新核对回执格式。

## 遗留状态

- Dev 上新增两个 Hosting 版本：`4c237bd274635377`（资产）和 `be52f85745d751dc`（目录，当前线上）。测试页 `mockup-dev-clip-v4-20261013` 在 v4 目录中；v3 人工投影保持原默认页。
- 上一轮 `clip-test-20261013-merged` 的韩语质检授权未用完，已因实现哈希改变而失效，不再续用。
- Spark 会话已关闭，没有未结束的 job hold。

## 外部可见的变化

- **Dev Hosting**：两次部署，证据在 `l4/workflow/*/deployment-attempt-v2.json`，均已对账为 `deployed`。
- **生产**：无变化。
- **设备播放、场地验收**：`not_run`。

## 预算

本轮按账本计 1.029 美元：

| 项目 | 美元 |
|---|---|
| 质检 ko | 0.353 |
| 质检 es | 0.304 |
| 质检 zh-Hans | 0.371 |

- 另有 66 次 `gpt-transcribe` 没有价格。
- 规划时把上一轮无价格转写按最高预留（0.62 美元）计入：已结算 12.9 美元起，结束时 13.93 美元，总额 20 美元。

## 后续

- #398 合并（用户）。
- 二级 ASR 结算没有价格（上一轮已列），规划时按预留保守计入；待开 backlog 条目。
- 韩语章号读法预检（上一轮已列），待开 backlog 条目。
