"""Layer 1: shared English facts and anchors.

Owns the English Source Package, the machine judge, anchors, the MFA adapter
and transport and the Layer 1 budget. Producers arrive here one batch at a
time (see docs/design/l1-source-layer-injection.zh.md); until then this
package holds the injection boundary they already call through.
"""
