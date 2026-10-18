"""Host modules the audio QC transport still reaches, under their old names.

The waiver rules and the audio QC checks move with review R3, the Layer 3 screener,
predicted schedule and formal renderer with L3 A3; until then the host lends them
through ComputeBackend.unmoved. Each name looks its module up at every use, so this
package imports without a host and a patch on the host module still lands. Drop a name
when its module moves.
"""
from __future__ import annotations

from . import backend as _compute


class _HostModule:
    def __init__(self, get):
        object.__setattr__(self, '_get', get)

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def __setattr__(self, name, value):
        setattr(self._get(), name, value)

    def __delattr__(self, name):
        delattr(self._get(), name)


def _module(field):
    return _HostModule(lambda: getattr(_compute.current().unmoved, field)())


waiver = _module('waiver')                          # machine_quality_waiver (review R3)
audio_qc = _module('audio_qc')                      # target_audio_auto_qc (review R3)
budget_authorization = _module('budget_authorization')   # machine_qc_budget_authorization (review R3)
screener = _module('screener')                      # screen_target_language_audio_units (L3 A3)
predicted_schedule = _module('predicted_schedule')  # target_audio_predicted_schedule (L3 A3)
formal = _module('formal_renderer')                 # render_formal_target_language_speech (L3 A3)
demos = _module('voice_demos')                      # render_multilingual_voice_demos
jobs = _module('jobs')                              # sermon_workflow_jobs (split in the closure window)
