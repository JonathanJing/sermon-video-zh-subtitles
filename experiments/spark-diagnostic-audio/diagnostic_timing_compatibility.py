"""Narrow resume compatibility for PR #287's observational timing changes.

The pre-timing worker (ce0bd112's parent) and ce0bd112 differ only in
receipt timing. The current worker adds this identity lookup. Keep their
frozen run/batch identities intact; bind_run still checks every other field.
Future worker edits must not inherit this compatibility automatically.
"""

PRE_TIMING_WORKER = '771c8a314f7b11f13e4fa8fa6fb89dd3a584450a9ab9e8e8cbee915886d3ad88'
TIMING_WORKER = 'da9ac211cabfea991b891394310753044dde916e6b43b014b50bb0af9ce523dd'
COMPATIBLE_CURRENT_WORKER = 'a2db571f40633f48eec652e2caaa57a7ea4a8450b30321669d2d1c18cef9be88'


def compatible_worker(current, saved):
    if current == COMPATIBLE_CURRENT_WORKER and saved in (PRE_TIMING_WORKER, TIMING_WORKER):
        return saved
    return current
