"""Durable pure-planner adapter; never a responder, scheduler or admission grant.

Trusted integration supplies a current evidence loader executed under the
existing canonical admission lock and global budget lock. All actual calls
still require StrictBudgetAdapter reservation. Plan history is pinned to that
same budget root; output folders and renamed issues cannot reset fingerprints.
"""
from pathlib import Path
import json
import re

from scripts import sermon_review_contracts as c
from scripts import sermon_repair_planning as planning
from scripts import sermon_review_budget as budget
from scripts import sermon_workflow_jobs as jobs
from scripts.canonical_layer2_controller import ADMISSION_LOCK
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_strict_budget_adapter as execution
from scripts import sermon_review_gate as gate
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import sermon_review_observation as observation
from scripts.sermon_release_workflow import _safe_path

SCHEMA='sermon-strict-repair-history-v1'


class RepairPlanner:
    def __init__(self, store, job_root, production_run_id):
        c.require(type(store) is budget.BudgetStore,'trusted_budget_store_required')
        c.require(type(production_run_id) is str and re.fullmatch('[a-f0-9]{64}',production_run_id),
                  'invalid_production_run_id')
        self.store=store;self.job_root=Path(job_root);self.run_id=production_run_id

    def plan(self, load_current, *, depends_on=None, completion_spans=None):
        if profile.current() is None:
            return self._plan(load_current)
        with accounting.stage('rqc.repair_planning',depends_on=depends_on,
                executor_type='deterministic_program') as span:
            result=self._plan(load_current)
            plan=result['planning']['repairPlan']
            if plan is not None:observation.record(plan)
        if completion_spans is not None:completion_spans.append(span)
        return result

    def _plan(self, load_current):
        """Load current D1/D4 evidence and atomically retain proposed sidecars.

        Loader returns the keyword arguments of plan_repair except budget;
        `state_revision` must be the current whole workflow revision, not just
        a receipt hash. No model-produced Gate Decision is accepted by a
        production loader. This adapter independently validates all bindings.
        """
        with jobs._lock(self.job_root,ADMISSION_LOCK) as (_,_,held):
            c.require(held,'repair_admission_busy')
            with self.store._locked() as (folder,ledger):
                values=load_current(ledger)
                c.require(type(values) is dict and 'budget' not in values,'invalid_current_repair_evidence')
                candidate=values['candidate'];review=values['review']
                identity={k:candidate[k] for k in budget.IDENTITY_FIELDS if k not in ('rubricSha256','workUnitId')}
                identity.update(rubricSha256=review['rubricSha256'],workUnitId=candidate['workUnitIds'][0])
                budget.chain_identity(identity);chain=c.canonical_sha256(identity)
                path=folder/'repair-planning.json'
                if path.exists():
                    history,_=c.read_snapshot(path)
                    c.require(type(history) is dict and set(history)=={'schemaVersion','productionRunId','chains'} and
                        history['schemaVersion']==SCHEMA and history['productionRunId']==self.run_id and
                        type(history['chains']) is dict,'repair_history_binding_changed')
                else:history=dict(schemaVersion=SCHEMA,productionRunId=self.run_id,chains={})
                entries=history['chains'].get(chain,{})
                c.require(type(entries) is dict,'invalid_repair_history')
                reservations=[row for row in ledger['reservations'].values() if row['request']['identity']==identity]
                known_reviews=[row for row in reservations if row['request']['kind']=='review' and
                    row['request']['revisionId']==candidate['revisionId'] and row['phase']=='result' and
                    row['result']['receiptSha256']==c.canonical_sha256(review)]
                c.require(len(known_reviews)==1,'repair_review_not_in_durable_budget')
                reserved_next={row['request']['revisionId'] for row in reservations if row['request']['kind']=='content_revision'}
                fingerprints=[]
                for plan_id,entry in entries.items():
                    c.require(type(entry) is dict and set(entry)=={'plan','fingerprint','sidecars'} and
                        entry['plan']['repairPlanId']==plan_id and type(entry['fingerprint']) is str and
                        re.fullmatch('[a-f0-9]{64}',entry['fingerprint']), 'invalid_repair_history_entry')
                    c.validate_contract(entry['plan'])
                    c.require(all(entry['plan'][k]==candidate[k] for k in
                        ('candidateId','targetLocale','sourceIdentitySha256','sourcePackageSha256','anchorSha256','policySha256')),
                        'repair_history_identity_changed')
                    if entry['plan']['toRevisionId'] in reserved_next:fingerprints.append(entry['fingerprint'])
                previous=list(values.get('prior_revisions',()))
                root_revision=(previous[0] if previous else candidate)['revisionId']
                limits=self.store.authority['limits']
                snapshot=planning.BudgetSnapshot(self.run_id,values['state_revision'],candidate['candidateId'],
                    identity['workUnitId'],root_revision,candidate['revisionId'],self.store.authority['approvalSha256'],
                    c.canonical_sha256(ledger),
                    sum(row['request']['kind']=='content_revision' for row in reservations),
                    sum(row['request']['kind']=='review' and row['request']['revisionId']==candidate['revisionId'] for row in reservations),
                    sum(row['request']['kind']=='decision_proposal' for row in reservations),
                    tuple(sorted(row['request']['operationId'] for row in reservations if row['phase']!='result' or
                        row['result']['executionStatus']=='outcome_unknown')),tuple(sorted(set(fingerprints))),
                    planning.Limits(limits['contentRevisions'],limits['reviewAttemptsPerRevision'],limits['decisionProposals']))
                result=planning.plan_repair(**values,budget=snapshot)
                plan=result['repairPlan'];repair=None
                if plan is not None:
                    sidecars={plan[k]['artifactId']:result[v] for k,v in
                        [('constraintsRef','constraints'),('budgetRef','budgetSnapshot'),('dependencyClosureRef','dependencyClosure')]}
                    entry=dict(plan=plan,fingerprint=result['failureFingerprint'],sidecars=sidecars)
                    prior=entries.get(plan['repairPlanId'])
                    c.require(prior is None or prior==entry,'repair_plan_identity_changed')
                    entries[plan['repairPlanId']]=entry;history['chains'][chain]=entries
                    # Persist evidence before returning any executable proposal.
                    # A write error propagates; no transport is reachable here.
                    encoded=(json.dumps(history,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
                    c.require(len(encoded)<=c.MAX_BYTES,'repair_history_size_limit')
                    jobs._persist(path,history)
                    if plan['repairAction']=='repair_translation':
                        repair=dict(parentRevision=candidate,parentCandidateBytes=values['candidate_bytes'],
                            plan=plan,triggerReview=review,inputManifest=values['input_manifest'],
                            sidecars={k:c.canonical_bytes(v) for k,v in sidecars.items()},
                            priorRevisions=previous,priorRepairs=list(values.get('prior_repairs',())))
                return {'planning':result,'repair':repair,'executionAuthority':'none',
                    'durableHistorySha256':c.canonical_sha256(history),'budgetStateRevision':c.canonical_sha256(ledger)}

    def plan_group(self, prepared, revision_root, graph, *, created_at, depends_on=None, completion_spans=None):
        """Production file loader for a failed current group before public assembly.

        This path verifies actual D3 outputs against every durable reservation;
        it cannot accept a caller/model-supplied passing gate or review inventory.
        Public candidate/plugin/human evidence is still required by the separate
        whole-locale admission adapter once all machine reviews pass.
        """
        return self.plan(lambda ledger:self._load_group(prepared,revision_root,graph,created_at,ledger),
                         depends_on=depends_on,completion_spans=completion_spans)

    def _load_group(self, prepared, revision_root, graph, created_at, ledger):
        root=_safe_path(revision_root);captured={}
        def read(name):
            value,data=c.read_snapshot(root/name);captured[name]=data
            return value,data
        identity=execution.chain_identity(prepared)
        manifest,manifest_bytes=read('revision.json');artifact,artifact_bytes=read('candidate.json')
        c.validate_candidate_artifact(manifest,artifact_bytes)
        for key,value in strict.common_identity(prepared,manifest['candidateId'],manifest['revisionId']).items():
            c.require(manifest[key]==value,'repair_current_identity_changed')
        repair=strict.load_repair(root)
        if repair is not None:
            strict.validate_repair(prepared,manifest['candidateId'],manifest['revisionId'],repair)
            for name in ('parent-revision','parent-candidate','repair-plan','trigger-review','repair-input','repair-sidecars','repair-history'):
                read(name+'.json')
        c.validate_revision_lineage(manifest,repair['parentRevision'] if repair else None,repair['plan'] if repair else None)
        rows=[row for row in ledger['reservations'].values() if row['request']['identity']==identity]
        c.require(rows and max(row['request']['revisionNumber'] for row in rows)==manifest['revisionNumber'],
                  'repair_revision_not_current')
        kind='initial_generation' if repair is None else 'content_revision'
        operation=execution.operation_binding(kind,prepared,root,manifest['candidateId'],manifest['revisionId'],repair=repair)
        generation_rows=[row for row in rows if row['request']['operationId']==operation['operationId']]
        c.require(len(generation_rows)==1 and generation_rows[0]['request']['inputSha256']==operation['inputSha256'] and
            generation_rows[0]['phase']=='result' and generation_rows[0]['result']['executionStatus']=='succeeded' and
            generation_rows[0]['result']['receiptSha256']==c.canonical_sha256(manifest),'repair_generation_not_recorded')
        generation,generation_bytes=read('generator.json');strict.require_call_binding(root/'generator.json',generation)
        read('generator.raw.json');read('generator.call.json')
        inputs,input_bytes=read('review-input.json')
        c.require(inputs==strict.input_manifest(prepared,manifest,artifact_bytes),'repair_input_manifest_changed')
        materials={}
        def add(name,data):
            c.require(name not in materials or materials[name]==data,'repair_material_identity_conflict')
            materials[name]=data
        for name,data in prepared['bytes'].items():
            if name!='rubric':add(name,data)
        add('generation',generation_bytes)
        reviews=[];receipts=[]
        for attempt in (1,2):
            suffix='' if attempt==1 else '-2';name='review-receipt'+suffix+'.json'
            if not (root/name).exists():continue
            review,data=read(name);c.validate_review_binding(review,manifest,prepared['rubric'],inputs)
            operation=execution.operation_binding('review',prepared,root,manifest['candidateId'],manifest['revisionId'],attempt)
            matches=[row for row in rows if row['request']['operationId']==operation['operationId']]
            c.require(len(matches)==1 and matches[0]['request']['inputSha256']==operation['inputSha256'] and
                matches[0]['phase']=='result' and matches[0]['result']['receiptSha256']==c.canonical_sha256(review),
                'repair_review_not_in_durable_budget')
            content={'pass':'pass','needs_rework':'fail','inconclusive':'uncertain','not_assessed':'not_assessed'}
            c.require(matches[0]['result']['executionStatus']==review['executionStatus'] and
                matches[0]['result']['contentStatus']==content[review['reviewVerdict']],
                'repair_review_budget_status_mismatch')
            stem='reviewer'+suffix
            for ref in review['evidenceRefs']:
                filename={'review-result':stem+'.json','review-execution-failure':stem+'.failure.json',
                          'review-transport-rejection':stem+'.rejection.json'}.get(ref['artifactId'])
                c.require(filename is not None,'unknown_repair_review_evidence')
                _,evidence_bytes=read(filename)
                c.require(strict.reference(ref['artifactId'],evidence_bytes)==ref,'repair_review_evidence_changed')
                add(ref['artifactId'],evidence_bytes)
            if review['executionStatus']=='succeeded':
                result,_=read(stem+'.json');strict.require_call_binding(root/(stem+'.json'),result)
                read(stem+'.raw.json');read(stem+'.call.json')
            reviews.append(gate.ReviewEvidence(gate.JsonArtifact('review-'+str(attempt),data),
                gate.JsonArtifact('input-'+str(attempt),input_bytes)))
            receipts.append((review,data))
        c.require(receipts,'repair_review_missing')
        expected=[row for row in rows if row['request']['kind']=='review' and
            row['request']['revisionId']==manifest['revisionId'] and row['phase']=='result']
        c.require(len(expected)==len(receipts),'repair_review_inventory_incomplete')
        unknown=any(row['phase']!='result' or row['result']['executionStatus']=='outcome_unknown' for row in rows)
        state=c.canonical_sha256({'ledger':ledger,'files':{k:c.bytes_sha256(v) for k,v in captured.items()},'graph':graph})
        current=gate.CurrentState(state,identity['targetLocale'],c.canonical_sha256(manifest),
            identity['sourceIdentitySha256'],identity['sourcePackageSha256'],identity['anchorSha256'],
            identity['policySha256'],identity['rubricSha256'],tuple(c.canonical_sha256(r) for r,_ in receipts),False,unknown)
        snapshot=gate.GateSnapshot(current,gate.JsonArtifact('revision',manifest_bytes),
            gate.JsonArtifact('candidate',artifact_bytes),gate.JsonArtifact('rubric',prepared['bytes']['rubric']),
            tuple(reviews),tuple(gate.JsonArtifact(k,v) for k,v in materials.items()),
            gate.JsonArtifact('parent-revision',captured['parent-revision.json']) if repair else None,
            gate.JsonArtifact('repair-plan',captured['repair-plan.json']) if repair else None)
        checks=gate.BoundaryChecks(gate.snapshot_sha256(snapshot),True,True,False,False,'missing')
        decision=gate.evaluate_gate(snapshot,gate_decision_id='repair-gate.'+state[:32],created_at=created_at,
            boundary_checks=checks).decision
        for name,data in captured.items():c.require(c.read_snapshot(root/name)[1]==data,'repair_snapshot_changed')
        review,review_bytes=receipts[-1]
        return dict(candidate=manifest,candidate_bytes=artifact_bytes,review=review,review_bytes=review_bytes,
            rubric=prepared['rubric'],input_manifest=inputs,gate=decision,state_revision=state,graph=graph,
            prior_revisions=[] if repair is None else repair['priorRevisions']+[repair['parentRevision']],
            prior_repairs=[] if repair is None else repair['priorRepairs']+[repair['plan']])
