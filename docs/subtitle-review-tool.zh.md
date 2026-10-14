# 单篇字幕审校工具

`review_sermon_subtitles_with_openai.py` 读取指定目录的已冻结英文与中文字幕，以 OpenAI API 做单篇字幕审校；默认模型为 `gpt-6.1-sol`，reasoning effort 为 `medium`。英文保留，只更新中文。该 legacy 工具的结果仍是机器证据，不能替代 canonical producer 的批准或发布门。

在已有授权的运行目录和对应 dev/prod [环境 launcher](openai-minimal-project-setup.zh.md) 下执行：

```sh
.venv/bin/python scripts/review_sermon_subtitles_with_openai.py \
  --outdir artifacts/<approved-run> \
  --model gpt-6.1-sol --reasoning-effort medium
```

这里只示范参数，不授权新增付费请求。绝对时间字幕额外传已核实的 `--sermon-start-seconds`；省略时只导出相对时间。

缓存读取前验证实际 bounded request，并绑定完整 request limits、非明文 credential fingerprint、project/runtime route 与 caller/transport 实现身份。旧未绑定身份的缓存不自动当作新执行的结果；执行身份变化或目录存在未知 provider outcome 时必须先核对，不能靠旧缓存或换身份绕过未知结果门。

当前 legacy bounded-text cache contract 为 v3；sentence-model 派生缓存也单独使用 v3，原 sentence run manifest v1 不变。旧缓存不原地重标为 v3；已有冻结运行保留其原实现/身份，新的执行使用新的缓存键，先核对未知 outcome 后再决定后续动作。
