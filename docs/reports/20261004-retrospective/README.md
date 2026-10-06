# 完整复盘的复算入口

主报告：[2026-10-04 完整制作复盘](../20261004-full-production-retrospective.zh.md)。

| 文件 | 用途 |
|---|---|
| [versions-and-cache.zh.md](versions-and-cache.zh.md) | 34轮L2、触发原因与结果复用 |
| [audio-and-resources.zh.md](audio-and-resources.zh.md) | 单句时长、排程、ASR与内存guard |
| [handoffs-and-release.zh.md](handoffs-and-release.zh.md) | 审批、启动、部署及最终身份链 |
| [review.ipynb](review.ipynb) | 已执行的关键核对代码与输出，只用Python标准库 |
| [summary.json](summary.json) | 经投影的计数、输入相对路径与SHA；无原始对话或审批正文 |
| [audit_versions.py](audit_versions.py) | 从既有accounting索引复算版本／原因／精确payload重复 |
| [audit_audio.py](audit_audio.py) | 从job、manifest、schedule、receipt复算音频与资源 |
| [audit_handoffs.py](audit_handoffs.py) | 从审批和HTTP收据复算身份链及时间覆盖 |
| [audit_operations.py](audit_operations.py) | 从授权的会话日志复算聚合操作；不导出命令／消息原文 |
| [export_summary.py](export_summary.py) | 只导出审阅所需字段，不直接提交完整运行输出 |

## 本地复跑

从仓库根目录执行，需要本次ignored RUN产物；这些文件没有上传Git。缺少RUN时，仍可打开notebook核对已提交聚合，但不能独立重建原始证据。Python 3.10+，仅标准库，无模型／网络调用。

```sh
RUN_DIR=artifacts/post-live-runs/2026-10-04/resi-69ba7a66
AUDIT_DIR="$RUN_DIR/full-retrospective-v1/reproduced"
CODE_DIR=docs/reports/20261004-retrospective
python3 "$CODE_DIR/audit_versions.py" --run-dir "$RUN_DIR" --out-dir "$AUDIT_DIR/versions"
python3 "$CODE_DIR/audit_audio.py" --run-dir "$RUN_DIR" --out-dir "$AUDIT_DIR/audio"
python3 "$CODE_DIR/audit_handoffs.py" --run-dir "$RUN_DIR" --out-dir "$AUDIT_DIR/handoffs"
```

音频脚本可加 `--session-log /path/to/authorized-session.jsonl`，只读取限定时段的工具输出以核验内存guard。未提供时 `historicalStderrStatus=not_provided`；这一步缺失不能变成“未发生内存失败”。当前提交摘要由提供了对应日志的执行生成。

操作审计需用户授权的会话目录及主线程ID，按parent_thread_id追踪子线程；只输出聚合、命令hash、窗口内时间和输入文件hash。不要提交原始日志或未经检查的输出。静态解析不是JavaScript执行器：动态命令单列unknown，混合命令按脚本中的优先级归一类。

```sh
python3 "$CODE_DIR/audit_operations.py" \
  --sessions-root /path/to/authorized-sessions \
  --root-thread-id ROOT_THREAD_ID \
  --start 2026-10-04T01:46:31.026Z \
  --end 2026-10-04T19:00:55.959Z \
  --out "$AUDIT_DIR/operations/metrics.json"
python3 "$CODE_DIR/export_summary.py" \
  --input-dir "$AUDIT_DIR" --output "$AUDIT_DIR/summary.json"
```

将新摘要与提交版对比后再更新报告。会话文件可能继续增长，所以完整输入文件SHA随快照变化；操作计数必须以相同冻结窗口比较。音频和审批hash也必须与同一生产版本绑定。脚本输出可能包含原始产物中的本地路径或审核正文，仅 `export_summary.py` 的字段投影作为可提交摘要，并仍需检查。

`review.ipynb` 可从本目录或仓库根运行。它核对：L2原因表与逐轮表闭合、三次0调用迁移、u172局部跳升、三语474句覆盖、审批与HTTP身份、外层调用分母和重复进度查询状态。它不重听音频、不重新访问线上、不测GPU或设备，不证明性能改善。
