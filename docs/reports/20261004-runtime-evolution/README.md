# 运行演进审计证据

主报告：[从冻结代码到临场调整](../20261004-runtime-evolution-retrospective.zh.md)。

- [L1／L2专项](text.zh.md)：缓存根错误、实际并发、controller接入与代码身份。
- [L3专项](audio.zh.md)：实际参数、收据热点、CPU重组、事务恢复及容量计量。
- [交付专项](delivery.zh.md)：发布代码补丁、运行桥接、消费者与环境绑定。
- [输入与摘要](inputs.json)：相对RUN路径与SHA、原始request／response身份hash、参数与热点计数。无prompt、response正文、私人审批或媒体。

## 离线复算

需有Git历史对象和本地ignored RUN；标准库Python 3.10+。命令从仓库根运行，只读取Git和已有文件，不联网、不调用模型、不改生产产物。输出保留在新的ignored审计目录；完整输出仍需投影审阅后才能提交。

```sh
RUN_DIR=artifacts/post-live-runs/2026-10-04/resi-69ba7a66
AUDIT_DIR="$RUN_DIR/runtime-evolution-audit-v1/reproduced"
CODE_DIR=docs/reports/20261004-runtime-evolution
python3 "$CODE_DIR/audit_text_runtime.py" --run-dir "$RUN_DIR" --repo-dir . --out-dir "$AUDIT_DIR/text"
python3 "$CODE_DIR/audit_delivery.py" --run-dir "$RUN_DIR" --repo-dir . --out-dir "$AUDIT_DIR/delivery"
python3 "$CODE_DIR/audit_identity_audio.py" --run-dir "$RUN_DIR" --repo-dir . --out-dir "$AUDIT_DIR/identity-audio"
```

文本脚本检查46账本SHA、全部16组重复请求的原始缓存、response hash／usage与账本对应，复算API区间重叠。交付脚本读精确Git版本与RUN桥接。身份／音频脚本验证本索引全部文件SHA、74个workflow观察与Git blob差异、两次缓存重组receipt子阶段总和、4个staged代码文件与5b2c1ac的字节一致性。

`inputs.json` 是可审阅快照，输入缺失或变化应明确报错，不自动替换成新版本。没有本地RUN时只能查看报告和摘要，不能复现原始证据核验。来源为历史执行记录，不能证明线上当前状态、生产提速或声音质量。
