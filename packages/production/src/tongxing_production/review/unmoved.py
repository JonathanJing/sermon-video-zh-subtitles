"""Host modules and records the moved adjudicators still reach, under their old names.

Review imports no stage layer (review design section 3, rule 6). Each name here looks its
target up through the ReviewBackend at every use, so these modules import without a host
and an attribute patch on a host module still lands where the code calls it. Drop a name
when its module moves into the package.
"""
from __future__ import annotations

from . import backend as _review


class _HostModule:
    def __init__(self, get):
        object.__setattr__(self, '_get', get)

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def __setattr__(self, name, value):
        setattr(self._get(), name, value)

    def __delattr__(self, name):
        delattr(self._get(), name)


class _Renamed:
    """A record's fields under a module's former attribute names; ``values`` are accessors."""

    def __init__(self, get, functions, values=()):
        self._get, self._functions, self._values = get, dict(functions), dict(values)

    def __getattr__(self, name):
        record = self._get()
        if name in self._values:
            return getattr(record, self._values[name])()
        if name in self._functions:
            return getattr(record, self._functions[name])
        raise AttributeError(name)


def _current():
    return _review.current()


# Layer 1 source text review module (MACHINE_*, STATUS, SUPPORTED_MODELS, text_sha256, ...).
source_review = _HostModule(lambda: _current().source.text_review())
# Layer 2 policy: review uses canonical_sha256, a field of the same name on TextRules.
policies = _HostModule(lambda: _current().text)
# The audio QC transports (CallCache, TRANSCRIBE_URL, _multipart, qwen_inference_identity).
transports = _HostModule(lambda: _current().transports.audio_qc())
# The durable job store module (its private names are the host's to lend).
jobs = _HostModule(lambda: _current().core.jobs)
# Sentence interpretation file and JSON hashes: same names on SourceEvidence.
contract = _HostModule(lambda: _current().source)
# The Layer 2 controller's code identity: Code.code_identity.
controller = _HostModule(lambda: _current().code)
judge_cache = _Renamed(lambda: _current().source,
                       {'cached_call': 'judge_cached_call',
                        'reconcile_returned_response': 'reconcile_returned_response',
                        '_atomic': 'atomic_json'},
                       {'RUN_SCHEMA': 'judge_run_schema'})
source_budget = _Renamed(lambda: _current().source, {},
                         {'SourceBudget': 'source_budget', 'METRICS': 'budget_metrics'})
# Layer 2 human rulings: SCHEMA and load, as TextRules fields.
human_ruling = _Renamed(lambda: _current().text, {'load': 'load_human_ruling'}, {'SCHEMA': 'human_ruling_schema'})


def _model_result(response, requested_model):
    """The anchor model runner's result parsing (SourceEvidence.model_result)."""
    return _current().source.model_result(response, requested_model)


# The scripture library modules, whose files stay where plugins hash them.
cuv_scripture = _HostModule(lambda: _current().scripture.cuv())
scripture_editions = _HostModule(lambda: _current().scripture.editions())
coverage_module = _HostModule(lambda: _current().scripture.coverage())
queue_module = _HostModule(lambda: _current().scripture.candidate_queue())


# R3's review closure reaches stage and R4 modules through the already bound ports.
plugin_rules = _HostModule(lambda: _current().plugins.module('language_review_plugins.auto_qc_text_common'))
audio_rules = _Renamed(lambda: _current().audio,
                       {'registered_normalization_policy': 'registered_normalization_policy'})
predicted_rules = _Renamed(lambda: _current().audio,
                           {'_check_identity': 'check_identity', 'policy_texts': 'policy_texts',
                            'speech_units': 'speech_units', 'budget': 'budget'},
                           {'SCHEMA': 'predicted_schema'})
freeze = _HostModule(lambda: _current().qc_runtime.implementation_freeze())
audio_waiver_acceptance = _HostModule(lambda: _current().qc_runtime.audio_waiver_acceptance())
codex_text_transport = _HostModule(lambda: _current().qc_runtime.codex_text_transport())
audio_qc_transports = _HostModule(lambda: _current().transports.audio_qc())
transcription_limits = _HostModule(lambda: _current().provider.transcription_limits())
