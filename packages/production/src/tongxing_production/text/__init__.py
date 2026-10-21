"""Layer 2: target-language candidates per locale.

Owns the frozen translation policy, candidate production and review, the
model runners and the per-locale controller. Modules arrive here one batch at
a time (see docs/design/l2-text-layer-injection.zh.md); until then this package
holds the injection boundary they will call through.
"""
