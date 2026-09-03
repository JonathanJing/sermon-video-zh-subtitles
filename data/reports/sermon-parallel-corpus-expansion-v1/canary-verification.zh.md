# Mariners train/dev 扩展 canary 验证

状态：`pass_canary_needs_pipeline_revision`

- 完成：6 篇，265 段
- 模型审核：pass 221；needs_audio_review 44；must_fix 0
- 剩余 train/dev：153 / 159
- test 保持未触碰：18 / 18
- 可观察成功 receipt：174 个；API 累计等待/内容时长比 1.015x
- 重复成功阶段-段绑定：78（来自批次降级和恢复）

## 判定

6 篇内容和独立审核均完整，split、来源哈希、逐段绑定和 test 隔离通过。
当前同步调用存在显著尾延时、人工中断和批次降级，因此在改成受控异步/Batch调度并补齐provider billing成本前，不自动启动剩余153篇。
模型审核结果可以作为用户指定的文本质量基线，但仍不是音频听校、Silver/Gold或训练授权。

## 逐篇

| video | split | segments | pass | audio | must-fix | receipts | duplicate bindings |
|---|---|---:|---:|---:|---:|---:|---:|
| `ArgSmQwhWp0` | train | 36 | 31 | 5 | 0 | 51 | 72 |
| `Lskg54LVBy4` | train | 49 | 43 | 6 | 0 | 26 | 0 |
| `XFbturPLU7o` | dev | 46 | 32 | 14 | 0 | 27 | 6 |
| `nre_3kR0PHk` | dev | 50 | 42 | 8 | 0 | 38 | 0 |
| `oDIIjVpJzFA` | dev | 48 | 43 | 5 | 0 | 18 | 0 |
| `vR9xKMOElQg` | train | 36 | 30 | 6 | 0 | 14 | 0 |

## 限制

- Interrupted in-flight requests without returned receipts are not observable here and may still appear in provider billing.
- 本报告不把本地token receipt直接换算成美元；最终成本门禁应使用provider billing export核对。
- 所有产物继续保持 `trainingEligibility=blocked`。
