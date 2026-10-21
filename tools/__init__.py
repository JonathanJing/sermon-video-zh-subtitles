"""Operator (``tools.ops``) and development (``tools.development``) tools of this checkout.

A regular package, not a namespace one: the Spark images ship a third-party ``tools``
package in site-packages, and a regular package anywhere on ``sys.path`` beats a namespace
portion, so ``tools.ops.render_multilingual_voice_demos`` (which the host loads with the
renderer) would resolve into the image's package. The checkout precedes site-packages on
the container ``PYTHONPATH``, so this package wins there.
"""
