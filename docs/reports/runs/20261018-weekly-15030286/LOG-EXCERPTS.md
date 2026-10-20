# 第三层与第四层运行日志摘录（脱敏）

只保留 `CHAIN` / `AWAIT` / `SERIAL` 里程碑行和部署结果；本机路径改为 `$WL`（artifacts/weekend-live）。时间为 UTC。

## layer3-15030286-20261018/es/chain-f1.out

```
AWAIT es: layer2 job failed 08:40:28
AWAIT es: no candidate, chain not started
```

## layer3-15030286-20261018/es/chain-f2.out

```
AWAIT es: layer2 job failed 09:15:21
AWAIT es: no candidate, chain not started
```

## layer3-15030286-20261018/es/chain-f2r.out

```
AWAIT es: layer2 job 71569d104dc5c016afe465d7074bfc8d502eba68d277040742fb2f6b83405664 failed 09:24:34
AWAIT es: no candidate, chain not started
```

## layer3-15030286-20261018/es/chain-g1.out

```
AWAIT es: layer2 job ca6efa581ac246a8a193268589820b49500be60f01e88f6f799dfdf789d4b204 succeeded 09:25:59
CHAIN es: text QC exit=1 status=requires_repair 09:36:51
CHAIN es: no text waiver; stop 09:36:51
```

## layer3-15030286-20261018/es/chain-g2.out

```
CHAIN es: text QC exit=0 status=text_waiver_issued 10:08:32
CHAIN es: speech job ready 10:08:34
CHAIN es: render start 10:11:55
CHAIN es: render exit=1 10:12:58
CHAIN es: compact exit=1 10:13:15
AWAIT es: zh chain finished 10:14:22
CHAIN es: speech job ready 10:14:22
CHAIN es: speech job ready 10:32:06
CHAIN es: render start 10:32:06
CHAIN es: render exit=1 10:39:50
CHAIN es: compact exit=0 10:41:41
CHAIN es: screen exit=0 10:43:18
CHAIN es: package exit=0 10:44:33
CHAIN es: audio QC exit=1 10:45:19
{'audioQc': 'requires_repair', 'audioQcReceipt': '$WL/text-qc-15030286-20261018/state-es/qc-receipts/audio/es/85b3713f1885bd8f86e6d8c0f02349bd63ded97c604dcc175d3faf51fa2013be/entry-000001.json', 'calibrationCoverage': {'
CHAIN es: done 10:45:19
SERIAL: es chain exit=0 10:45:19
CHAIN es: [seed 43] render start 13:29:19
CHAIN es: [seed 43] render exit=1 13:35:31
CHAIN es: [seed 43] reserve tripped; resume {"reuseRoot": "<spark-home>/dgx-spark-benchmark/results/weekly-20261018-resi-15030286-l3/output/es-s43-raw-a1/speech-job", "setAside": 106} 13:35:32
CHAIN es: [seed 43] render resume start 13:35:32
CHAIN es: [seed 43] render resume exit=1 13:39:55
CHAIN es: [seed 43] compact exit=0 13:41:54
CHAIN es: [seed 43] screen exit=0 13:43:46
CHAIN es: [seed 43] package exit=0 13:44:58
CHAIN es: [seed 43] audio QC exit=1 13:45:48
{'audioQc': 'requires_repair', 'failedGroups': ['translation-chunk-0007-u009', 'translation-chunk-0007-u015', 'translation-chunk-0007-u022']}
CHAIN es: [seed 43] done 13:45:48
SERIAL: es reseed exit=0 13:45:48
CHAIN es: accepted audio QC start 13:53:54
CHAIN es: accepted audio QC exit=0 14:17:49
{'audioQc': 'requires_repair', 'status': 'audio_waiver_issued', 'failedGroups': ['translation-chunk-0007-u009', 'translation-chunk-0007-u015', 'translation-chunk-0007-u022']}
```

## layer3-15030286-20261018/es/chain-human.out

```
CHAIN human-es: speech job ready 15:30:48
CHAIN human-es: speech job ready 15:48:34
CHAIN human-es: render exit=1 15:50:50
CHAIN human-es: compact exit=0 15:52:36
CHAIN human-es: screen exit=0 15:54:26
CHAIN human-es: package exit=0 15:55:49
track sha equal to the track the operator listened to: True ed1c8dcbbcec ed1c8dcbbcec
CHAIN human-es: done 15:55:49
```

## layer3-15030286-20261018/es/chain.out

```
AWAIT es: layer2 job failed 08:48:20
AWAIT es: no candidate, chain not started
```

## layer3-15030286-20261018/ko/chain-f1.out

```
AWAIT ko: layer2 job failed 08:40:28
AWAIT ko: no candidate, chain not started
```

## layer3-15030286-20261018/ko/chain-f2.out

```
AWAIT ko: layer2 job failed 08:55:20
AWAIT ko: no candidate, chain not started
```

## layer3-15030286-20261018/ko/chain-g1.out

```
AWAIT ko: layer2 job 1d341fb75267c04ae46ccfeb02ea6617594392369ca6223e1a74ef3725eab963 failed 09:25:26
AWAIT ko: no candidate, chain not started
```

## layer3-15030286-20261018/ko/chain-g2.out

```
AWAIT ko: layer2 job 527421c3fedf9aafe84b398106c36914eca17997a459a5fd3b8c84b1843010b9 succeeded 09:39:01
CHAIN ko: text QC exit=1 status=requires_repair 09:59:36
CHAIN ko: no text waiver; stop 09:59:36
CHAIN ko: text QC exit=0 status=text_waiver_issued 10:46:41
CHAIN ko: speech job ready 10:46:43
CHAIN ko: queue clear 10:46:43
CHAIN ko: render start 10:46:43
CHAIN ko: render exit=1 10:54:30
CHAIN ko: reserve tripped; resume {"reuseRoot": "<spark-home>/dgx-spark-benchmark/results/weekly-20261018-resi-15030286-l3/output/ko-raw-a1/speech-job", "setAside": 18} 10:54:30
CHAIN ko: render resume start 10:54:31
CHAIN ko: render resume exit=1 10:57:50
CHAIN ko: compact exit=0 10:59:46
CHAIN ko: screen exit=0 11:01:38
CHAIN ko: package exit=0 11:02:54
CHAIN ko: audio QC exit=1 11:04:15
{'audioQc': 'requires_repair', 'audioQcReceipt': '$WL/text-qc-15030286-20261018/state-ko/qc-receipts/audio/ko/7ca56d1a7803afcee69a8809b94f17752f8b52dbcd818a62cdf7f6b7c318a458/entry-000001.json', 'calibrationCoverage': {'
CHAIN ko: done 11:04:15
CHAIN ko: [seed 43] render start 13:47:09
CHAIN ko: [seed 43] render exit=1 13:53:47
CHAIN ko: [seed 43] reserve tripped; resume {"reuseRoot": "<spark-home>/dgx-spark-benchmark/results/weekly-20261018-resi-15030286-l3/output/ko-s43-raw-a1/speech-job", "setAside": 114} 13:53:48
CHAIN ko: [seed 43] render resume start 13:55:58
CHAIN ko: [seed 43] render resume exit=1 14:00:41
CHAIN ko: [seed 43] compact exit=0 14:02:47
CHAIN ko: [seed 43] screen exit=0 14:04:40
CHAIN ko: [seed 43] package exit=0 14:06:01
CHAIN ko: [seed 43] audio QC exit=1 14:07:21
{'audioQc': 'requires_repair', 'failedGroups': ['translation-chunk-0001-u028', 'translation-chunk-0001-u035', 'translation-chunk-0003-u015']}
CHAIN ko: [seed 43] done 14:07:21
SERIAL: ko reseed exit=0 14:07:21
CHAIN ko: accepted audio QC start 15:00:59
CHAIN ko: accepted audio QC exit=0 15:31:39
{'audioQc': 'requires_repair', 'status': 'audio_waiver_issued', 'failedGroups': ['translation-chunk-0001-u028', 'translation-chunk-0001-u035', 'translation-chunk-0003-u015']}
```

## layer3-15030286-20261018/ko/chain-human.out

```
CHAIN human-ko: speech job ready 15:55:51
CHAIN human-ko: render exit=1 15:58:05
CHAIN human-ko: compact exit=0 15:59:57
CHAIN human-ko: screen exit=0 16:01:42
CHAIN human-ko: package exit=0 16:03:01
track sha equal to the track the operator listened to: True 095f9a4675fe 095f9a4675fe
CHAIN human-ko: done 16:03:01
```

## layer3-15030286-20261018/ko/chain.out

```
AWAIT ko: layer2 job failed 08:48:50
AWAIT ko: no candidate, chain not started
```

## layer3-15030286-20261018/zh-Hans/chain-f1.out

```
AWAIT zh-Hans: layer2 job failed 08:40:28
AWAIT zh-Hans: no candidate, chain not started
```

## layer3-15030286-20261018/zh-Hans/chain-f2.out

```
AWAIT zh-Hans: layer2 job succeeded 09:06:21
CHAIN zh-Hans: text QC exit=1 status=requires_repair 09:18:06
CHAIN zh-Hans: no text waiver; stop 09:18:06
```

## layer3-15030286-20261018/zh-Hans/chain-g1.out

```
AWAIT zh-Hans: layer2 job ae012fa70d2ab3f555228e59d58041b0ff78e120677a7c21f17881c6f2b81008 succeeded 09:25:35
CHAIN zh-Hans: text QC exit=1 status=blocked_prior_failure 09:25:45
CHAIN zh-Hans: no text waiver; stop 09:25:45
```

## layer3-15030286-20261018/zh-Hans/chain-g2.out

```
CHAIN zh-Hans: text QC exit=1 status=requires_repair 09:36:21
CHAIN zh-Hans: no text waiver; stop 09:36:21
```

## layer3-15030286-20261018/zh-Hans/chain-g3.out

```
CHAIN zh-Hans: text QC exit=0 status=text_waiver_issued 09:54:54
CHAIN zh-Hans: speech job ready 09:54:56
CHAIN zh-Hans: render start 09:54:56
CHAIN zh-Hans: render exit=1 09:56:38
CHAIN zh-Hans: compact exit=1 09:56:42
CHAIN zh-Hans: screen exit=1 09:57:04
CHAIN zh-Hans: package exit=1 09:57:04
CHAIN zh-Hans: text QC exit=0 status=text_waiver_issued 10:05:44
CHAIN zh-Hans: speech job ready 10:05:44
CHAIN zh-Hans: render start 10:05:45
CHAIN zh-Hans: render exit=1 10:06:02
CHAIN zh-Hans: compact exit=1 10:06:10
CHAIN zh-Hans: screen exit=1 10:07:52
CHAIN zh-Hans: package exit=1 10:07:54
CHAIN zh-Hans: speech job ready 10:08:04
CHAIN zh-Hans: render start 10:09:54
CHAIN zh-Hans: render exit=1 10:17:21
CHAIN zh-Hans: compact exit=1 10:17:22
CHAIN zh-Hans: screen exit=1 10:17:24
CHAIN zh-Hans: package exit=1 10:17:25
CHAIN zh-Hans: speech job ready 10:19:44
CHAIN zh-Hans: render start 10:19:45
CHAIN zh-Hans: render exit=1 10:23:11
CHAIN zh-Hans: compact exit=0 10:25:06
CHAIN zh-Hans: screen exit=0 10:26:36
CHAIN zh-Hans: package exit=0 10:27:50
CHAIN zh-Hans: audio QC exit=2 10:28:05
CHAIN zh-Hans: done 10:28:05
SERIAL: zh chain exit=0 10:28:05
CHAIN zh-Hans: audio QC rerun start 10:30:00
CHAIN zh-Hans: audio QC exit=1 10:30:35
{'audioQc': 'requires_repair', 'audioQcReceipt': '$WL/text-qc-15030286-20261018/state-zh-Hans/qc-receipts/audio/zh-Hans/ad368f47b972668f00a84ab6511101e440585224bfc2e34d89a7bf8efc322034/entry-000001.json', 'calibrationCov
```

## layer3-15030286-20261018/zh-Hans/chain.out

```
AWAIT zh-Hans: layer2 job failed 08:49:20
AWAIT zh-Hans: no candidate, chain not started
```

## 生产 Hosting 部署（guarded_hosting_publish 回执）

- `prod-asset-first-es-v1/deploy.log`: deployed sites/ai-for-god-sermon-audio/versions/37421012eb737055 → sites/ai-for-god-sermon-audio/versions/c9ec668186401bda
- `prod-asset-first-eske-v1/deploy.log`: deployed sites/ai-for-god-sermon-audio/versions/c9ec668186401bda → sites/ai-for-god-sermon-audio/versions/d8c8bfa3d16fc1ec
- `publish-catalog.log`: deployed sites/ai-for-god-sermon-audio/versions/d8c8bfa3d16fc1ec → sites/ai-for-god-sermon-audio/versions/3c35779c91e9e0ca
- `publish-posters.log`: deployed sites/ai-for-god-sermon-audio/versions/3c35779c91e9e0ca → sites/ai-for-god-sermon-audio/versions/05343d2d7520c407
- `publish-align.log`: deployed sites/ai-for-god-sermon-audio/versions/05343d2d7520c407 → sites/ai-for-god-sermon-audio/versions/0cd17fc1326f668d
