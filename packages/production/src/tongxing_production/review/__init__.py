"""Cross-layer machine review: receipts, fixed gates and revision rules.

Owns machine QC, waivers and their calibration, the repair ledger, machine
adjudication of source meaning and scripture, unified review ingestion and the
review budget ledger. It sits below the stages: every stage may import it, and
it reaches a stage only through its backend. Modules arrive here one batch at a
time (see docs/design/review-layer-injection.zh.md); until then this package
holds the injection boundary they will call through.
"""
