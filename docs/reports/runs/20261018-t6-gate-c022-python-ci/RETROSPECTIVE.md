# 复盘：20261018-t6-gate-c022-python-ci

## 结论先行

交付类型：代码测试。PR #1036 当前 head `c0224028` 的 [Python CI 39096320227](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39096320227) 终态成功：8 个 root 分片及汇总 `unittest` 全部成功，native/shared client contracts 按范围跳过。代码与安全审查同 head 均无发现。本报告不证明正式三语 Layer 2 或旧实验完成。

## 总时间

本地摘要没有完整分片计时；工作流页面保留 job 时间。不声称总耗时或性能改善。

## 各层模型、耗时与速度

L1–L4 真实生产均 `not_run`。无模型、token、音频、Spark 或费用。

## 错误

当前 head 的 Python CI 无失败。旧提交的 Python 流程因后续提交抢占而取消，分别见 #1040、#1046；取消后的聚合门禁失败不是当前提交的单测结果。

## 可以改进的地方

合并前按精确提交核对全量 CI 与身份代，并保留已冻结正式运行和历史实验计划的旧 checkout；新代码身份必须由新计划绑定。

## 实际覆盖范围

完整 Python CI：`changes`、8/8 root 分片与 `unittest` 成功；native/shared client contracts 跳过。另有本地 strict gate、schema 绑定、W 与 Layer 2 代码身份比较报告 #1035、#1037、#1045、#1052，以及当前头 Prefect mock 报告 #1051。

## 遗留状态

PR #1036 仍为草稿。正式三语 Layer 2 仍活跃；历史实验快照按用户决定保留只读，未来重启另建计划，见 #1050。不得把本 CI 当成准入或内容验收。

## 外部可见的变化

`not_run`：无 Dev 发布、TestFlight、HTTP 读回、设备或场地验收。
