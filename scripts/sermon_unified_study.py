"""Freeze supplied study text in the owner, independently of audio and PDFs."""
from scripts.sermon_unified import contracts as c
from scripts import study_artifacts as study
from scripts.sermon_unified_reviews import validate_review
from scripts.sermon_execution_harness import atomic_json


def inspect(manifest,base,configuration_path,step):
    config=c.read(configuration_path)
    if (set(config)!={'schemaVersion','kind','producerIdentity','inputs'}
        or config['schemaVersion']!='sermon-unified-study-inputs-v1'
        or config['kind'] not in ('outline','meditation')
        or not isinstance(config['producerIdentity'],str) or not config['producerIdentity'].strip()
        or set(config['inputs'])!={'source','anchor','candidate','translationReview','sections'}):
        raise c.ContractError('study_configuration_invalid')
    inputs={key:c.binding(manifest,base,name) for key,name in config['inputs'].items()}
    validate_review('translation',inputs['translationReview'],inputs=inputs,
                    expected_source=manifest['source'],expected_locale=step['locale'])
    source=c.read(inputs['source']);candidate=c.read(inputs['candidate']);anchor=c.read(inputs['anchor'])
    sections=c.read(inputs['sections'])
    artifact=study.produce(config['kind'],sections,page_id=manifest['content']['pageId'],locale=step['locale'],
                           source_sha=c.digest(source),text_sha=c.digest(candidate),producer_identity=config['producerIdentity'])
    unit_ids={unit['sourceUnitId'] for unit in anchor['sourceUnits']}
    if any(not set(section['sourceUnitIds'])<=unit_ids for section in sections):
        raise c.ContractError('study_source_units_changed')
    return artifact


def execute(manifest,base,configuration_path,step,output):
    artifact=inspect(manifest,base,configuration_path,step)
    target=output.parent/(step['id']+'-study.json')
    if target.exists():
        if c.read(target)!=artifact:
            raise c.ContractError('study_output_changed')
    else:
        atomic_json(target,artifact)
    return {'status':'succeeded','kind':'study_candidate','artifact':'verified','review':'human_pending',
            'productionEligible':False,'path':str(target),'sha256':c.file_sha(target),
            'jsonSha256':c.digest(artifact),'freshApiAttempts':0}
