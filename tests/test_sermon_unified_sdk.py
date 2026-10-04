"""Run in artifacts/temporal/runtime/venv; no Temporal server or provider."""
import unittest
from unittest.mock import AsyncMock,patch
from scripts.sermon_temporal.unified import UnifiedRequest
try:
    from scripts.sermon_temporal import unified_sdk as sdk
except ModuleNotFoundError as exc:
    if exc.name!='temporalio':raise
    sdk=None


@unittest.skipIf(sdk is None,'Run in the isolated Temporal SDK runtime')
class UnifiedWorkflowResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_human_gate_waits_for_signal_then_continues_same_request(self):
        instance=sdk.UnifiedWorkflow()
        request=UnifiedRequest('/unused','run','plan')
        async def wake(condition):
            self.assertFalse(condition());instance.evidence_changed();self.assertTrue(condition())
        with patch.object(sdk.workflow,'execute_activity',new=AsyncMock(side_effect=[{'outcome':'blocked'},{'outcome':'succeeded'}])) as execute, \
             patch.object(sdk.workflow,'wait_condition',new=AsyncMock(side_effect=wake)) as wait:
            self.assertEqual(await instance.run(request),{'outcome':'succeeded'})
        self.assertEqual(execute.await_count,2);self.assertEqual(wait.await_count,1)
        for call in execute.await_args_list:
            self.assertIs(call.args[1],request)
            self.assertEqual(call.kwargs['retry_policy'].maximum_attempts,1)
    async def test_unknown_requires_explicit_wake_and_stays_unknown(self):
        instance=sdk.UnifiedWorkflow();request=UnifiedRequest('/unused','run','plan')
        async def stop(condition):
            self.assertFalse(condition());raise RuntimeError('manual reconciliation pending')
        with patch.object(sdk.workflow,'execute_activity',new=AsyncMock(return_value={'outcome':'unknown'})) as execute, \
             patch.object(sdk.workflow,'wait_condition',new=AsyncMock(side_effect=stop)):
            with self.assertRaisesRegex(RuntimeError,'manual reconciliation'):
                await instance.run(request)
        self.assertEqual(execute.await_count,1)
