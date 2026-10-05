"""Temporal SDK definitions; provider work stays in the project interpreter."""
import asyncio
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from .unified import UnifiedRequest, project_call


@activity.defn(name='sermon.unified.execute.v1')
async def execute_activity(request: UnifiedRequest) -> dict:
    task=asyncio.create_task(asyncio.to_thread(project_call,'execute',request))
    try:
        while not task.done():
            activity.heartbeat({'runKey':request.run_key,'planHash':request.plan_hash})
            await asyncio.wait({task},timeout=1)
        return await task
    except asyncio.CancelledError:
        try:
            await asyncio.to_thread(project_call,'cancel',request)
        finally:
            await asyncio.shield(task)
        raise


@workflow.defn(name='SermonUnifiedV1',sandboxed=False)
class UnifiedWorkflow:
    def __init__(self):
        self.evidence_epoch=0
        self.current={'outcome':'pending'}

    @workflow.signal
    def evidence_changed(self):
        self.evidence_epoch+=1

    @workflow.query
    def status(self) -> dict:
        return self.current

    @workflow.run
    async def run(self, request: UnifiedRequest) -> dict:
        while True:
            epoch=self.evidence_epoch
            self.current=await workflow.execute_activity('sermon.unified.execute.v1',request,
                start_to_close_timeout=timedelta(hours=24),heartbeat_timeout=timedelta(seconds=20),
                retry_policy=RetryPolicy(maximum_attempts=1),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED)
            if self.current['outcome'] in ('succeeded','cancelled'):
                return self.current
            # A signal merely wakes validation. It cannot replace a review,
            # reconcile an unknown response or reset a failed effect.
            await workflow.wait_condition(lambda:self.evidence_epoch!=epoch)
