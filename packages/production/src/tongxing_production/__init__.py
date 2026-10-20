"""Production package for the four-layer sermon pipeline.

Modules move here from ``scripts/`` one at a time; each old path stays as a
thin facade until no caller imports it. Nothing in this package may import
``scripts``, ``backend``, ``apps``, ``tools`` or ``experiments``, or locate
resources relative to a repository checkout.
"""
