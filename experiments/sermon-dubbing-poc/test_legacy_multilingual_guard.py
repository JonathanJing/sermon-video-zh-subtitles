import sys
from pathlib import Path
import unittest
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_firebase import guard_multilingual_home


class Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class LegacyMultilingualGuardTest(unittest.TestCase):
    def test_existing_multilingual_catalog_blocks_legacy_deploy(self):
        with self.assertRaisesRegex(ValueError, "multilingual catalog"):
            guard_multilingual_home("ai-for-god-caption-dev", "ai-for-god-sermon-audio",
                                    opener=lambda *_args, **_kwargs: Response(200))

    def test_absent_catalog_allows_initial_legacy_deploy(self):
        def missing(request, timeout):
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        guard_multilingual_home("ai-for-god-caption-dev", "ai-for-god-sermon-audio",
                                opener=missing)

    def test_unexpected_state_fails_closed_and_explicit_rollback_is_possible(self):
        with self.assertRaisesRegex(ValueError, "HTTP 503"):
            guard_multilingual_home("ai-for-god-caption-dev", "ai-for-god-sermon-audio",
                                    opener=lambda *_args, **_kwargs: Response(503))
        guard_multilingual_home("ai-for-god-caption-dev", "ai-for-god-sermon-audio",
                                allow_rollback=True,
                                opener=lambda *_args, **_kwargs: self.fail("unexpected network"))


if __name__ == "__main__":
    unittest.main()
