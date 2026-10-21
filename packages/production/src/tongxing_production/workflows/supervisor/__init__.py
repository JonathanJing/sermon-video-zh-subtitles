"""The post-live reading-PDF production supervisor, its agents and the legacy page-release composition.

Moved from scripts/ in the D-5 closure window. It lives under workflows/ because it drives the
dual_pdf entries (orchestration/ may not import workflows/); backend helpers (Cloud, logs,
stage leases) arrive through the dual_pdf host ports. backend/app.py still imports it through
scripts/sermon_production_supervisor.py until the next Cloud Run deploy (decision D-2).
"""
