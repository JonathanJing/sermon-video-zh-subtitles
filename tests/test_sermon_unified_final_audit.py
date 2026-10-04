"""Focused integration regressions identified in final adapter audit."""
import json
from unittest.mock import patch
from scripts import sermon_unified_study as study
from scripts.sermon_unified import contracts as c


def test_study_reads_canonical_source_units(tmp_path):
    # Approval validity has separate real-fixture tests; exercise the downstream
    # consumer with the exact canonical anchor field, real bindings and schema.
    values={'source':{},'anchor':{'sourceUnits':[{'sourceUnitId':'u1'}]},
            'candidate':{},'translationReview':{},
            'sections':[{'title':'Title','body':'Body','sourceUnitIds':['u1']}]}
    bindings={}
    for name,value in values.items():
        path=tmp_path/(name+'.json');path.write_text(json.dumps(value))
        bindings[name]={'path':str(path),'sha256':c.file_sha(path)}
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'schemaVersion':'sermon-unified-study-inputs-v1',
        'kind':'outline','producerIdentity':'fixture','inputs':{k:k for k in values}}))
    manifest={'bindings':bindings,'source':{},'content':{'pageId':'p'}}
    with patch.object(study,'validate_review',return_value={'status':'validated'}):
        artifact=study.inspect(manifest,tmp_path,config,{'locale':'es'})
    assert artifact['sections'][0]['sourceUnitIds']==['u1']
