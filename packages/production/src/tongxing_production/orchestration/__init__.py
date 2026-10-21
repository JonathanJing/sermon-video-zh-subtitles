"""Durable jobs, leases, scheduling and recovery.

Owns what runs next and how an outcome is recorded; never modifies approved
text or treats an unknown outcome as a failure to retry. Engines and compute
are adapters injected by the host.
"""
