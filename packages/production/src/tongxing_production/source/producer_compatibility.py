"""Exact reviewed source-producer migrations; no generic old-code waiver.

Only these exact old/new bytes are eligible. Inspect immutable historical Source
with zero new ASR/MFA; this does not claim re-execution under the new producer.
"""
import sys
from ..contracts.canonical import require as _require
from . import backend as _source


# Legacy identity keys stay the keys of every table and closure below; a moved
# file is reached through its alias in the shared table. These names stay here
# for the callers that already resolve through this module.
from ..path_aliases import PATH_ALIASES, recorded, resolve  # noqa: E402,F401


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

# The Layer 1 leaves moved into tongxing_production.source byte for byte. The two
# producers that located them as sibling files (anchor generator hash, Spark
# adapter bundle) now ask the code port; nothing else about Source changed.
MOVE_SOURCE_SHA256 = {**EXTRACTION_SOURCE_SHA256,
    'scripts/build_english_source_package.py': '2923477bf106c3eeade71aab3d3116cc853c4a94623cb16c481c9697a3925a0b',
    'scripts/mfa_spark.py': '76e68f26a781a67d25f4f07049a7ba341b8dfdc8f78ac136cb01c722345d869a'}
MOVE_MIGRATION = 'l1-source-package-move-v4'
MOVE_CHANGED = ['scripts/build_english_source_package.py', 'scripts/mfa_spark.py']

# The builder itself moved into the package; only its imports and the way it
# locates the judge, the anchor generator and itself changed.
PRODUCER_MOVE_SOURCE_SHA256 = {**MOVE_SOURCE_SHA256,
    'scripts/build_english_source_package.py': '51a2e2a00a6a6720f47067807c6cb5922c9094ec57111b8b47f628bdfe8fd250'}
PRODUCER_MOVE_MIGRATION = 'l1-source-producers-package-move-v5'
PRODUCER_MOVE_CHANGED = ['scripts/build_english_source_package.py']

# The MFA backend and Spark transport moved into the package. Their imports
# changed; the backend takes MFA options and the adapter path from the ports.
# The adapter they ship and hash (mfa_alignment) is byte-identical.
TRANSPORT_MOVE_SOURCE_SHA256 = {**PRODUCER_MOVE_SOURCE_SHA256,
    'scripts/mfa_backend.py': 'f535d1a8338a0914ba58148f364421a1b30822c9aa6197cfecbb9b9e9a94d982',
    'scripts/mfa_spark.py': 'ee5272d62fa81b2576279f9e92ba44fb8f87d539aac3760ed5e4829164ddbee1'}
TRANSPORT_MOVE_MIGRATION = 'l1-source-mfa-transport-package-move-v6'
TRANSPORT_MOVE_CHANGED = ['scripts/mfa_backend.py', 'scripts/mfa_spark.py']

# Infrastructure I1 split sermon_review_contracts: its review half moved into
# review/contracts.py and imports canonical JSON, error codes and schema checks
# from contracts/, with the same output bytes. The checkout before I1 had already
# drifted from the v6 table in four files (no reviewed generation covers that
# drift), so the historical side is the exact dev checkout I1 started from.
CONTRACTS_SPLIT_HISTORICAL_SHA256 = {**TRANSPORT_MOVE_SOURCE_SHA256,
    'scripts/mfa_alignment.py': 'e1dd12f3fc5bff6d99bd89d28e9ac764c2662b54222bcef1f911772e5adac8bd',
    'scripts/sermon_diagnostic_context.py': '6af31378cfa0cf353f3a5e4aff519085bd6252a8f86e73570614709cfb890383',
    'scripts/sermon_review_contracts.py': '71e7fa802fad3cac9788b1163907da3b908d4410777552333d46034754db89f2',
    'scripts/sermon_sentence_interpretation.py': '5aa19b0580febb3652f9b694cf2ac9f1cbba1c241320c02396a99f0a63a439c1'}
CONTRACTS_SPLIT_SOURCE_SHA256 = {**CONTRACTS_SPLIT_HISTORICAL_SHA256,
    'scripts/sermon_review_contracts.py': '663e7da5d1d2f26fb7191d7146f2693242ae5318d7188b17ab1fafcfef4de17d'}
CONTRACTS_SPLIT_MIGRATION = 'i1-review-contracts-split-package-move-v7'
CONTRACTS_SPLIT_CHANGED = ['scripts/sermon_review_contracts.py']


def verify(historical,current,planned,binding):
    _require(type(historical) is dict and type(current) is dict and type(planned) is dict
        and set(historical)==set(current)==set(HISTORICAL_SOURCE_SHA256)
        and all(recorded(planned,path)==sha for path,sha in current.items()),
        'source_producer_compatibility_new_identity_changed')
    if historical==current:
        return None
    original = historical==HISTORICAL_SOURCE_SHA256 and current==CURRENT_SOURCE_SHA256
    followup = historical==CURRENT_SOURCE_SHA256 and current==FOLLOWUP_SOURCE_SHA256
    extraction = historical==FOLLOWUP_SOURCE_SHA256 and current==EXTRACTION_SOURCE_SHA256
    move = historical==EXTRACTION_SOURCE_SHA256 and current==MOVE_SOURCE_SHA256
    producer_move = historical==MOVE_SOURCE_SHA256 and current==PRODUCER_MOVE_SOURCE_SHA256
    transport_move = historical==PRODUCER_MOVE_SOURCE_SHA256 and current==TRANSPORT_MOVE_SOURCE_SHA256
    contracts_split = historical==CONTRACTS_SPLIT_HISTORICAL_SHA256 and current==CONTRACTS_SPLIT_SOURCE_SHA256
    package_move = move or producer_move or transport_move or contracts_split
    changed = (CHANGED if original else MOVE_CHANGED if move else PRODUCER_MOVE_CHANGED if producer_move
        else TRANSPORT_MOVE_CHANGED if transport_move else CONTRACTS_SPLIT_CHANGED if contracts_split
        else ['scripts/sermon_fresh_diagnostic_source.py'])
    _require((original or followup or extraction or package_move) and {path for path in current if current[path]!=historical[path]}==set(changed),
        'source_producer_compatibility_unknown_revision')
    _require(type(binding) is dict and set(binding)=={'parentPlanSha256','newPlanSha256',
        'sourceCanonicalSha256','anchorCanonicalSha256','alignmentBytesSha256','asrReceiptSha256','sourceCheckReceiptSha256'}
        and all(type(value) is str and len(value)==64 and all(ch in '0123456789abcdef' for ch in value)
                for value in binding.values()),'source_producer_compatibility_binding_required')
    migration = (MIGRATION if original else MOVE_MIGRATION if move else PRODUCER_MOVE_MIGRATION if producer_move
        else TRANSPORT_MOVE_MIGRATION if transport_move else CONTRACTS_SPLIT_MIGRATION if contracts_split
        else EXTRACTION_MIGRATION if extraction else FOLLOWUP_MIGRATION)
    return {'schemaVersion':SCHEMA,'migrationId':migration,'binding':binding,
        'historicalProducerSha256':historical,'currentInspectorProducerSha256':current,
        'changedModules':changed,'migrationCodeSha256':_source.current().code.module_sha256(sys.modules[__name__]),
        'acceptedScope':('original_deadline_and_typed_failures_only_no_source_semantic_change' if original else
            'read_only_original_source_under_package_move_no_new_inference' if package_move else
            'read_only_original_source_under_fixed_stage_extraction_no_new_inference' if extraction else
            'read_only_original_source_under_typed_completion_and_identity_inspector_no_new_inference'),
        'sourceExecution':'historical_receipts_reused_current_deterministic_inspection',
        'historicalSourcePreserved':True,'newASRCalls':0,'newSourceCheckCalls':0,'newMFACalls':0,
        'productionEligible':False,'humanAcceptance':'pending','executionAuthority':'none'}
