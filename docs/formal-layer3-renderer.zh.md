# 正式 Layer 3 配音 renderer

`scripts/render_formal_target_language_speech.py` 只接受已人工审核的 v2 speech job。先验证 Layer 1/2、独立人审、音色授权与能力收据、clip timeline、adapter/registry、音频操作策略三项哈希以及部署 checkpoint 的权重 SHA。它逐组使用 job 的原文合成自然速度 WAV，完整解码并写 unit receipt，按 clip-relative 首个源单元起点排程。默认 reaction lag 0.05 秒、组间 gap 0.05 秒、末单元源结束后最大 8 秒；最终音频必须在片段媒体时长内。越界时保留已解码的单元与 `render-diagnostics.json`，不写成功 manifest，不调速、不裁剪、不跳过。

重跑时按 job、源与候选、adapter、checkpoint map/权重、策略文件、文本、renderer SHA 与合成参数比较缓存身份；任何旧稿或旧音色无法复用。一个单元在 WAV 写出后中断时，可凭已写的 SHA commit 记录恢复。`render-manifest.json` 的机器筛查为 `not_run`，人工听审仍待完成。

Mac 绝对输入路径可用 `--path-map` 映射到容器中的 staged 文件。JSON 形状：`{"schemaVersion":"sermon-deployment-path-map-v1","paths":{"/原始/绝对/文件":"/work/staged/文件"}}`。必须列出 job 的每个不可访问 input 路径以及 source/voice/timeline 收据中引用的不可访问文件。renderer 在建立临时路径别名之前逐项重新核对文件 SHA 和提供的 JSON SHA，绝不改写 job JSON。为了让现有验证器沿用不可变 job 内的原路径，容器需要 `/Users` 与 `/private` 两个临时文件系统；只在隔离容器里创建别名。

在 Spark 上，9 月 23 日长探针对应镜像是 `nvcr.io/nvidia/pytorch:26.06-py3`。已经只读验证镜像内 `/usr/bin/python` 可以从旧 venv 的 `site-packages` 导入 `torch`、`qwen_tts` 和 `jsonschema`，GPU 可见。Eric checkpoint 的宿主权重在 `/home/achillesjing/dgx-spark-benchmark/results/sermon-voice-poc-20260905/checkpoints/checkpoint-epoch-0`，SHA 与 Registry 一致。以下是 staged 目录准备完成后的一语执行模板；`SEP20_STAGE` 应指向操作员已校验的实际目录，其中 `repo/` 是含本脚本及依赖的仓库代码、`inputs/ko/` 是原始字节的正式输入、`output/ko/speech-job/job.json` 是未改字节的 job、`path-map.json` 映射所有原始绝对路径。

```bash
SEP20_STAGE=/home/achillesjing/dgx-spark-benchmark/results/sermon-formal-sep20-stage
docker run --rm --gpus all --ipc=host --read-only --network none \
  --tmpfs /tmp:rw,exec,nosuid,size=512m --tmpfs /Users:rw,nosuid,size=64m \
  --tmpfs /private:rw,nosuid,size=64m \
  -v "$SEP20_STAGE":/work:rw \
  -v /home/achillesjing/dgx-spark-benchmark/results:/results:ro \
  -v /home/achillesjing/dgx-spark-benchmark/results/sermon-voice-poc-20260905/venv/lib/python3.12/site-packages:/voice-packages:ro \
  -e PYTHONPATH=/work/repo:/voice-packages -e NUMBA_CACHE_DIR=/tmp/numba \
  -e TRITON_CACHE_DIR=/tmp/triton -e XDG_CACHE_HOME=/tmp/cache \
  -e HF_HOME=/tmp/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  --entrypoint python nvcr.io/nvidia/pytorch:26.06-py3 \
  /work/repo/scripts/render_formal_target_language_speech.py \
  --source /work/inputs/ko/english-source-package.json \
  --anchor /work/inputs/ko/anchor-manifest.json \
  --candidate /work/inputs/ko/candidate.approved.json \
  --policy /work/inputs/ko/policy-v2.json \
  --human-review-receipt /work/inputs/ko/human-review-receipt.json \
  --speaker-registry /work/inputs/ko/speaker-voice-registry.json \
  --adapter /work/inputs/ko/speech-adapter.json \
  --clip-voice-authorization /work/inputs/ko/clip-voice-authorization.json \
  --clip-voice-capability /work/inputs/ko/clip-voice-capability.json \
  --clip-timeline-map /work/inputs/ko/clip-timeline-map.json \
  --job /work/output/ko/speech-job/job.json \
  --checkpoint-map /results/sermon-voice-sep20-long-probe-20260923-v1/work/speaker-checkpoints.dgx.json \
  --audio-operation-policies /work/inputs/audio-operation-policies.json \
  --path-map /work/path-map.json
```

中文已有全局人审能力时可省略 `--clip-voice-capability`。这个模板没有运行正式合成；部署时须先把实际输入放入模板指定位置，并核对 `path-map.json`。`build_target_language_audio_package.py` 以 renderer 的 manifest 构建最高为 `candidate` 的 Layer 3 包。机器筛查及全文人工听审需单独完成。
