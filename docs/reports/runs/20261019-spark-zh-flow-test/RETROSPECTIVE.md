# 复盘：2026-10-19 Spark 中文 Layer 3 流程测试

## 结论

测试证明了 S（TTS）→ compact → A（ASR 筛查）能跑通，但 66 分 57 秒的会话里约 **31 分钟**花在两次可预检的失败上（8 副本内存门限、partial reuse 不完整）。真正的有效测试约 29 分钟。package 在最后一步被旧 QC waiver 挡住，这一步本该在开 Spark 前预检。

## 时间账

| 段 | 时间（UTC） | 耗时 | 结果 |
|---|---|---|---:|---|
| 会话 begin | 19:21:42 | — | exclusive_ready，126 GB |
| test-1（8 副本） | 19:23:06–19:30:34 | 7m28 | 内存门限，742 WAV |
| test-2（1 副本，reuse test-1） | 19:31:19–19:55:01 | 23m42 | `Incomplete previous render evidence: u027` |
| test-3（1 副本，fresh） | 19:55:22–20:21:24 | 26m02 | 402 单元，1108 WAV；assembly exit=1（1×，已知） |
| compact | 20:22:10–20:24:01 | 1m51 | exit 0 |
| ASR screen | 20:25:54–20:27:27 | 1m33 | exit 0 |
| package | 20:27–20:28 | <1m | exit 1，旧 QC waiver |
| session finish | 20:28:19–20:28:39 | 20s | 恢复 llama healthy，closed |

- 有效：test-3 + compact + screen ≈ **29m26**。
- 失败尝试：test-1 + test-2 ≈ **31m10**（47%）。
- 1 副本吞吐约 **15.4 单元/分钟**；402 单元约 26 分钟。

## 做对了什么

1. 开跑前用 `inspect` 确认没有活跃会话、没有未知 dispatch；没有直接接管旧会话。
2. 8 副本失败后切 1 副本，内存稳定，没有再次触发门限。
3. 把 1× 拼接 exit=1 正确识别为 E13 设计行为，继续 compact，没有误判为渲染失败。
4. compact 和 ASR screening 都成功，流程走到 package 前。
5. finish 后 llama-server 恢复 healthy，没有留下独占会话。
6. 保留了 exit 码、render/screen manifest 和错误原文。

## 出了什么问题

| 问题 | 现象 | 根因 | 代价 | 下次怎么避免 |
|---|---|---|---|---|
| 8 副本内存门限 | `MemAvailable is below the TTS replica reserve` | 用了生产 helper 的 8 副本；测试前没做内存计划 | 7m28 | 测试默认 1 副本；8 副本只在明确内存预算下用 |
| partial reuse 不完整 | `Incomplete previous render evidence: u027` | test-1 失败留下不完整单元；test-2 直接把它当 reuse root | 23m42 | reuse 前校验每个单元三件证据；不完整就清掉或换新 root |
| 整篇 402 单元做测试 | 1 副本 26 分钟 | 没有小分段入口；formal renderer 只收整篇 | 26m | 用 preview lane/3–10 组做流程测试，整篇只在验收时跑 |
| package 被旧 waiver 挡住 | `Waiver was issued under a QC implementation other than the current one` | 文本 waiver 是旧 QC 闭包签的；开 Spark 前没核对 | 最后 1 分钟失败，前面 29 分钟白做 | 先跑 package preflight；waiver 不匹配就重签，不先开 Spark |
| 测试目录 sprawl | test-1/2/3 三个目录，partial 未清 | 每次失败换目录，没有统一 run record | 清理成本 | 一个 test run 目录，失败 attempt 子目录，统一 manifest |

## 瓶颈

1. **1 副本吞吐**：约 15 单元/分钟，402 单元 26 分钟；8 副本快但内存门限。
2. **容器启动/组装**：test-3 容器启动到出单元约 1–2 分钟；assembly 在 1× 超长时必失败，必须 compact。
3. **partial reuse 的完整性检查**：一个坏单元阻塞整轮 resume。
4. **package 的 QC 身份**：文本 waiver 与当前 QC 闭包绑定；换代码后旧 waiver 立即失效。

## 重复出现的模式

- **内存门限**（10-18 的 E11）：8 副本 + reserve 仍然会触发；测试要显式 1 副本。
- **1× 拼接 exit=1**（E13）：每次正式渲染都会出现，compact 解决，不是失败。
- **QC/waiver 闭包漂移**（E5/E23 类）：旧 waiver 在新 QC 下无效；每次换 QC 都要重签。
- **partial reuse 不预检**：这次新增；失败后直接把 partial 当 reuse root。

## 下次最短测试路径

1. **开 Spark 前**（零成本）：
   - 检查 text waiver 的 `implementationSha256` 是否等于当前 QC 闭包；不等就重签。
   - 检查 `--reuse-from` 每个单元是否有 intent/commit/audio 三件；缺一个就清掉。
   - 明确副本数：测试 1 副本，生产 8 副本需内存计划。
2. **小分段**：3–10 组，1 副本，batch1；优先用 preview lane（`--group-id`），不跑整篇。
3. **流程顺序**：render → compact → screen → package preflight；package 通过后再考虑 audio QC/发布。
4. **会话预算**：测试会话 ≤ 30 分钟；结束必须 finish 并确认 llama healthy。
5. **记录**：一个测试 run 目录 + attempt 子目录 + manifest；不要三套并行目录。

## 下一步

package 已成功（`audio-package-c4.json`，candidate，402 units）。下一步是音频质检/音频 waiver；需要当前 QC 的音频检查和 Spark/API 证据，不再需要重新签 text waiver。
