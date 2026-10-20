"""Supervisor helpers: bounded decision proposals and their hash-only accounting,
D5 repair planning, and the bounded Agents API session client.

The supervisor itself (scripts/sermon_production_supervisor.py) and its agents stay
in scripts/ until backend.leases has a host port (scripts migration plan section 9).
Callers bind the host first (tools/ops/run.py or scripts/tongxing_host.py).
"""
