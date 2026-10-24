"""Frozen Layer 3 identity values that Layer 2 planning reads without loading the renderer.

``orchestration/group_plan.py`` and ``group_pipeline.py`` record
``rendererSoundIdentitySha256`` in every ``sermon-group-stage-record-v1`` stage plan.
Importing ``audio.renderer`` for that one constant loads the whole TTS stack (Spark
replica pool, window scheduler, CPU bounding, anomaly and recovery modules, the
voice-demo and Korean numeral entries), which put about twenty Layer 3 files into
the Layer 2 code closure (``config/layer2-code-closure.json``). This module has no
imports, so the closure tracer stops here.

``renderer.py`` keeps its own copy of the value on purpose: that file is inside the
machine-quality waiver's frozen closure (``review/waiver.py``
``IMPLEMENTATION_PHYSICAL_FILES`` resolves ``scripts/render_formal_target_language_speech.py``
to it), so editing it would move ``machineQcImplementationSha256`` and invalidate issued
waivers. ``tests/test_layer2_code_closure.py`` fails if the two copies differ; when a
closure window next edits ``renderer.py``, make it import the value from here.
"""
from __future__ import annotations

# Observability-only renderer edits must not invalidate already rendered sound; this is
# the frozen sound identity, not the renderer file's current hash (``renderer._renderer_sha256``).
RENDERER_SOUND_IDENTITY_SHA256 = "fef7604882470137f46f1b01fbd06c7c3c9a07166da91003243608785fa47f0b"
