"""Exact reviewed source-producer migrations; no generic old-code waiver.

Only these exact old/new bytes are eligible. Inspect immutable historical Source
with zero new ASR/MFA; this does not claim re-execution under the new producer.
"""
from pathlib import Path
from scripts import sermon_review_contracts as c
SCHEMA='sermon-source-producer-compatibility-v1'
MIGRATION='mfa-original-deadline-and-source-failure-classification-v1'
HISTORICAL_SOURCE_SHA256= {'scripts/build_english_source_package.py': '65024b7cf518a90f800a8042e6a3206cbb83bde6a424258c850aa47e1e0ef740', 'scripts/four_layer_measure.py': '7f628c8c79b9cab65b25c23cc5b4df9a5154b0129726607fa3a2f56aa9f9c2fd', 'scripts/mfa_alignment.py': '6183298a18704f32336bd543a157fc7dbdfd83776baa2cf1155cc71ff872ddc3', 'scripts/mfa_backend.py': '4cd8c6606b65f686bfa6bea9af82f3e15e0be02740e82124ef7ea6312788e246', 'scripts/mfa_spark.py': '0d659a2361b67ccfe2892cc80deaca03c9aea7e3771a5033df7b3de743689a8b', 'scripts/sermon_diagnostic_context.py': '212d95511bd0b4536f574fb538f5cd599f80b5a203615a3ba88618a5f72630bb', 'scripts/sermon_fresh_diagnostic_source.py': 'c70ef5edea80ee2d7c7e0639d253fe52e57e6383673563c93c80b677ed99c1db', 'scripts/sermon_public_snapshot.py': '824d43f2ff64e473277e1a26447a8d4c435b5d5b5a93498be29320a6225c6af8', 'scripts/sermon_review_contracts.py': '17cf677ee068cd898b90310c2ff489b9bce01b9333bc59c0a5c23a6d3a115466', 'scripts/sermon_sentence_interpretation.py': '028b9123c53d9509a965f6c49fa3116f129a9b444202cecab9b3ce71b0aced45'}
CURRENT_SOURCE_SHA256= {'scripts/build_english_source_package.py': '65024b7cf518a90f800a8042e6a3206cbb83bde6a424258c850aa47e1e0ef740', 'scripts/four_layer_measure.py': '7f628c8c79b9cab65b25c23cc5b4df9a5154b0129726607fa3a2f56aa9f9c2fd', 'scripts/mfa_alignment.py': '8394fec4c556303146b87b1c53144c7ac3c27397f5da523f8ee9fe30b5cf9123', 'scripts/mfa_backend.py': '343220c9aeceeb7fdb1f1e35d81083134d8928db812d7c67fa8bbe28595feb43', 'scripts/mfa_spark.py': '0d659a2361b67ccfe2892cc80deaca03c9aea7e3771a5033df7b3de743689a8b', 'scripts/sermon_diagnostic_context.py': '212d95511bd0b4536f574fb538f5cd599f80b5a203615a3ba88618a5f72630bb', 'scripts/sermon_fresh_diagnostic_source.py': 'b233d6a03ae66961220c13f1a67a5aefa1e821ad117a4249dedb53d5a9b9663d', 'scripts/sermon_public_snapshot.py': '824d43f2ff64e473277e1a26447a8d4c435b5d5b5a93498be29320a6225c6af8', 'scripts/sermon_review_contracts.py': '17cf677ee068cd898b90310c2ff489b9bce01b9333bc59c0a5c23a6d3a115466', 'scripts/sermon_sentence_interpretation.py': '028b9123c53d9509a965f6c49fa3116f129a9b444202cecab9b3ce71b0aced45'}
CHANGED= ['scripts/mfa_alignment.py', 'scripts/mfa_backend.py', 'scripts/sermon_fresh_diagnostic_source.py']

# Exact reviewed dev producer -> typed-completion/identity-inspection adapter.
# Only read-only reuse of its unchanged Source artifact is admitted.
FOLLOWUP_SOURCE_SHA256 = {**CURRENT_SOURCE_SHA256,
    'scripts/sermon_fresh_diagnostic_source.py': 'd0d2f0dcdbbb98a126a4f83820c2791a2116b5be085221bfa9dd23dd42846be6'}
FOLLOWUP_MIGRATION = 'fresh-source-typed-leaves-and-mfa-identity-v2'

# Preserve both earlier exact transitions; this independently reviewed refactor
# only changes fixed stage composition and read-only original result adoption.
EXTRACTION_SOURCE_SHA256 = {**FOLLOWUP_SOURCE_SHA256,
    'scripts/sermon_fresh_diagnostic_source.py': 'cfb2677efea593c9d680435de5582f5df1cfda83bd76899dcaae9ba5c706aed0'}
EXTRACTION_MIGRATION = 'fresh-source-fixed-stage-extraction-v3'


def verify(historical,current,planned,binding):
    c.require(type(historical) is dict and type(current) is dict and type(planned) is dict
        and set(historical)==set(current)==set(HISTORICAL_SOURCE_SHA256)
        and all(planned.get(path)==sha for path,sha in current.items()),
        'source_producer_compatibility_new_identity_changed')
    if historical==current:
        return None
    original = historical==HISTORICAL_SOURCE_SHA256 and current==CURRENT_SOURCE_SHA256
    followup = historical==CURRENT_SOURCE_SHA256 and current==FOLLOWUP_SOURCE_SHA256
    extraction = historical==FOLLOWUP_SOURCE_SHA256 and current==EXTRACTION_SOURCE_SHA256
    changed = CHANGED if original else ['scripts/sermon_fresh_diagnostic_source.py']
    c.require((original or followup or extraction) and {path for path in current if current[path]!=historical[path]}==set(changed),
        'source_producer_compatibility_unknown_revision')
    c.require(type(binding) is dict and set(binding)=={'parentPlanSha256','newPlanSha256',
        'sourceCanonicalSha256','anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256'}
        and all(type(value) is str and len(value)==64 and all(ch in '0123456789abcdef' for ch in value)
                for value in binding.values()),'source_producer_compatibility_binding_required')
    return {'schemaVersion':SCHEMA,'migrationId':MIGRATION if original else EXTRACTION_MIGRATION if extraction else FOLLOWUP_MIGRATION,'binding':binding,
        'historicalProducerSha256':historical,'currentInspectorProducerSha256':current,
        'changedModules':changed,'migrationCodeSha256':c.bytes_sha256(Path(__file__).read_bytes()),
        'acceptedScope':('original_deadline_and_typed_failures_only_no_source_semantic_change' if original else
            'read_only_original_source_under_fixed_stage_extraction_no_new_inference' if extraction else
            'read_only_original_source_under_typed_completion_and_identity_inspector_no_new_inference'),
        'sourceExecution':'historical_receipts_reused_current_deterministic_inspection',
        'historicalSourcePreserved':True,'newASRCalls':0,'newSourceCheckCalls':0,'newMFACalls':0,
        'productionEligible':False,'humanAcceptance':'pending','executionAuthority':'none'}
