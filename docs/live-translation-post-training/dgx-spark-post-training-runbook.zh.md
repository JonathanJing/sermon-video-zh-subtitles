# DGX Spark 证道翻译后训练运行方案

日期：2026-08-30

状态：设计 runbook，命令尚未在目标 DGX Spark 执行

适用范围：单台 128GB DGX Spark，对 Qwen3.5 4B/9B 做 LoRA/SFT 与离线 replay

## 1. 运行结论

首轮采用 NVIDIA 官方支持路径：

- 训练框架：NeMo AutoModel 的单 GPU SFT/PEFT 路径。
- 模型：Qwen3.5 4B/9B post-trained 与 Base 对照。
- 方法：优先 BF16 LoRA；QLoRA 是 LoRA 实测出现内存或吞吐问题后的备选。
- 模态：只训练文本路径，冻结 vision tower 和无关多模态模块；实际冻结清单写入 receipt。
- 教师：Terra/Sol 在 Spark 外完成候选数据准备；Spark 默认只读取已发布 Gold 训练轻量学生。Qwen3.8-27B 仅保留为隔离备用教师实验臂。
- 数据：只读、不可变 dataset version；训练输出写入独立 candidate 目录。
- 生产隔离：不得覆盖现有模型、symlink、服务、端口或 benchmark 结果；promotion 是另一个需要明确授权的阶段。

NVIDIA 官方硬件文档列出 DGX Spark 为 128GB LPDDR5x unified memory、273GB/s memory bandwidth。它说明 4B/9B LoRA 和 27B 离线 inference 有装载空间，不证明实际训练吞吐或周日延时。[DGX Spark hardware](https://docs.nvidia.com/dgx/dgx-spark/hardware.html)

NVIDIA 的 DGX Spark NeMo playbook提供 SFT、LoRA 和 QLoRA 示例；NeMo AutoModel 也列出 Qwen3.5 4B/9B recipe。正式运行前仍须在目标 Spark 上验证容器架构、模型支持和当前驱动组合。[DGX Spark NeMo fine-tune](https://build.nvidia.com/spark/nemo-fine-tune/instructions)、[NeMo AutoModel Qwen3.5](https://docs.nvidia.com/nemo/automodel/model-coverage/vision-language-models/qwen/qwen3-5-vl)

## 2. 生产隔离原则

DGX Spark 可能同时承载已有 Qwen/agent 服务。训练是高显存、高功耗工作，不应与生产推理默认并行。

硬规则：

1. 开始前只读记录当前 service、port、process、GPU memory、model path、active symlink 和 health。
2. 默认不停止或修改生产服务；若资源不足，安排明确的 maintenance window，而不是由脚本隐式停止。
3. 训练容器、缓存、数据、checkpoint 和日志使用独立根目录。
4. 训练不写 production model directory，不修改 `spark-agent-current` 或类似 active 指针。
5. POC inference 使用隔离端口，例如现有生产在 `8000` 时使用经确认的 test port；端口必须现场解析，不能只照抄文档。
6. 训练失败只能清理本次 job 的临时资源，不删除共享 cache 或历史 candidate。
7. 从 candidate 到 production 的合并、量化、服务切换和回滚另走 promotion receipt。

## 3. 建议目录

路径在执行前由 operator 确认；不要依赖未解析的 `$HOME`：

```text
/home/achillesjing/sermon-live-training/
  env/
  datasets/
    sermon-simul-ds-v1-poc/
  model-cache/
  configs/
  runs/
    20260830-qwen35-4b-post-lora/
      config.yaml
      preflight.json
      logs/
      checkpoints/
      eval/
      receipt.json
  artifacts/
  quarantine/
```

每个 run 目录只写一次；重跑使用新 run ID，不能覆盖旧 checkpoint 和报告。

## 4. Preflight

### 4.1 机器与软件快照

保存而不是只在终端看：

- DGX OS、kernel、driver、CUDA、Docker/Container Toolkit。
- `nvidia-smi`/系统内存/磁盘/温度/功耗。
- ARM64 架构与目标 container manifest。
- 当前生产进程、service 状态、监听端口和实际 smoke response。
- 可用空间；model cache、dataset、checkpoint 与 merged artifact 需要分别预算。
- 时间同步、网络与 Hugging Face/NGC 访问。

当前 NVIDIA release 可能变化，因此 run receipt 必须记录实际版本，不把本文日期的文档页面当作机器事实。

### 4.2 数据检查

- dataset 目录只读挂载。
- `manifest.json`、split manifest 与所有 JSONL hash 匹配。
- rights receipt 完整率 100%。
- train/dev/test 没有 sermon lineage 重叠。
- 训练 loader 只读取允许的 `reviewStatus` 和 teacher provenance。
- 运行前随机解析至少 100 条样本，检查 UTF-8、schema、长度和 label mask。

### 4.3 模型检查

- model ID 与完整 revision 已批准。
- `LICENSE`、model card、Tokenizer、chat template 和 weight 文件 hash 已归档。
- 只从官方 safetensors/base artifact 开始训练；不把 GGUF 当训练源。
- 首轮先跑未训练模型的 20–50 条 deterministic inference，确认 template 和 `WAIT/WRITE` schema。
- 读取实际 trainable parameter 清单，确认 vision tower/非文本模块为 frozen；若框架仍把它们加入 optimizer，preflight 失败。

## 5. 环境选择

优先使用经过 Spark 验证、按 digest 固定的 NeMo AutoModel 容器，不使用漂移的 `latest`。

官方 Qwen3.5 页面目前示例 `nvcr.io/nvidia/nemo-automodel:26.06.00`，但它只作为候选起点；执行时应解析当前 Spark 支持矩阵和 ARM64 image，记录最终 image digest。单 GPU Spark 不需要 `--nproc-per-node=8`；NeMo 文档说明单 GPU 可省略该参数。

环境 receipt 至少包含：

```json
{
  "containerImage": "nvcr.io/nvidia/nemo-automodel:<validated-tag>",
  "containerDigest": "sha256:...",
  "hostArch": "aarch64",
  "driver": "...",
  "cuda": "...",
  "pytorch": "...",
  "nemoAutomodelCommit": "...",
  "transformers": "..."
}
```

Hugging Face token 等 secret 通过 operator 选择的 secret mechanism 注入；不能写入 config、shell history、日志、receipt 或 Git。

## 6. 训练配置起点

以下是实验起点，不是已调优参数：

| 参数 | 4B LoRA 起点 | 9B LoRA 起点 | 说明 |
|---|---:|---:|---|
| precision | BF16 | BF16 | Spark Blackwell 路径先验证 BF16 |
| sequence length | 1024，必要时 2048 | 1024，必要时 2048 | 实时状态应短，不因模型支持超长上下文而扩大 |
| micro batch | 1–2 | 1 | 以 preflight 实测为准 |
| grad accumulation | 8–32 | 16–64 | 追求稳定有效 batch，不追求单步大 batch |
| LoRA rank | 16/32 bake-off | 16/32 bake-off | 先小后大 |
| LoRA alpha | 32/64 | 32/64 | 与 rank 成对记录 |
| LoRA dropout | 0–0.05 | 0–0.05 | 用 dev loss 与过拟合决定 |
| learning rate | `5e-5`–`2e-4` sweep | `3e-5`–`1e-4` sweep | 不是单一默认值 |
| epochs | 1–3，early stop | 1–3，early stop | 看 held-out sermon，不只看 train loss |
| gradient checkpointing | on/off 实测 | 默认 on | 记录吞吐与内存代价 |
| seed | 至少 3 个 | 至少 3 个 | 小数据方差不可忽略 |

LoRA target modules 不能凭另一个 Qwen 版本猜测。先读取当前 checkpoint module names，并与 NeMo Qwen3.5 recipe 对照；任何 glob 的实际匹配层数写入 receipt。

### 配置骨架

```yaml
run:
  id: 20260830-qwen35-4b-post-lora
  seed: 17

model:
  pretrained_model_name_or_path: Qwen/Qwen3.5-4B
  revision: <approved-full-revision>
  dtype: bf16

data:
  train_manifest: /data/examples/prefix-policy.train.jsonl
  validation_manifest: /data/examples/dev.jsonl
  schema_version: sermon-simul-v1
  max_sequence_length: 1024

peft:
  method: lora
  rank: 16
  alpha: 32
  dropout: 0.05
  target_modules: <verified-qwen35-module-pattern>
  # Add the current NeMo recipe's verified fields that freeze vision/non-text towers.

optimization:
  learning_rate: 0.0001
  micro_batch_size: 1
  gradient_accumulation_steps: 16
  max_epochs: 2
  gradient_checkpointing: true

checkpoint:
  save_steps: 100
  keep_last: 3
  save_optimizer: true
```

最终文件应使用 NeMo AutoModel 当前实际 schema；这个骨架表达必须固定的实验信息，不能直接假设可运行。

NeMo 当前 release notes 还列出 Qwen3.5 9B-to-4B 的 chunked KD recipe，并冻结 vision/audio towers。该路径可以作为 sequence-level P2P SFT 之后的研究对照；首轮不直接采用 logits KD，以免同时增加 teacher/student 并行、KD loss 和单机内存变量。[NeMo AutoModel release notes](https://docs.nvidia.com/nemo/automodel/whats-new/release-notes)

## 7. 执行阶段

### Phase A：数据 loader smoke

- 100 条去敏 fixture。
- 前向 + 反向 5–20 step。
- 验证 loss 有限、label mask 正确、checkpoint 可保存/恢复。
- 人工解码固定样本，确认输出不是 prompt echo 或无限解释。

失败时停止，不进入全量。

### Phase B：4B post-trained LoRA

- 先用小数据 100–300 step。
- 每个 checkpoint 跑固定 dev 子集和格式/忠实度 validator。
- 确认 improvement 后再跑完整 POC dataset。
- 不先合并 adapter；保留 base + LoRA，方便回滚和消融。

### Phase C：4B Base 对照

使用完全相同的 split、seed、prefix contract 和大致训练预算。若 Base 连基本中文/JSON 都不稳定，不因理论偏好继续扩大。

### Phase D：9B post-trained/Base

只有 4B 流程和评估可重放后再启动。9B 使用相同 recipe 系列，不能因参数量变大而改变数据或指标。

### Phase E：可选 QLoRA

NeMo 文档支持 QLoRA，用 NF4 降低内存；但在 Spark 上是否更快、kernel 是否稳定、量化是否损害经文和 `WAIT` 行为都需实测。[NeMo SFT/PEFT](https://docs.nvidia.com/nemo/automodel/latest/recipes-e2e-examples/sft-peft)

触发条件：

- BF16 LoRA 无法在目标 sequence/batch 下稳定运行，或训练窗口不满足。
- 当前容器明确支持目标 Qwen3.5 + ARM64/Blackwell 的 QLoRA 路径。
- 先通过 20-step smoke 与 checkpoint resume。

QLoRA 不是默认“更省就更好”；如果 LoRA 已稳定，先完成基线再比较。

### Phase F：可选偏好训练

只有 P2P SFT 在 held-out sermons 上稳定后，才用 accepted/rejected pair 评估 DPO 或同类方法。首轮不要同时改变 base、SFT、偏好数据和量化。

## 8. 每个 checkpoint 的在线外评估

训练过程中不只看 loss。每个保存点至少运行：

- schema pass rate。
- `WAIT/WRITE` action accuracy。
- append-only violation。
- unsupported/Saturday-only addition。
- 经文模式与术语准确率。
- clean text 与 real-ASR prefix 两套 quality。
- 固定 30–60 秒音频 replay 的 student TTFT 和 end-to-end first-readable。

选择 checkpoint 依据 dev/faithfulness，而不是自动取最后一步。

## 9. 数据准备 job 与 student job 分离

当前流程：

1. 在 Spark 外运行 Terra 初译、Sol 独立复审，写入隔离 dataset staging。
2. validator、授权门禁与 human review 通过后发布不可变 Gold dataset version。
3. Spark 只读挂载已发布 dataset；训练 step 不同步查询 Terra、Sol 或其他教师。
4. 如果启用 Qwen3.8-27B 备用实验臂，必须先独立制数并停止教师，再启动学生训练。

这样训练可重放，也避免教师调用状态与 4B/9B optimizer 状态耦合。

## 10. Artifact 导出

保留层级：

1. 原始 LoRA adapter checkpoint。
2. 选中的 adapter + base reference。
3. 经过离线评估的 merged BF16 candidate。
4. 从同一 merged candidate 生成的 8/6/4-bit 推理 artifact。
5. 每种 artifact 的独立评估和 hash。

不要：

- 在通过门禁前删除 optimizer/checkpoint。
- 用量化 artifact 反推“训练成功”。
- 覆盖已有 tag。
- 把模型文件直接复制到 production active path。

## 11. 推理 bake-off

DGX Spark 上至少比较：

- BF16 merged + vLLM/SGLang 当前支持路径。
- 8/6/4-bit 当前支持路径。
- 4B vs 9B，Context Pack on/off。
- cold start、warm TTFT、steady-state tokens/s。
- 75 分钟 replay 的 p50/p95/p99、memory、temperature、power 和 latency drift。

Mac 的 MLX 转换与量化在 Mac workstream 完成；同一 adapter/merged source hash 必须能追溯到 DGX 训练 artifact。

## 12. Run receipt

```json
{
  "runId": "20260830-qwen35-4b-post-lora",
  "status": "candidate_rejected_or_ready_for_eval",
  "host": "dgx-spark-pseudonym",
  "baseModel": "Qwen/Qwen3.5-4B",
  "baseRevision": "...",
  "baseFilesSha256Manifest": "...",
  "datasetVersion": "sermon-simul-ds-v1-poc",
  "datasetManifestSha256": "...",
  "codeCommit": "...",
  "containerDigest": "sha256:...",
  "configSha256": "...",
  "seeds": [17, 29, 43],
  "selectedCheckpoint": "step_...",
  "adapterSha256": "...",
  "evalReportSha256": "...",
  "productionChanged": false
}
```

`productionChanged=false` 是训练 run 的正常结果，不代表未完成。

## 13. 停止与恢复

- 收到 OOM、NaN loss、磁盘不足、温度/功耗异常、生产服务异常或数据 hash 不符时停止 job。
- 先保存诊断和本次 run 状态，再停止本次容器；不要用广泛 kill 或删除命令。
- 只从 hash 匹配且写入完成的 checkpoint 恢复。
- resume 后先复跑固定 eval，确认 loss/optimizer/seed 状态连续。
- 三次重复出现同一不可恢复阻塞，才将 run 标为 blocked 并请求用户决策。

## 14. Run 完成定义

DGX 后训练完成不是“loss 降了”或“模型能回答”。需要：

- 训练与 checkpoint resume 通过。
- adapter、config、dataset、container 和 code receipt 完整。
- held-out sermon 评估与人工抽审完成。
- BF16/量化候选的端到端 replay 完成。
- 75 分钟稳定性通过或明确失败。
- production 未被意外改变。
- candidate 被标记为 `rejected` 或 `ready_for_promotion_review`；训练 run 本身不能直接标记 production deployed。
