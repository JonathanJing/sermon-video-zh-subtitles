"""Supervisor helpers: bounded decision proposals and their hash-only accounting,
D5 repair planning, the decision budget, the Gemini snapshot transport and the
bounded Agents API session client.

The supervisor itself and its agents drive the dual_pdf entries, so they live in
workflows/supervisor/ (orchestration/ may not import workflows/).
Callers bind the host first (tools/ops/run.py or scripts/tongxing_host.py).
"""
