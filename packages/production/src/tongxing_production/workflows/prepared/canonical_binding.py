"""Tie existing canonical inspection to the active unified run's frozen source."""
from pathlib import Path
from scripts.sermon_unified import contracts as c
from scripts import inspect_canonical_packages as packages


def inspect_bound(manifest, base, configuration_path, step):
    config_path = Path(configuration_path).resolve()
    config = c.read(config_path)
    source_path = (config_path.parent / config['source']).resolve()
    # Config bytes alone do not freeze the JSON files named inside them.
    names = [name for name, row in manifest['bindings'].items()
             if (Path(base) / row['path']).resolve() == source_path]
    if not names:
        raise c.ContractError('canonical_source_binding_required')
    for name in names:
        c.binding(manifest, base, name)
    # Every configured JSON consumer is frozen, not just the source pointer.
    # Media directories are verified against the bound package/manifest hashes
    # by the canonical inspectors; they are not opaque directory bindings.
    references=[config[key] for key in ('anchor',) if key in config]
    for lane in config.get('locales',{}).values():
        for field,value in lane.items():
            if isinstance(value,str):
                references.append(value)
            elif field in ('audio','release') and isinstance(value,dict):
                references.extend(path for key,path in value.items() if key not in ('artifactRoot','assetRoot'))
    for reference in references:
        path=(config_path.parent/reference).resolve()
        bound_names=[name for name,row in manifest['bindings'].items()
                     if (Path(base)/row['path']).resolve()==path]
        if not bound_names:
            raise c.ContractError('canonical_consumer_binding_required')
        for name in bound_names:
            c.binding(manifest,base,name)
            if name not in names:names.append(name)
    source = c.read(source_path)
    expected = manifest['source']
    actual = source.get('source', {})
    window = actual.get('approvedWindow', {})
    if (actual.get('sourceId') != expected['sourceId']
            or actual.get('media', {}).get('sha256') != expected['mediaSha256']
            or actual.get('sourceUrlHash') != expected['sourceUrlHash']
            or actual.get('media', {}).get('durationSeconds') != expected.get('durationSeconds')
            or (window.get('evidence') or {}).get('sha256') != expected['window'].get('approvalReceiptSha256')
            or any(window.get(key) != expected['window'][key] for key in ('startSeconds', 'endSeconds'))):
        raise c.ContractError('canonical_source_identity_changed')
    locale = step.get('locale')
    if locale is not None:
        if locale not in config['locales']:
            raise c.ContractError('canonical_locale_changed')
        policy = next((row for row in manifest['policies'] if row['locale'] == locale), None)
        policy_path = config_path.parent / config['locales'][locale]['policy']
        if policy is None or c.file_sha(policy_path) != policy['policySha256']:
            raise c.ContractError('canonical_policy_changed')
    if step['stageId']!='english_source':
        validate_selected_source(manifest,base,c.digest(source))
    result = packages.inspect(config_path)
    if result.get('packageIdentities', {}).get('source') != c.digest(source):
        raise c.ContractError('canonical_source_changed_during_inspection')
    for name in names:
        c.binding(manifest, base, name)
    return result


def validate_selected_source(manifest, base, actual_sha):
    """Bind consumers to the selected English package, including its text.

    Same recording/window does not authorize substituting a different English
    revision. Component helpers without a run DAG retain their legacy scope.
    """
    selected = []
    for step in manifest.get('steps', []):
        if step['adapter'] != 'canonical.inspect' or step['stageId'] != 'english_source':
            continue
        config_path = c.binding(manifest, base, step['configuration'])
        config = c.read(config_path)
        path = (config_path.parent / config['source']).resolve()
        names = [name for name, ref in manifest['bindings'].items()
                 if (Path(base) / ref['path']).resolve() == path]
        if not names:
            raise c.ContractError('selected_source_binding_required')
        for name in names:
            c.binding(manifest, base, name)
        selected.append(c.digest(c.read(path)))
    if not selected and manifest.get('schemaVersion') == 'sermon-unified-run-manifest-v2':
        raise c.ContractError('selected_english_source_required')
    if selected and (len(set(selected)) != 1 or actual_sha != selected[0]):
        raise c.ContractError('selected_english_source_changed')
    return actual_sha
