"""Layer 3: audio and synchronization packages per locale.

Owns the frozen speech job, formal rendering and silence compaction,
back-transcription screening, the predicted schedule, the Target-Language
Audio Package and its listening review. Modules arrive here one batch at a
time (see docs/design/l3-audio-layer-injection.zh.md); until then this package
holds the injection boundary they will call through.
"""
