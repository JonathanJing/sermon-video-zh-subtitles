# Spark 测试关键日志

只保留错误类型、退出码和最终产物；原始日志在本机证据目录，未提交。

## 8 副本内存门限

```
tongxing_production.compute.spark_tts_replica_pool.ReplicaPoolError:
MemAvailable is below the TTS replica reserve
```

## partial reuse 不完整

```
ValueError: Incomplete previous render evidence: translation-chunk-0009-u027
```

## 1× 拼接 exit=1（已知）

```
ValueError: Measured target audio exceeds 1x clip schedule:
{'unitIndex': 396, 'textGroupId': 'translation-chunk-0010-u011',
 'plannedEnd': 1895.31, 'sourceEnd': 1866.28, 'clipDuration': 1895.0,
 'maxEndLagSeconds': 120.0}
```

## 默认 compact 缺 trailing 字段

```
ValueError: Edge silence trim duration differs from unit 0
```

## 用主 checkout 旧代码 package 的 waiver 误报

```
ValueError: Waiver was issued under a QC implementation other than the current one; recalibrate and reissue
```

## 正确 compact 后 package 成功

```
{"status": "candidate", "targetLocale": "zh-Hans",
 "package": "<workspace>/artifacts/weekend-live/layer3-test-zh-20261019c/zh-Hans/audio-package-c4.json"}
```

## 重签尝试（不签发）

```
31 failed; old acceptance covers 25; 6 remain
zh-Hans.text-qc.prefetch 1050.8s
zh-Hans.text-qc 174.0s
status: requires_repair
```
