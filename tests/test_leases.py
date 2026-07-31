import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend import leases


class LeaseTest(unittest.TestCase):
    def test_local_lease_is_exclusive_and_releasable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            location = str(Path(tempdir) / "timeline.json")
            first = leases.acquire_lease(location, owner="first")
            second = leases.acquire_lease(location, owner="second")
            self.assertIsNotNone(first)
            self.assertIsNone(second)

            leases.release_lease(first)
            third = leases.acquire_lease(location, owner="third")

        self.assertIsNotNone(third)

    def test_expired_local_lease_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as tempdir:
            location = str(Path(tempdir) / "generation.json")
            old_now = datetime.now(timezone.utc) - timedelta(hours=2)
            old = leases.acquire_lease(
                location,
                owner="expired-owner",
                ttl_seconds=60,
                now=old_now,
            )
            replacement = leases.acquire_lease(location, owner="replacement")

        self.assertIsNotNone(old)
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.owner, "replacement")


if __name__ == "__main__":
    unittest.main()
