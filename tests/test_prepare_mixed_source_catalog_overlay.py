import json

from tools.ops import prepare_mixed_source_catalog_overlay as command


def test_cli_defaults_to_production_and_forwards_exact_paths(tmp_path, monkeypatch, capsys):
    paths = {name: tmp_path / name for name in ('baseline', 'catalog.json', 'plan.json', 'out')}
    observed = {}

    def prepare(baseline, catalog, plan, out, *, environment, asset_source):
        observed.update(baseline=baseline, catalog=catalog, plan=plan, out=out,
                        environment=environment, asset_source=asset_source)
        return {'status': 'prepared_not_deployed', 'pageId': 'family'}

    monkeypatch.setattr(command.baseline, 'mixed_source_catalog_overlay', prepare)
    assert command.main(['--baseline', str(paths['baseline']), '--catalog', str(paths['catalog.json']),
                         '--release-plan', str(paths['plan.json']), '--out', str(paths['out'])]) == 0
    assert observed == {'baseline': paths['baseline'], 'catalog': paths['catalog.json'],
                        'plan': paths['plan.json'], 'out': paths['out'],
                        'environment': 'production', 'asset_source': None}
    assert json.loads(capsys.readouterr().out) == {'status': 'prepared_not_deployed', 'pageId': 'family'}

    assert command.main(['--baseline', str(paths['baseline']), '--catalog', str(paths['catalog.json']),
                         '--release-plan', str(paths['plan.json']), '--out', str(paths['out']),
                         '--environment', 'dev', '--asset-source', str(tmp_path / 'source')]) == 0
    assert observed['environment'] == 'dev'
    assert observed['asset_source'] == tmp_path / 'source'


def test_cli_help_names_the_cas_inputs():
    try:
        command.main(['--help'])
    except SystemExit as error:
        assert error.code == 0
