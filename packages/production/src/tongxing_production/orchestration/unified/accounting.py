"""Join owner dispatch to existing v4 provider/job accounting without new logs."""
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts.sermon_unified import contracts as c


def execute(executor,manifest,step,output,state,row):
    directory=output.parent/'accounting'/step['id']
    with profile.session(directory,'unified_stage',
        {'pageId':manifest['content']['pageId'],'sourceId':manifest['source']['sourceId']},
        work_kind='production',evidence_mode='current_execution',
        production_run_id=manifest['productionRunId'],evidence_directory=output.parent) as session:
        with profile.context(revisionId='r'+str(manifest['runRevision']),
            jobId=c.digest(c.job_identity(manifest,step)),attemptId=state['attemptId'],workUnitId=step['id']):
            with accounting.stage_outcome('unified.'+step['adapter'],billing='orchestrator',
                executor_type='deterministic_program',work_unit_id=step['id'],attempt_id=state['attemptId'],
                depends_on=[],dependency_ready_at=row['readyAt'],queued_at=row['enqueuedAt']) as span:
                result=executor(manifest,'/',step,output)
                span.finish('completed' if result.get('status')=='succeeded' else 'failed')
                result['accountingEvidence']={'runId':session['runId'],'workflowId':session['workflowId'],
                    'eventPath':session['events'],'dispatchSpanId':span.span_id,
                    'ownerDispatchEventId':row['dispatchEventId'],'ownerTraceId':state['traceId'],
                    'invoiceVerified':False}
                return result
