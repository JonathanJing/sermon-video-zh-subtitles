"""Durable, opt-in D4 permission boundary; never starts a job or Layer 3/4.

Trust boundary: only the production controller supplies Configuration and the
ONE existing BudgetStore (including approved authority). None of these paths,
current revision selections, roots or approvals may come from model output.
All writers must share canonical ADMISSION_LOCK, then the BudgetStore lock.
The stable budget root stores the admission registry; moving an output directory
cannot reset an intent. Changing that trusted root is an operator migration,
not an API retry. Fresh bridge checks validate independent existing human
receipts; this module has no approval writer, provider transport or scheduler.

snapshot() returns an advisory revision. admit() reloads under both locks,
runs the actual whole-locale bridge and every private group gate, compares the
complete byte inventory, and atomically persists decisions plus ONE bound
prepare_layer3 intent. Exceptions during persistence mean outcome_unknown.
reconcile() reads that same intent without creating or executing anything.
An existing L3 adapter must revalidate current evidence before consuming it;
this permission alone enables no production dispatch rollout.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import re

from scripts import canonical_layer2_controller as controller
from scripts import produce_target_language_candidate as producer
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public_snapshot
from scripts import sermon_review_gate as gate
from scripts import sermon_strict_candidate_bridge as bridge
from scripts import sermon_strict_budget_adapter as adapter
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import sermon_review_observation as observations
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-strict-gate-admission-v1'


@dataclass(frozen=True)
class Configuration:
    production_run_id: str
    target_locale: str
    job_root: Path
    revision_root: Path
    revision_roots: tuple[Path, ...]
    source: Path
    anchor: Path
    policy: Path
    rubric: Path
    public_candidate: Path
    human_receipt: Path
    plugin: Path
    plugin_sha256: str


@dataclass(frozen=True)
class Snapshot:
    state_revision: str
    snapshot_sha256: str
    groups: tuple[gate.GateSnapshot, ...]
    revisions: tuple[tuple[Path, int], ...]
    files: dict[str, bytes]
    diagnostics: tuple[str, ...]


class AdmissionBoundary:
    def __init__(self, config: Configuration, store: budget.BudgetStore):
        c.require(type(config) is Configuration and type(store) is budget.BudgetStore,
                  'trusted_admission_configuration_required')
        budget._hash(config.production_run_id); budget._hash(config.plugin_sha256)
        c.require(config.target_locale in ('zh-Hans', 'ko', 'es'), 'invalid_admission_locale')
        c.require(type(config.revision_roots) is tuple and 1 <= len(config.revision_roots) <= 128,
                  'invalid_admission_revision_inventory')
        self.config, self.store = config, store
        root = self._path(config.revision_root)
        c.require(len(set(map(self._path, config.revision_roots))) == len(config.revision_roots),
                  'duplicate_admission_revision')
        for path in config.revision_roots:
            c.require(root in self._path(path).parents, 'revision_outside_trusted_root')
        self.key = c.canonical_sha256({'schemaVersion': SCHEMA,
            'productionRunId': config.production_run_id, 'targetLocale': config.target_locale})
        # Current revision selection is content-bound; other locations are pinned
        # by the first durable registry and cannot be reset by a fresh output dir.
        self.binding = {key: str(self._path(getattr(config, key))) for key in
            ('job_root', 'revision_root', 'source', 'anchor', 'policy', 'rubric',
             'public_candidate', 'human_receipt', 'plugin')}
        self.binding.update(productionRunId=config.production_run_id,
            targetLocale=config.target_locale, pluginSha256=config.plugin_sha256,
            budgetStoreSha256=store.store_sha256, budgetAuthoritySha256=store.authority_sha256)

    @staticmethod
    def _path(path):
        return _safe_path(Path(path).absolute())

    @contextmanager
    def _locked(self):
        with jobs._lock(self.config.job_root, controller.ADMISSION_LOCK) as (_, _, held):
            c.require(held, 'strict_admission_busy')
            with self.store._locked() as (folder, ledger):
                registry = self._path(folder / ('gate-' + self.key))
                path = registry / 'state.json'
                if not registry.exists():
                    registry.mkdir(mode=0o700)
                    jobs._sync_directory_ancestry(registry)
                    jobs._persist(path, {'schemaVersion': SCHEMA, 'binding': self.binding,
                                         'intents': {}})
                    jobs._sync_directory_ancestry(registry)
                # An existing registry missing its record is damaged, never new.
                record, record_bytes = c.read_snapshot(path)
                c.require(type(record) is dict and set(record) == {'schemaVersion', 'binding', 'intents'}
                          and record['schemaVersion'] == SCHEMA and record['binding'] == self.binding
                          and type(record['intents']) is dict, 'admission_registry_changed')
                for key, intent in record['intents'].items():
                    budget._hash(key)
                    c.require(type(intent) is dict and intent.get('intentId') == key
                              and intent.get('action') == 'prepare_layer3'
                              and intent.get('executionAuthority') == 'existing_layer3_adapter_only'
                              and key == c.canonical_sha256(intent['identity']), 'invalid_admission_intent')
                yield path, record, record_bytes, ledger

    def _load(self, record_bytes, ledger):
        files = {}
        def read(key, path):
            reader = public_snapshot if key == 'public_candidate' else c
            value, data = reader.read_snapshot(self._path(path))
            files[key] = data
            return value
        values = {key: read(key, getattr(self.config, key)) for key in
                  ('source', 'anchor', 'policy', 'rubric', 'public_candidate', 'human_receipt')}
        c.require(values['policy']['targetLocale'] == self.config.target_locale,
                  'admission_locale_changed')
        files['budget-ledger'] = c.read_snapshot(self.store.root / budget.STORE_ID / 'state.json')[1]
        c.require(c.decode_json(files['budget-ledger']) == ledger, 'admission_budget_changed')
        files['admission-registry'] = record_bytes
        # Plugin's full implementation closure is pinned by its existing runner.
        files['plugin-identity'] = c.canonical_bytes({'implementationSha256':
            producer.plugin_implementation_sha256(self.config.plugin)})
        c.require(c.decode_json(files['plugin-identity'])['implementationSha256'] == self.config.plugin_sha256,
                  'admission_plugin_changed')
        parsed, diagnostics = [], []
        for index, root in enumerate(self.config.revision_roots):
            root = self._path(root)
            names = sorted(p.name for p in root.iterdir() if p.name != '.admission')
            c.require(len(names) <= 64 and all(name.endswith('.json') for name in names),
                      'unrecognized_revision_evidence')
            fixed = {'request-limits.json', 'strict-identity.json', 'revision.json', 'candidate.json', 'review-input.json',
                     'parent-revision.json', 'parent-candidate.json', 'repair-plan.json', 'trigger-review.json',
                     'repair-input.json', 'repair-sidecars.json', 'repair-history.json'}
            c.require(all(name in fixed or re.fullmatch(
                r'(?:generator|reviewer(?:-2)?)\.(?:json|raw\.json|call\.json|started\.json|failure\.json|rejection\.json|budget-binding\.json|budget-call\.json|budget-result\.json)|review-receipt(?:-2)?\.json', name)
                for name in names), 'unrecognized_revision_evidence')
            data = {}
            for name in names:
                read(f'group.{index}.{name}', root / name)
                data[name] = files[f'group.{index}.{name}']
            manifest = c.decode_json(data['revision.json'])
            candidate = c.decode_json(data['candidate.json'])
            prepared = strict.prepare(*(files[k] for k in ('source', 'anchor', 'policy', 'rubric')),
                {k: candidate[k] for k in ('translationGroupId', 'sourceUnitIds')},
                request_limits=c.decode_json(data['request-limits.json']) if 'request-limits.json' in data else None)
            identity = {key: manifest[key] for key in budget.IDENTITY_FIELDS if key not in ('workUnitId', 'rubricSha256')}
            identity['workUnitId'] = prepared['workUnitId']
            identity['rubricSha256'] = c.canonical_sha256(values['rubric'])
            budget.chain_identity(identity)
            c.require(c.decode_json(data['strict-identity.json']) == {
                'candidateId': manifest['candidateId'], 'revisionId': manifest['revisionId'],
                'workUnitId': prepared['workUnitId'], 'sourcePackageSha256': identity['sourcePackageSha256'],
                'policySha256': identity['policySha256']}, 'admission_revision_registration_changed')
            rows = [row for row in ledger['reservations'].values()
                    if row['request']['identity'] == identity]
            # Every current D3 review must correspond to a settled reservation;
            # omitted/unknown attempts anywhere in this locale remain blockers.
            pending = any(row['phase'] != 'result' for row in rows)
            unknown = any(row.get('result', {}).get('executionStatus') == 'outcome_unknown' for row in rows)
            current = [row for row in rows if row['request']['revisionId'] == manifest['revisionId']]
            generation_kind = 'initial_generation' if manifest['revisionNumber'] == 1 else 'content_revision'
            generations = [row for row in current if row['request']['kind'] == generation_kind]
            generation_binding = adapter.operation_binding(generation_kind, prepared, root,
                manifest['candidateId'], manifest['revisionId'],
                repair=strict.load_repair(root) if manifest['revisionNumber'] > 1 else None)
            if (len(generations) != 1 or generations[0].get('result', {}).get('executionStatus') != 'succeeded'
                or generations[0]['result']['receiptSha256'] != c.canonical_sha256(manifest)
                or any(generations[0]['request'][key] != generation_binding[key]
                       for key in ('identity', 'operationId', 'inputSha256', 'revisionNumber'))):
                diagnostics.append('generation_budget_binding_mismatch')
            if len(generations) == 1:
                self._budget_proof(root, data, generation_binding, generations[0], manifest)
            if manifest['revisionNumber'] > 1:
                history = [c.decode_json(data['parent-revision.json'])]
                history.extend(c.decode_json(data['repair-history.json'])['priorRevisions'])
                trigger = c.decode_json(data['trigger-review.json'])
                if not any(row['request']['kind'] == 'review' and
                    row['request']['revisionId'] == trigger['revisionId'] and
                    row.get('result', {}).get('executionStatus') == 'succeeded' and
                    row['result']['receiptSha256'] == c.canonical_sha256(trigger) and
                    row['result']['contentStatus'] in ('fail', 'uncertain') for row in rows):
                    diagnostics.append('repair_trigger_budget_mismatch')
                for number in range(1, manifest['revisionNumber']):
                    prior = [value for value in history if value['revisionNumber'] == number]
                    prior_rows = [row for row in rows if row['request']['revisionNumber'] == number
                                  and row['request']['kind'] == ('initial_generation' if number == 1 else 'content_revision')]
                    if (len(prior) != 1 or len(prior_rows) != 1 or
                        prior_rows[0].get('result', {}).get('executionStatus') != 'succeeded' or
                        prior_rows[0]['request']['revisionId'] != prior[0]['revisionId'] or
                        prior_rows[0]['result']['receiptSha256'] != c.canonical_sha256(prior[0])):
                        diagnostics.append('generation_budget_history_mismatch')
                    elif number == 1:
                        initial = adapter.operation_binding('initial_generation', prepared, root,
                            prior[0]['candidateId'], prior[0]['revisionId'])
                        if any(prior_rows[0]['request'][key] != initial[key] for key in
                               ('identity', 'operationId', 'inputSha256', 'revisionNumber')):
                            diagnostics.append('generation_budget_history_mismatch')
            review_rows = [row for row in current if row['request']['kind'] == 'review']
            receipts = []
            attempts = []
            for name, raw in data.items():
                if name.startswith('review-receipt'):
                    match = re.fullmatch(r'review-receipt(?:-([2]))?\.json', name)
                    c.require(match is not None, 'unrecognized_review_attempt')
                    attempts.append(int(match[1] or 1)); receipts.append((name, raw))
            receipts.sort(key=lambda item: item[0] != 'review-receipt.json')
            c.require(attempts and sorted(attempts) == list(range(1, max(attempts) + 1)),
                      'incomplete_review_inventory')
            for name in data:
                if name.startswith('reviewer'):
                    match = re.fullmatch(r'reviewer(?:-([2]))?\.(?:json|raw\.json|call\.json|started\.json|failure\.json|rejection\.json|budget-binding\.json|budget-call\.json|budget-result\.json)', name)
                    c.require(match is not None, 'unrecognized_reviewer_evidence')
                    if int(match[1] or 1) not in attempts: pending = True
            hashes = [c.canonical_sha256(c.decode_json(raw)) for _, raw in receipts]
            settled = [row.get('result', {}).get('receiptSha256') for row in review_rows]
            if sorted(h for h in settled if h is not None) != sorted(hashes):
                diagnostics.append('review_budget_inventory_mismatch')
            for receipt_name, receipt_bytes in receipts:
                receipt = c.decode_json(receipt_bytes)
                matches = [row for row in review_rows if row.get('result', {}).get('receiptSha256') == c.canonical_sha256(receipt)]
                if len(matches) == 1:
                    row = matches[0]
                    content = {'pass': 'pass', 'needs_rework': 'fail', 'inconclusive': 'uncertain', 'not_assessed': 'not_assessed'}
                    attempt_number = 1 if receipt_name == 'review-receipt.json' else 2
                    review_binding = adapter.operation_binding('review', prepared, root,
                        manifest['candidateId'], manifest['revisionId'], attempt_number=attempt_number)
                    if (any(row['request'][key] != review_binding[key] for key in
                            ('identity', 'operationId', 'inputSha256', 'revisionNumber')) or
                        row['result']['executionStatus'] != receipt['executionStatus'] or
                        row['result']['contentStatus'] != content[receipt['reviewVerdict']]):
                        diagnostics.append('review_budget_binding_mismatch')
                    self._budget_proof(root, data, review_binding, row, receipt)
            if not rows or max(row['request']['revisionNumber'] for row in rows) != manifest['revisionNumber']:
                diagnostics.append('budget_revision_not_current')
            if any(row['request']['revisionNumber'] == manifest['revisionNumber'] and
                   row['request']['revisionId'] != manifest['revisionId'] for row in rows):
                diagnostics.append('budget_revision_identity_changed')
            # The bridge selects the latest receipt, never an earlier convenient pass.
            latest = c.decode_json(receipts[-1][1])
            if latest['executionStatus'] != 'succeeded' or latest['reviewVerdict'] != 'pass':
                diagnostics.append('latest_review_not_passed')
            parsed.append((root, data, manifest, prepared, receipts, pending, unknown, max(attempts)))
        # A reservation for an omitted group in the same frozen locale scope is
        # not silently hidden by the caller's current directory list.
        units = {row[3]['workUnitId'] for row in parsed}
        for row in ledger['reservations'].values():
            ident = row['request']['identity']
            if ident['targetLocale'] != self.config.target_locale:
                continue
            if (row['phase'] != 'result' or row.get('result', {}).get('executionStatus') == 'outcome_unknown'):
                diagnostics.append('locale_budget_reconciliation_required')
            if (ident['policySha256'] == c.canonical_sha256(values['policy']) and
                ident['sourcePackageSha256'] == c.canonical_sha256(values['source']) and
                ident['workUnitId'] not in units):
                diagnostics.append('locale_group_inventory_incomplete')
        if any(any(budget._charge(row)[k] > row['request']['bounds'][k] for k in budget.METRICS)
               for row in ledger['reservations'].values()):
            diagnostics.append('budget_bound_exceeded')
        inventory = {key: c.bytes_sha256(raw) for key, raw in sorted(files.items())}
        selection = [str(self._path(path)) for path in self.config.revision_roots]
        state_revision = c.canonical_sha256({'binding': self.binding, 'files': inventory, 'revisions': selection})
        # Public aggregate bytes stay in the authoritative CAS inventory and
        # real bridge validation. A compact descriptor keeps PRIVATE per-group
        # Gate artifacts bounded without relabeling an approval receipt.
        public_binding = {'schemaVersion': 'sermon-public-candidate-binding-v1',
            'canonicalJsonSha256': c.canonical_sha256(values['public_candidate']),
            'fileBytesSha256': c.bytes_sha256(files['public_candidate'])}
        common = [gate.JsonArtifact('public-candidate-binding', c.canonical_bytes(public_binding))]
        common.extend(gate.JsonArtifact(key, files[key]) for key in
                      ('human_receipt', 'budget-ledger', 'plugin-identity'))
        common.append(gate.JsonArtifact('full-byte-inventory', c.canonical_bytes(inventory)))
        snapshots = []
        for root, data, manifest, prepared, receipts, pending, unknown, attempt in parsed:
            artifacts = {'candidate': gate.JsonArtifact('candidate', data['candidate.json']),
                         'rubric': gate.JsonArtifact('rubric', files['rubric'])}
            for key, raw in prepared['bytes'].items():
                artifacts[key] = gate.JsonArtifact(key, raw)
            artifacts['generation'] = gate.JsonArtifact('generation', data['generator.json'])
            # Resolve literal D1 reference IDs by both canonical AND exact byte
            # hash. Equivalent IDs deduplicate; conflicting meanings block.
            available = list(data.values()) + list(prepared['bytes'].values())
            def refs(value):
                if type(value) is dict:
                    if set(value) == {'artifactId', 'canonicalJsonSha256', 'fileBytesSha256', 'mediaType'}:
                        matches = [raw for raw in available if c.bytes_sha256(raw) == value['fileBytesSha256']]
                        c.require(matches, 'admission_reference_missing')
                        artifact = gate.JsonArtifact(value['artifactId'], matches[0])
                        c.require(artifact.reference() == value, 'admission_reference_changed')
                        old = artifacts.get(artifact.artifact_id)
                        c.require(old is None or old.data == artifact.data, 'admission_reference_conflict')
                        artifacts[artifact.artifact_id] = artifact
                    else:
                        for child in value.values(): refs(child)
                elif type(value) is list:
                    for child in value: refs(child)
            refs(manifest['generationReceiptRef'])
            refs(c.decode_json(data['review-input.json']))
            for _, raw in receipts: refs(c.decode_json(raw))
            evidence = tuple(gate.ReviewEvidence(gate.JsonArtifact('receipt.' + str(i), raw),
                gate.JsonArtifact('input.' + str(i), data['review-input.json'])) for i, (_, raw) in enumerate(receipts))
            extras = [gate.JsonArtifact('file.' + name, raw) for name, raw in data.items()]
            state = gate.CurrentState(state_revision, self.config.target_locale, c.canonical_sha256(manifest),
                values['source']['downstreamInvalidationKey'], c.canonical_sha256(values['source']),
                c.canonical_sha256(values['anchor']), c.canonical_sha256(values['policy']),
                c.canonical_sha256(values['rubric']),
                tuple(c.canonical_sha256(c.decode_json(raw)) for _, raw in receipts), pending, unknown)
            snapshots.append(gate.GateSnapshot(state, gate.JsonArtifact('revision', data['revision.json']),
                artifacts.pop('candidate'), artifacts.pop('rubric'), evidence,
                tuple(list(artifacts.values()) + common + extras),
                gate.JsonArtifact('parent-revision', data['parent-revision.json']) if manifest['revisionNumber'] > 1 else None,
                gate.JsonArtifact('repair-plan', data['repair-plan.json']) if manifest['revisionNumber'] > 1 else None))
        fingerprint = c.canonical_sha256({'stateRevision': state_revision,
            'groups': [gate.snapshot_sha256(s) for s in snapshots], 'diagnostics': sorted(set(diagnostics))})
        return Snapshot(state_revision, fingerprint, tuple(snapshots),
            tuple((row[0], row[-1]) for row in parsed), files, tuple(sorted(set(diagnostics))))

    def _budget_proof(self, root, data, operation, row, artifact):
        output = root / operation['outputName']
        rid = self.store._reservation_id(row['request'])
        binding = {'schemaVersion': 'sermon-strict-budget-binding-v1', 'reservationId': rid,
            'chainId': c.canonical_sha256(operation['identity']), 'operationId': operation['operationId'],
            'inputSha256': operation['inputSha256'], 'payloadSha256': operation['payloadSha256'],
            'authoritySha256': self.store.authority_sha256, 'storeSha256': self.store.store_sha256}
        c.require(c.decode_json(data[output.with_suffix('.budget-binding.json').name]) == binding,
                  'admission_budget_call_binding_changed')
        c.require(c.decode_json(data[output.with_suffix('.budget-result.json').name]) == row['result'],
                  'admission_budget_result_changed')
        adapter.StrictBudgetAdapter._evidence(output, binding, row['result']['executionStatus'], artifact)

    def snapshot(self):
        """Locked advisory state; no model call, approval or Layer 3 intent."""
        with self._locked() as (_, _, raw, ledger):
            return self._load(raw, ledger)

    def _validate(self, snapshot, created_at):
        if snapshot.diagnostics:
            return None, [], snapshot.diagnostics
        f = snapshot.files
        # Never synthesize BoundaryChecks for a failed/pending bridge.
        validated = bridge.validate_approved_chain(*(f[k] for k in ('source', 'anchor', 'policy', 'rubric')),
            snapshot.revisions, candidate=public_snapshot.decode_json(f['public_candidate']),
            human_receipt=c.decode_json(f['human_receipt']), plugin_path=self.config.plugin,
            expected_plugin_sha256=self.config.plugin_sha256)
        decisions = []
        for index, group in enumerate(snapshot.groups):
            checks = gate.BoundaryChecks(gate.snapshot_sha256(group), True, True, True, True,
                                         'valid', ('human_receipt',))
            evaluated = gate.evaluate_gate(group, gate_decision_id='gate-' + c.canonical_sha256([self.key, snapshot.state_revision, index])[:48],
                                            created_at=created_at, boundary_checks=checks)
            decisions.append(evaluated.decision)
        return validated, decisions, tuple(sorted({reason for decision in decisions
            if decision['admissionStatus'] != 'admitted' for reason in decision['reasonCodes']}))

    def admit(self, *, expected_state_revision, created_at):
        """CAS exact current evidence and persist permission; never dispatch."""
        budget._hash(expected_state_revision)
        try:
            with self._locked() as (path, record, raw, ledger):
                snapshot = self._load(raw, ledger)
                if snapshot.state_revision != expected_state_revision:
                    return self._result('stale', reasons=['stale_state_revision'])
                validated, decisions, reasons = self._validate(snapshot, created_at)
                if reasons:
                    return self._result('blocked', reasons=list(reasons), decisions=decisions)
                fresh = self._load(c.read_snapshot(path)[1], c.read_snapshot(
                    self.store.root / budget.STORE_ID / 'state.json')[0])
                if fresh.snapshot_sha256 != snapshot.snapshot_sha256:
                    return self._result('stale', reasons=['snapshot_changed'])
                if profile.current() is not None:
                    for decision in decisions:observations.record(decision)
                identity = {'schemaVersion': SCHEMA, 'productionRunId': self.config.production_run_id,
                    'targetLocale': self.config.target_locale, 'action': 'prepare_layer3',
                    'sourceIdentitySha256': snapshot.groups[0].current.source_identity_sha256,
                    'policySha256': snapshot.groups[0].current.policy_sha256,
                    'publicCandidateSha256': validated['publicCandidateSha256']}
                # A reissued valid human receipt may retain identical approved
                # Candidate bytes. Bind the permission to that receipt as the
                # downstream preparation adapter does. Preserve old-format
                # permissions only when their exact receipt still matches.
                legacy_key = c.canonical_sha256(identity)
                identity['humanReceiptSha256'] = validated['humanReceiptSha256']
                key = c.canonical_sha256(identity)
                if key in record['intents']:
                    existing = record['intents'][key]
                    c.require(existing['humanReceiptSha256'] == validated['humanReceiptSha256'],
                              'admission_intent_receipt_changed')
                    return self._result('existing', intent=existing)
                legacy = record['intents'].get(legacy_key)
                if legacy is not None and legacy['humanReceiptSha256'] == validated['humanReceiptSha256']:
                    return self._result('existing', intent=legacy)
                intent = {'intentId': key, 'identity': identity, 'action': 'prepare_layer3',
                    'executionAuthority': 'existing_layer3_adapter_only',
                    'stateRevision': snapshot.state_revision, 'snapshotSha256': snapshot.snapshot_sha256,
                    'publicCandidateSha256': validated['publicCandidateSha256'],
                    'humanReceiptSha256': validated['humanReceiptSha256'],
                    'decisions': decisions, 'createdAt': created_at}
                record['intents'][key] = intent
                c.require(len((json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())
                          <= c.MAX_BYTES, 'admission_registry_size_limit')
                try:
                    jobs._persist(path, record)
                    jobs._sync_directory_ancestry(path.parent)
                    if profile.current() is not None:
                        accounting.record_log('rqc_gate_commit',fields={'status':'committed','reasonCode':'prepare_layer3_intent'})
                except Exception:
                    return self._result('outcome_unknown', reasons=['reconcile_durable_intent'])
                return self._result('committed', intent=intent)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return self._result('blocked', reasons=['invalid_or_incomplete_evidence'], errorType=type(exc).__name__)

    def reconcile(self):
        """Recover an unknown commit without a second intent or model call.

        Returned intents are historical permission records, not a fresh claim
        that changed artifacts still pass. Consumers must revalidate evidence.
        """
        with self._locked() as (_, record, _, _):
            return self._result('reconciled', intents=list(record['intents'].values()))

    @staticmethod
    def _result(status, **fields):
        return {'schemaVersion': SCHEMA, 'status': status, 'dispatched': False,
                'accountingCoverage': 'profile_active' if profile.current() is not None else 'not_observed',
                'layer4Authority': 'none', **fields}
