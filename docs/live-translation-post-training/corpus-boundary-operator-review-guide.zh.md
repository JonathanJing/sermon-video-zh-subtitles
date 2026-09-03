# 三篇 POC sermon-only 边界音频审核指南

日期：2026-08-31

状态：等待指定审核者听源音频；本文只缩短操作路径，不代表批准

## 1. 需要做的决定

请分别打开下面六个 YouTube 时间点，从链接位置前后连续听约 20–30 秒，判断 v2 cue 是否是完整证道 spoken unit 的开始或结束。

| 视频 | 边界 | 音频入口 | v1 | v2 建议 | 判断重点 |
|---|---|---|---|---|---|
| `cFLQLjzbnVg` | 开始 | [从 02:06 播放](https://www.youtube.com/watch?v=cFLQLjzbnVg&t=126s) | `cue_00068` | `cue_00067` | 是否应包含 “Super exciting. I’m so glad that you were a part” 这整个承接单元 |
| `cFLQLjzbnVg` | 结束 | [从 29:14 播放](https://www.youtube.com/watch?v=cFLQLjzbnVg&t=1754s) | `cue_00773` | `cue_00773` | 信息祷告的 Amen 后是否立即转入敬拜/通用 outro |
| `mIyioBLQmJ0` | 开始 | [从 00:00 播放](https://www.youtube.com/watch?v=mIyioBLQmJ0&t=0s) | `cue_00005` | `cue_00001` | “Hi, Mariners online” 与讲员自我介绍是否属于本篇信息 |
| `mIyioBLQmJ0` | 结束 | [从 30:33 播放](https://www.youtube.com/watch?v=mIyioBLQmJ0&t=1833s) | `cue_00710` | `cue_00710` | “all that he is” 后是否开始通用线上 outro |
| `wxcIGSolCvc` | 开始 | [从 18:32 播放](https://www.youtube.com/watch?v=wxcIGSolCvc&t=1112s) | `cue_00188` | `cue_00186` | 讲员问候与 “share God’s word” 是否是本篇证道开场 |
| `wxcIGSolCvc` | 结束 | [从 48:48 播放](https://www.youtube.com/watch?v=wxcIGSolCvc&t=2928s) | `cue_00886` | `cue_00886` | 邀请祷告/歌唱结束后是否已进入回应诗歌 |

YouTube 时间点只能帮助定位；最终 cue 仍应对照审核包中的逐 cue 时间轴与字幕。

## 2. 审核文件

每篇的完整上下文和决定模板位于已忽略目录：

```text
data/derived/sermon-boundary-operator-review-v2/<videoId>/
  review.zh.md
  review-packet.json
  operator-decision.template.json
```

对每篇：

1. 复制 `operator-decision.template.json` 为 `operator-decision.json`。
2. 填写实际选择的 `selectedStartCueId` 和 `selectedEndCueId`；不必机械接受 v2。
3. 填写审核者、带时区的 `approvedAt`、可复核的 `decisionReason`。
4. 只有实际听完音频后，才设置 `audioReviewCompleted=true` 和 `status=approved`。
5. 不修改 `review-packet.json`、源字幕或其中任何 hash。

完成三篇后运行：

```bash
uv run --with-requirements requirements.txt python \
  scripts/apply_sermon_boundary_approvals.py
```

脚本只会在三篇决定齐全、cue 合法、时间带时区、音频审核已声明完成且 source/review hash 全部匹配时，生成新的 approved boundary root。它不会覆盖 v1/v2 历史。

## 3. 批准后的下一步

批准边界并不批准翻译。还需要：

1. 以 approved boundary 生成新的 POC 版本。
2. 从新版本重新导出 117 条左右的 review bundle；段数可能因重切分变化。
3. 对新 hash 逐条做英文听校与中文双语审核。
4. 再生成 Silver/Gold 质量目录；训练权和教师输出使用许可仍单独判断。
