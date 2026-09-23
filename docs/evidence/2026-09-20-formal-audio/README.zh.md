# 9 月 20 日片段 Layer 3 人审证据快照

本目录保存中文、韩语、西语 2:58 正式候选音轨的独立 v2 人审收据，以及不含本机绝对路径的 Audio Package 精简快照。用户逐语言以原视频 1 倍速听审全文和 ASR 标红组；收据保留原机器状态 `requires_review`，逐组记下人工裁决。快照列出每个单元的文本和音频 SHA、整轨、字幕、排程、上游包及原版已审 Audio Package 的 JSON SHA；可与[进度清单](../2026-09-20-multilingual-clip-layer2.json)交叉核对。

完整 Audio Package、原始音频和排程位于忽略目录 `artifacts/multilingual-clip-20260920/20260920-blocks9-14-178s/layer3-formal-prep/`，其中 package 包含本机媒体路径，不能直接作为可移植构建输入提交到 Git。此目录可以复核批准范围和哈希绑定；干净检出若没有授权媒体归档，不能重建或发布音轨。正式 staging 仍须读取原 package、完整 ASR 收据、文件字节和同一来源的 Layer 1／2 收据。
