import copy
import json
import pytest
from scripts import sermon_unified_canonical_binding as adapter
from scripts.sermon_unified import contracts as c


def setup(tmp_path):
    source = {'source': {'sourceId': 'fixture', 'sourceUrlHash': 'a' * 64, 'media': {'sha256': 'b' * 64},
                         'approvedWindow': {'startSeconds': 0, 'endSeconds': 60}}}
    source_path = tmp_path / 'source.json'; source_path.write_text(json.dumps(source))
    config_path = tmp_path / 'config.json'; config_path.write_text(json.dumps({'source': 'source.json', 'locales': {}}))
    manifest = {'source': {'sourceId': 'fixture', 'sourceUrlHash': 'a' * 64, 'mediaSha256': 'b' * 64, 'window': {'startSeconds': 0, 'endSeconds': 60}},
                'bindings': {'source': {'path': str(source_path), 'sha256': c.file_sha(source_path)}}}
    return source, manifest, config_path


def test_validated_inspector_cannot_hide_active_source_drift(tmp_path, monkeypatch):
    source, manifest, config = setup(tmp_path)
    monkeypatch.setattr(adapter.packages, 'inspect', lambda path: {'nodes': {'source': {'status': 'validated'}}, 'packageIdentities': {'source': c.digest(source)}})
    assert adapter.inspect_bound(manifest, tmp_path, config, {'stageId': 'english_source'})['nodes']['source']['status'] == 'validated'
    for key in ('mediaSha256', 'sourceId', 'sourceUrlHash'):
        changed = copy.deepcopy(manifest); changed['source'][key] = 'wrong'
        with pytest.raises(c.ContractError, match='canonical_source_identity_changed'):
            adapter.inspect_bound(changed, tmp_path, config, {'stageId': 'english_source'})
    changed = copy.deepcopy(manifest); changed['source']['window']['endSeconds'] = 59
    with pytest.raises(c.ContractError, match='canonical_source_identity_changed'):
        adapter.inspect_bound(changed, tmp_path, config, {'stageId': 'english_source'})


def test_config_binding_alone_does_not_freeze_nested_source(tmp_path):
    source, manifest, config = setup(tmp_path)
    manifest['bindings'] = {}
    with pytest.raises(c.ContractError, match='canonical_source_binding_required'):
        adapter.inspect_bound(manifest, tmp_path, config, {'stageId': 'english_source'})


def test_candidate_consumer_cannot_change_under_frozen_config(tmp_path, monkeypatch):
    source, manifest, config = setup(tmp_path)
    candidate=tmp_path/'candidate.json';candidate.write_text('{}')
    value=json.loads(config.read_text());value['locales']={'zh-Hans':{'candidate':'candidate.json'}}
    config.write_text(json.dumps(value))
    with pytest.raises(c.ContractError,match='canonical_consumer_binding_required'):
        adapter.inspect_bound(manifest,tmp_path,config,{'stageId':'english_source'})
    manifest['bindings']['candidate']={'path':str(candidate),'sha256':c.file_sha(candidate)}
    candidate.write_text('{"changed":true}')
    with pytest.raises(c.ContractError,match='binding_changed'):
        adapter.inspect_bound(manifest,tmp_path,config,{'stageId':'english_source'})
