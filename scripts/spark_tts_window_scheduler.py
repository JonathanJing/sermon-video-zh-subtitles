"""Parent-only ordered window dispatcher; workers never own output files."""
from __future__ import annotations

import copy


class ParallelBatchEngine:
    def __init__(self, pool, windows, *, seed, frozen_check):
        self.pool = pool
        self.windows = windows
        self.pending = list(windows)
        self.submitted = []
        self.seed = seed
        self.frozen_check = frozen_check
        self.pool.start()
        self._fill()

    def _fill(self):
        while self.pending and len(self.submitted) < self.pool.replicas:
            self.frozen_check()
            start = self.pending.pop(0)
            self.pool.submit(start, copy.deepcopy(self.windows[start]), seed=self.seed + start)
            self.submitted.append(start)

    def batch(self, requests, *, seed):
        if not self.submitted:
            raise ValueError("Replica dispatcher received an extra window")
        start = self.submitted[0]
        if requests != self.windows[start] or seed != self.seed + start:
            raise ValueError("Replica dispatcher window identity/order differs")
        self.frozen_check()
        values = self.pool.result(start)
        self.frozen_check()
        # Validate before admitting another window or any output to the parent.
        if not isinstance(values, list) or len(values) != len(requests):
            raise ValueError("TTS batch output cardinality differs")
        for value, request in zip(values, requests):
            if (not isinstance(value, dict) or value.get("identity") != request["identity"]
                    or "wave" not in value or type(value.get("sampleRate")) is not int
                    or value["sampleRate"] <= 0):
                raise ValueError("TTS batch output identity/order or sample rate differs")
        self.submitted.pop(0)
        self._fill()
        return values
