"""The unified production run: manifest admission, adapter registry,
host-local resource reservations and the CAS state pump.

Import ``backend`` first and ``configure`` a host; the other modules read
their collaborators from it at call time, never at import time.
"""
