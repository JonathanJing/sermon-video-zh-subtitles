"""Host memory admission for local model stages: measured budgets, fail-closed measurement."""
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.compute import memory_admission as subject

GIB = 1024**3


class MemoryAdmissionTests(unittest.TestCase):
    def test_admits_when_reserve_plus_budget_fits(self):
        receipt = subject.admit(stage="asr_screen", reserve_gib=24, budget_gib=12, memory_reader=lambda: 52 * GIB)
        self.assertEqual((receipt["status"], receipt["requiredBytes"], receipt["memAvailableBytes"]),
                         ("admitted", 36 * GIB, 52 * GIB))
        self.assertEqual(receipt["schemaVersion"], subject.SCHEMA)

    def test_rejects_with_the_numbers_when_it_does_not_fit(self):
        with self.assertRaises(subject.MemoryAdmissionError) as caught:
            subject.admit(stage="asr_screen", reserve_gib=24, budget_gib=12, memory_reader=lambda: 35 * GIB)
        receipt = caught.exception.receipt
        self.assertEqual((receipt["status"], receipt["requiredBytes"]), ("rejected", 36 * GIB))

    def test_missing_or_invalid_measurement_is_rejected_not_assumed(self):
        def broken():
            raise OSError("no /proc/meminfo")
        for reader in (broken, lambda: None, lambda: -1):
            with self.subTest(reader=reader):
                with self.assertRaises(subject.MemoryAdmissionError) as caught:
                    subject.admit(stage="asr_screen", reserve_gib=24, budget_gib=12, memory_reader=reader)
                self.assertEqual(caught.exception.receipt["status"], "unmeasurable")
        self.assertIsNone(subject.sample(broken))
        self.assertEqual(subject.sample(lambda: 7), 7)

    def test_arguments_are_validated(self):
        for kwargs in (dict(reserve_gib=-1, budget_gib=1), dict(reserve_gib=1, budget_gib=float("inf")),
                       dict(reserve_gib=True, budget_gib=1)):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    subject.admit(stage="x", memory_reader=lambda: GIB, **kwargs)
        with self.assertRaises(ValueError):
            subject.admit(stage=" ", reserve_gib=1, budget_gib=1, memory_reader=lambda: GIB)

    def test_cuda_peaks_need_a_cuda_capable_torch(self):
        from types import SimpleNamespace
        self.assertIsNone(subject.cuda_peaks(SimpleNamespace(bfloat16="x")))
        cuda = SimpleNamespace(is_available=lambda: True, max_memory_allocated=lambda: 3,
                               max_memory_reserved=lambda: 5)
        self.assertEqual(subject.cuda_peaks(SimpleNamespace(cuda=cuda)),
                         {"maxAllocatedBytes": 3, "maxReservedBytes": 5})


if __name__ == "__main__":
    unittest.main()
