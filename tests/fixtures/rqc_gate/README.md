# D4 synthetic developer fixtures

`test_sermon_review_gate.py` derives an internally consistent, synthetic snapshot
from the read-only D1 fixtures and rebinds all actual bytes/canonical hashes.
Source, generation, plugin and human inputs are fake JSON; BoundaryChecks are
mocked integration-adapter results. They are never production approval evidence.
The tests do not call a model, invoke a plugin, launch a stage, or establish D6
Stage 0 or real-media acceptance. No D1 shared fixture is modified.
