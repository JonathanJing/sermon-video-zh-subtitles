"""Host modules and records Layer 3 still reaches, under the names its modules used.

Accounting, producer timing, the spoken-number and citation rules (pinned in scripts/
by L3 decision 3) and the voice checkpoint reader come through AudioBackend records.
Each name looks its target up at every use, so a patch on the host module still lands
where the code calls it. Renamed record fields are mapped to the old attribute names.
"""
from __future__ import annotations

from . import backend as _audio


class _HostModule:
    def __init__(self, get):
        object.__setattr__(self, '_get', get)

    def __getattr__(self, name):
        return getattr(self._get(), name)


class _Renamed:
    """A record's fields under a module's former attribute names; ``values`` are accessors."""

    def __init__(self, get, functions=(), values=()):
        self._get, self._functions, self._values = get, dict(functions), dict(values)

    def __getattr__(self, name):
        record = self._get()
        if name in self._values:
            return getattr(record, self._values[name])()
        if name in self._functions:
            return getattr(record, self._functions[name])
        raise AttributeError(name)


def _current():
    return _audio.current()


# sermon_accounting: the four functions Layer 3 calls, as Accounting port fields.
accounting = _Renamed(lambda: _current().accounting,
                      {'accounting_session': 'session', 'stage': 'stage', 'record_workload': 'record_workload',
                       'bounded_dependencies': 'bounded_dependencies'})
# four_layer_measure: producer timing, same names on the Measure port.
measure = _HostModule(lambda: _current().measure)
# render_multilingual_voice_demos: the checkpoint map reader and checkpoint check.
demos = _Renamed(lambda: _current().tts_runtime,
                 {'read_object': 'read_checkpoint_map', 'validate_checkpoint': 'validate_checkpoint'})
# ko_spoken_numerals (stays in scripts/): rules, spoken forms and pattern constants.
ko_spoken_numerals = _Renamed(lambda: _current().spoken_rules,
    {'spoken_form': 'spoken_form', 'spoken_form_v2': 'spoken_form_v2', 'spoken_form_v3': 'spoken_form_v3',
     'equivalent': 'equivalent', 'bare_context_allowed': 'bare_context_allowed',
     'bare_citation_matches': 'bare_citation_matches'},
    {'RULE': 'ko_rule', 'RULE_V2': 'ko_rule_v2', 'RULE_V3': 'ko_rule_v3', '_PARTICLES': 'ko_particles',
     '_CONNECTOR': 'ko_connector', '_RANGE_PARTICLE': 'ko_range_particle', '_DELIMITERS': 'ko_delimiters',
     '_NUMERIC_TOKEN': 'ko_numeric_token', '_CITATIONS': 'ko_citations'})
# language_review_plugins.auto_qc_text_common (stays in scripts/): folding and citation rules.
rules = _Renamed(lambda: _current().spoken_rules,
    {'_fold': 'fold', '_ko_pattern': 'ko_pattern', 'book_citations': 'book_citations',
     'english_numbers': 'english_numbers', 'korean_sino': 'korean_sino', 'korean_native': 'korean_native'},
    {'_EN_BOOK_CODES': 'en_book_codes', '_ES_BOOK_CODES': 'es_book_codes', '_KO_BOOK_CODES': 'ko_book_codes',
     '_ZH_BOOK_CODES': 'zh_book_codes', '_KO_CITATION': 'ko_citation', '_KO_COUNTERS': 'ko_counters',
     '_ZH_MEASURE_WORDS': 'zh_measure_words'})
