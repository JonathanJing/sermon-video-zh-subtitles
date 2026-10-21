"""Layer 4: release packages per pageId + targetLocale.

Owns the release and catalog contracts, the formal stage and asset builders,
the four-product app release, guarded publication and the app delivery gate.
Modules arrive here one batch at a time (see
docs/design/l4-delivery-layer-injection.zh.md); until then this package holds
the injection boundary they will call through.
"""
