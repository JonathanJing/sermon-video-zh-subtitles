"""Freeze the actual canonical Layer 2 input closure before dispatch."""
from pathlib import Path
from scripts.sermon_unified import contracts as c
from scripts import canonical_layer2_controller as ctl


def inspect_bound(manifest, base, step, config_path):
    config = ctl.load_configuration(config_path)
    locale = step['locale']
    if locale not in config.lanes:
        raise c.ContractError('controller_locale_mismatch')
    snapshots = {}

    def bound(path):
        path = Path(path).resolve()
        names = [name for name, row in manifest['bindings'].items()
                 if (Path(base) / row['path']).resolve() == path]
        if not names:
            raise c.ContractError('layer2_input_binding_required:' + str(path))
        for name in names:
            c.binding(manifest, base, name)
        snapshots[str(path)] = c.file_sha(path)
        return path

    execution = c.read(bound(config.path))
    bound(config.path.parent / execution['inspectionConfig'])
    source_path = bound(config.inspection_root / config.inspection['source'])
    bound(config.inspection_root / config.inspection['anchor'])
    # All configured consumer lanes are inspected, even before this step is ready.
    for lane in config.lanes.values():
        bound(lane['policy'])
        bound(lane['plugin'])
    authority_path = c.binding(manifest, base, step['budgetAuthorization'])
    authority = c.read(bound(authority_path))
    # Authorization loader separately checks semantics; freeze nested approval bytes.
    def evidence(value, root):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
                path = (root / value['path']).resolve()
                if c.file_sha(path) != value['sha256']:
                    raise c.ContractError('layer2_nested_evidence_changed')
                snapshots[str(path)] = value['sha256']
            for item in value.values():
                evidence(item, root)
        elif isinstance(value, list):
            for item in value:
                evidence(item, root)
    source = c.read(source_path)
    evidence(source, config.inspection_root)
    evidence(authority, Path(authority_path).parent)
    approval_path = (Path(authority_path).parent / authority['approvalReceipt']).resolve()
    if c.file_sha(approval_path) != authority['authority']['approvalSha256']:
        raise c.ContractError('layer2_budget_approval_changed')
    snapshots[str(approval_path)] = authority['authority']['approvalSha256']
    actual, expected = source['source'], manifest['source']
    if (actual.get('sourceId') != expected['sourceId']
            or actual.get('sourceUrlHash') != expected['sourceUrlHash']
            or actual.get('media', {}).get('sha256') != expected['mediaSha256']
            or any(actual.get('approvedWindow', {}).get(k) != expected['window'][k]
                   for k in ('startSeconds', 'endSeconds'))):
        raise c.ContractError('controller_source_mismatch')
    for name, lane in config.lanes.items():
        policy = next((p for p in manifest['policies'] if p['locale'] == name), None)
        if policy is None or c.file_sha(lane['policy']) != policy['policySha256']:
            raise c.ContractError('controller_policy_mismatch')
    view = ctl.package_view(config)
    for name in config.lanes:
        ctl._inputs(config, name, view)
    if view.get('inspectionDiagnostics', {}).get('source'):
        raise c.ContractError('controller_source_not_validated')
    for path, sha in snapshots.items():
        if c.file_sha(path) != sha:
            raise c.ContractError('layer2_input_changed_during_inspection')
    return {'snapshotBound': True, 'inputsSha256': snapshots, 'configurationSha256': config.sha256}
