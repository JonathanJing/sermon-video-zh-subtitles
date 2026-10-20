# 测试日志摘录

只保留计数、失败分类和最慢模块；原始日志在本地证据目录，未提交。

## 权威全量

```
Full suite: 5874 tests from 516 modules
...
Ran 5874 tests in 3777.547s

OK (skipped=38, expected failures=2)
```

## 第二次全量的 7 个错误（环境）

2 个 API 路径：

```
ERROR: test_backend_app (unittest.loader._FailedTest.test_backend_app)
ERROR: test_cloud_run_jobs (unittest.loader._FailedTest.test_cloud_run_jobs)
ModuleNotFoundError: No module named 'tongxing_api'
```

5 个进程组测试：

```
ERROR: test_escaped_pipe_holder_cannot_hide_timeout_or_block_cleanup_forever
ERROR: test_guarded_nested_groups_cascade_when_intermediate_owner_is_killed
ERROR: test_killed_owner_keeps_inherited_child_lock_until_child_exits
ERROR: test_timeout_kills_process_group_including_term_ignoring_grandchild
ERROR: test_owner_sigkill_stops_child_and_grandchild_before_lease_expiry
PermissionError: [Errno 1] Operation not permitted: 'ps'
```

加 `services/api/src` 后 44 passed / 5 subtests；完整进程访问下 14 passed / 10 subtests。

## 最慢模块

```
 776.92s    67  test_machine_quality_waiver
 314.05s    13  test_sermon_mock_tts_dag
 308.95s    17  test_run_machine_qc_audio_test
 306.96s     8  test_sermon_fresh_full_dag
  83.22s    48  test_sermon_delivery_intent_binding
  61.16s    13  test_sermon_pilot_evidence
  60.81s    49  test_sermon_cuv_translation
  56.44s    18  test_sermon_local_business_callbacks
```

## 定向测试

```
15 passed, 37 subtests   模拟器 + 纯文字发布夹具
64 passed, 165 subtests  逐组记录 + QC 回归
82 passed, 149 subtests  交付契约
14 passed, 10 subtests   supervisor / execution harness
44 passed, 5 subtests    backend / cloud run jobs
```
