"""Whole-stage host memory admission before a local model loads on Spark unified memory.

A stage names the reserve the host must keep and its own measured peak budget; admission
requires MemAvailable >= reserve + budget before any model process or CUDA context exists,
so a stage that cannot fit never loads a model and never trips the running reserve guard.
The receipt records the numbers whether admitted or rejected. Budgets are measured values
owned by the stage that declares them; this module never guesses one, and a host without a
MemAvailable measurement is rejected rather than assumed to have room.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Callable

SCHEMA = "sermon-host-memory-admission-v1"
GIB = 1024**3


class MemoryAdmissionError(RuntimeError):
    def __init__(self, receipt: dict):
        self.receipt = receipt
        super().__init__(f"{receipt['stage']}: MemAvailable is below the stage's memory admission budget")


def linux_mem_available() -> int:
    """Host MemAvailable bytes; fails closed when the measurement is absent."""
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise MemoryAdmissionError({"stage": "host", "status": "unmeasurable"})


def _gib(value, name: str) -> int:
    if (type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value)
            or not 0 <= value <= 1024):
        raise ValueError(f"{name} must be a finite GiB value in 0..1024")
    return int(value * GIB)


def admit(*, stage: str, reserve_gib: float, budget_gib: float,
          memory_reader: Callable[[], int] = linux_mem_available) -> dict:
    """Return the admission receipt; raise MemoryAdmissionError when the host cannot fit the stage."""
    if type(stage) is not str or not stage.strip():
        raise ValueError("stage must be a non-empty name")
    reserve, budget = _gib(reserve_gib, "reserve_gib"), _gib(budget_gib, "budget_gib")
    try:
        available = memory_reader()
    except Exception as exc:
        raise MemoryAdmissionError({"schemaVersion": SCHEMA, "stage": stage, "status": "unmeasurable",
                                    "reason": type(exc).__name__}) from exc
    if type(available) is not int or available < 0:
        raise MemoryAdmissionError({"schemaVersion": SCHEMA, "stage": stage, "status": "unmeasurable",
                                    "reason": "invalid_measurement"})
    receipt = {"schemaVersion": SCHEMA, "stage": stage, "memAvailableBytes": available,
               "reserveBytes": reserve, "budgetBytes": budget, "requiredBytes": reserve + budget,
               "measuredAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    if available < reserve + budget:
        raise MemoryAdmissionError(receipt | {"status": "rejected"})
    return receipt | {"status": "admitted"}


def sample(memory_reader: Callable[[], int] = linux_mem_available) -> int | None:
    """A later MemAvailable reading for the receipt's calibration fields; None when unavailable."""
    try:
        value = memory_reader()
    except Exception:
        return None
    return value if type(value) is int else None


def cuda_peaks(torch_module) -> dict | None:
    """This process's CUDA allocator peaks, for calibrating the stage budget; None without CUDA."""
    cuda = getattr(torch_module, "cuda", None)
    try:
        if cuda is None or not cuda.is_available():
            return None
        return {"maxAllocatedBytes": int(cuda.max_memory_allocated()),
                "maxReservedBytes": int(cuda.max_memory_reserved())}
    except Exception:
        return None
