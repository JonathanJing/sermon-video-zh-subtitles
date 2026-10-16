"""Legacy Layer 4 delivery: catalog v2, release v1, weekly.json and the v3 assembler.

These producers keep their own interfaces (L4 design decision 5): they are not
merged with the four-product delivery in ``tongxing_production.delivery``. They
read the host through the configured ``DeliveryBackend`` at call time, and the
old-format poster renderer ships beside its Python caller as package data.
"""
