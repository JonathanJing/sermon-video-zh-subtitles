# 2026-10-19 Spark 中文 Layer 3 流程测试

- **类型**：本地 Spark 流程测试；不是发布、不是人工听审、不是 L4 页面验收。
- **测试代码**：Spark 侧 `repo-d1314424`（与 10-18 运行同一冻结代码）；本地 package/QC 用 `dev c03b9416`。
- **报告基线**：`dev c7b3397e`（整理报告时的 `dev`；测试结果不外推到该提交）。
- **结论**：S（TTS）→ compact → A（ASR 筛查）→ package 走通；最终产出 `audio-package-c4.json`（candidate，402 units）。text waiver 无需重签。

## 一、会话

| 会话 | 起 | 止 | 结果 |
|---|---|---|---|
| `test-zh-audio-20261019` | 2026-10-19T19:21:42Z | 2026-10-19T20:28:39Z | `closed`；llama-server 恢复 healthy |
| `test-zh-audio-2-20261019` | 2026-10-19T21:21:07Z | 2026-10-19T21:26:02Z | `closed`；llama-server 恢复 healthy |

两次都先停 `llama-server` 等单元，finish 后 readback 恢复。没有留下独占会话。

## 二、时间线

| 段 | 时间（UTC） | 耗时 | 结果 |
|---|---|---|---:|
| test-1：8 replicas | 19:23:06–19:30:34 | 7m28 | `MemAvailable is below the TTS replica reserve`，742 WAV |
| test-2：1 replica + reuse test-1 | 19:31:19–19:55:01 | 23m42 | `Incomplete previous render evidence: translation-chunk-0009-u027` |
| test-3：1 replica fresh | 19:55:22–20:21:24 | 26m02 | 402 units，1108 WAV；assembly exit=1（1× 超长，已知） |
| compact c1 | 20:22:10–20:24:01 | 1m51 | exit 0 |
| ASR screen c1 | 20:25:54–20:27:27 | 1m33 | exit 0 |
| package（旧代码） | 20:27–20:28 | <1m | exit 1：waiver QC 实现不匹配 |
| compact c4（`--trim-trailing`） | 21:21–21:23 | ~2m | exit 0 |
| ASR screen c4 | 21:24–21:26 | ~2m | exit 0 |
| package c4（`dev c03b9416`） | 21:26–21:28 | ~2m | exit 0，`audio-package-c4.json` |

有效测试约 30 分钟；test-1/test-2 的两次失败约 31 分钟，占会话 47%。

## 三、每一步的结果

### 3.1 Spark 渲染

- test-1：8 replicas，742 WAV 后触发内存保护线。
- test-2：1 replica，复用 test-1 的 partial root；`u027` 的 intent/commit/audio 三件不齐，整轮 resume 被拒绝。
- test-3：1 replica fresh，402 单元全部合成，1108 WAV；约 15.4 单元/分钟。
- assembly exit=1：`Measured target audio exceeds 1x clip schedule`；这是已知 E13，compact 解决，不是渲染失败。

### 3.2 compact / ASR

- compact c1：exit 0；但默认没有 `--trim-trailing`，trim evidence 缺 trailing 字段。
- ASR screen c1：exit 0，产出 `render-manifest-screened-c1.json`。
- compact c4：按 10-18 原链参数重做：

```bash
--trim-trailing --padding-seconds 0.03 --inter-utterance-gap-seconds 0 \
--reaction-lag-seconds 0 --tail-overrun-seconds 1.0
```

- screen c4：exit 0，产出 `render-manifest-screened-c4.json`。

### 3.3 text waiver

- 当前 `dev c03b9416` 的 text waiver 实现哈希是 `51e2b9ca…`，与 10-18 的旧 waiver 相同。
- 第一次 package 报 `Waiver was issued under a QC implementation other than the current one`，原因是 package 用了主 checkout 的旧代码，不是 waiver 过期。
- 用 `dev c03b9416` 的 package 代码后，旧 waiver 通过。

### 3.4 重签尝试（没有签发新 waiver）

用新鲜 QC state 跑了一次当前实现的 zh text QC（Codex CLI，约 802 次调用，prefetch 1050.8 秒 + QC 174 秒）：

- 结果 **31 个 failed**；旧 acceptance 覆盖 **25 个**，缺 6 个（u020、u038、u001-u023 等）。
- 没有签发新 waiver；package 继续使用旧 waiver。
- 如果将来要新签，需要先补这 6 组的接受或返修。

### 3.5 package

- 产物：`audio-package-c4.json`
- `status=candidate`，`targetLocale=zh-Hans`，**402 units**
- track `fba18e8fc7f95b30caca568ffa3e223144dd4f0a19721f00ffc216938549674d`
- captions `bdde6aba6c395fda60d5178fc6677452d6873b0da9ce4656a747368bbbe22ec8`
- machineScreening `requires_review`，coverage 1.0
- `package4.exit` = 0

## 四、发现

1. **1 replica 稳定，8 replicas 会触发内存门限**；测试/小分段显式用 1 replica。
2. **1× 拼接 exit=1 是设计行为**，compact 后成功。
3. **partial reuse 必须先校验三件证据**；一个坏单元会阻塞整轮 resume。
4. **compact 必须带 `--trim-trailing` 等参数**，否则 package 报 `Edge silence trim duration differs from unit 0`。
5. **package 代码版本必须与 render/compact 兼容**；主 checkout 的旧代码会误报 waiver 不匹配。
6. **text waiver 当前仍有效**；重签不是必需，且新 QC 会多出 6 个未接受的失败组。
7. 1 replica 吞吐约 15.4 单元/分钟；402 单元约 26 分钟。

## 五、边界

- 没有 L4 页面、海报、公告或发布。
- 没有音频 QC/音频 waiver；package 仍是 `candidate`。
- 没有人工听审或设备/场地验收。
- test-1/test-2 的 partial 输出留在本机；原始日志未提交。
- 没有修改文字，没有修改生产站点。

## 六、证据哈希

| 文件 | SHA-256 |
|---|---|
| `audio-package-c4.json` | `b7027f07fbd62ba9611e7dcd85c1919f0d7a26025a14c7405990baa579904ee8` |
| `render-manifest-screened-c4.json` | `8357bc992f6e097ee30a429b5f842b99d27032c5ca67caba46a59a17949b8e40` |
| `compact4.exit` / `screen4.exit` / `package4.exit` | `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa` |
| 旧 zh text waiver | `2623046e4794dce92dc8a799551c753ff5260425e85e21d03838cb192ca4eed2` |
| 重签尝试 summary | `d63f912d30a85e1685c1f0a1a0f586e8bfda2180e41e876d298f244a7813d6ee` |

本机证据目录（不提交）：`artifacts/weekend-live/layer3-test-zh-20261019c/`、`artifacts/local-runs/20261019-spark-zh-flow-test/`。

## 七、下一步

1. 音频 QC / 音频 waiver：package 仍是 candidate；下一步不是 Spark TTS，而是当前 QC 下的音频检查。
2. 若要重签 text waiver：补 6 个未接受组的接受或返修。
3. 若要 production 化：把“1 replica 测试 / 8 replica 生产”和 `--trim-trailing` 参数写进 test profile。
