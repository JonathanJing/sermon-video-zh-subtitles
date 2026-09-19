# Mac mini 调度 DGX Spark

本研究分支的后续推理从 Mac mini 发起：

- 分支：`codex/local-prosody-poc`
- Mac mini 独立工作树：`/Users/jonyopenclaw/sermon-prosody-research`
- Spark SSH：`achillesjing@192.168.1.152`
- 推理接口：Spark 本机 `http://127.0.0.1:8000/v1`，通过 SSH 调用。

主仓库存在未提交工作，研究分支使用独立工作树；不切换主仓库分支，不覆盖它的修改。

```sh
ssh jonyopenclaw@Jonys-Mac-mini.local
cd /Users/jonyopenclaw/sermon-prosody-research
git pull --ff-only origin codex/local-prosody-poc
python3 experiments/local-prosody-poc/spark_smoke.py --output artifacts/local-prosody-poc/mac-mini-spark-smoke.json
# 使用已冻结输入进行声学表格消融，已有结果会复用缓存
python3 experiments/local-prosody-poc/acoustic_trial.py --conditions text gap acoustic
```

这是按需命令调度，没有创建定时任务。Python 标准库即可调用 Spark；不要求 Mac mini 本地加载27B模型。确认服务实际模型身份后才运行新实验；改变模型或提示词需要新结果目录。

媒体、冻结讲稿、词对齐和声学特征位于忽略的artifacts目录，需单独传输并验证哈希；Git只分发代码和说明。Mac mini未验证MLX/ForcedAligner本地环境，不能把Spark调度成功当作该路径已就绪。Omni权重及隔离环境仍在Spark `/home/achillesjing/prosody-omni-poc/20260919`，需要按其实际容器/挂载配置运行，不能直接在Mac mini执行GPU脚本。
