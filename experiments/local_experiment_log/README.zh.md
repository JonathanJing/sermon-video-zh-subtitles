# 统一日志：本地参数实验扩展

本扩展将预加载、batch、时钟和产物测量绑定到已有 accounting 事件。正式合同仍为 `sermon-workflow-accounting-v3` / `sermon-accounting-log-contract-v1`，直接复用仓库 `scripts/sermon_log_contract.py` 和对应 schema，不维护第二份生产 validator、writer、profile 或 outbox。

L1 是英文事实与锚点，L2 是目标语言文字，L3 是音频与同步，L4 是发布与播放。执行主机使用独立 host/component 字段。局部 TTS 参数实验属于 L3，复用冻结的 L1/L2 输入，不伪造 L4 发布。定义见[四层合同](../../docs/multilingual-production-interfaces.zh.md)。

## 接入与身份

`canonical_bridge.convert(measurement, context, start=None)` 接收调用方已有 run/workflow/workUnit/attempt/event/producer/span/trace/clock 身份和分类字段。trace 沿用 profile 的 run 绑定算法，attemptId 是字符串身份；可选 attemptNumber 是次数。不得使用 fixture 的身份生成方式创建生产身份。

正式事件使用既有 stage_started/stage_finished/workload。详细参数放在 `sermon-local-experiment-measurement-v1` sidecar，正式事件的 `metrics.experimentObservationSha256` 绑定其 canonical JSON hash。`verify_pair` 核对 hash、身份、job、已有 attemptNumber、业务层和证据类型，拒绝 synthetic→current_execution 的提升。实验参数不能改变原内容包、付费请求或缓存身份。

接入者应先从当前 accounting/profile 获取 context，调用适配器，再由现有 writer/outbox 持久化正式 facts 和受限的 sidecar。纯转换不直接写生产 accounting，不提交任务或授予执行、审核、发布权限。云端 DAG 可复用这套适配器；完整工作流的状态投影继续使用现有项目工具。

此 PR 未连接生产采集 hook 或 MacBook 端，未实现 resident worker 或新的语音任务 API。已有 Job DB 仍是任务状态权威来源。

## 计时与有效比较

- 单调时钟只在同一 clock domain 内相减；UTC 用于关联，重启换 producer/clock。请求完整回收、准入/排队、加载、推理、写盘和返回分别测量，不相加重叠 spans。
- preload session 的 load 只计一次，trial 通过 links 引用同一 worker/PID。报告 session 完整成本，摊销标为计算值；first generation 与 subsequent generation 分开。
- 同一比较组固定 model/code/runtime/sample、单位顺序、精度和生成参数，只改变 batch 与 load_policy。实际 batch 必须覆盖冻结 units，缓存、缺字节证据、质量失败或异步 CUDA 提交计时不能进入速度分组。
- fixed_sample 必须完整生成并核验；wall_budget 仅计截止前已完成且通过检查的 units。两种三分钟口径不得混用。保留预算外成本。
- 等价重复可去重，冲突、序号缺口、未闭合 spans 阻断汇总。GPU/进程 UMA 与系统占用不是可相加的内存视角；不可得为 null。音频检查与人工听审分别记录。

审计只验证证据一致性，不独立证明硬件执行、生产部署、资源隔离或人类验收。所有 example 数据均为 synthetic，模板中的 null 不是已配置值。日志不写凭据、完整环境或原始正文。

## 离线入口

在仓库根目录使用已装有 requirements 中 jsonschema 的 Python：

```sh
python -m unittest discover -s tests -p test_local_experiment_log.py -v
python -m experiments.local_experiment_log.export_contract --out-dir /new/templates
python -m experiments.local_experiment_log.canonical_bridge \
  --measurements experiments/local_experiment_log/example/events.synthetic.jsonl \
  --contexts experiments/local_experiment_log/example/contexts.synthetic.json \
  --out /new/events.canonical.jsonl
python -m experiments.local_experiment_log.audit_logs \
  --manifest experiments/local_experiment_log/example/manifest.json \
  --logs experiments/local_experiment_log/example/events.synthetic.jsonl \
  --canonical /new/events.canonical.jsonl --out /new/audit.json
```

也可直接执行脚本的绝对路径，入口会从自身位置定位仓库，不要求当前目录为仓库根。转换输出与模板目录必须是新路径；审计不能覆盖输入。真实实验必须提供 canonical facts，校验失败不生成速度汇总。

## 独立工具部署

部署是显式操作，与采集和模型运行分开。build 复制本扩展及当前仓库只读 validator/schema 到版本包，必须明确提供 canonical source commit；文件 hashes 以实际打包字节为准。install 校验整个包后更新本工具专用 current，保留旧 release 和回执；不切换 Hub/Spark 服务，不动 gate、任务 DB 或 GPU。

```sh
python -m experiments.local_experiment_log.deploy_tools build \
  --source . --canonical-source-pin <40-hex-commit> \
  --bundle /new/log-tools.tgz --receipt /new/build.json
python experiments/local_experiment_log/deploy_tools.py install \
  --bundle /new/log-tools.tgz --root /isolated/log-tools \
  --receipt /isolated/log-tools/receipts/install.json
python /isolated/log-tools/current/experiments/local_experiment_log/deploy_tools.py verify \
  --root /isolated/log-tools/releases/<release-id>
python /isolated/log-tools/releases/<release-id>/experiments/local_experiment_log/deploy_tools.py rollback \
  --receipt /isolated/log-tools/receipts/install.json
```

rollback 只恢复回执里的工具指针，拒绝覆盖之后的更新，不删除版本。安装目录祖先不得是 symlink；临时目录应先解析为实际路径。已有部署是单独的历史工具包，见[历史摘要](../../docs/evidence/2026-10-01-local-experiment-log/deployment-summary.json)。本 PR 将源码改为仓库 package 和共享 validator 引用，不能把历史包 hash 当作本 PR 代码已部署的证据。

真实三分钟实验的矩阵、准入和质量条件见[本地实验协议](../../docs/local-preload-batch-experiment.zh.md)。不扩大 CPU gate，不使用 legacy SSH GPU launch 绕过 scheduler；未获得资源窗口或语音准入时，只继续离线准备。
