import io
import json
from urllib.error import HTTPError
import unittest

import deploy_firebase


class Response(io.BytesIO):
    status = 200

    def geturl(self):
        return "https://ai-for-god-sermon-audio.web.app/multilingual-v2.json"


class ProductionOverwriteGuardTest(unittest.TestCase):
    def test_present_multilingual_catalog_blocks_legacy_path(self):
        response = Response(json.dumps({"schemaVersion":
            "sermon-multilingual-catalog-v2"}).encode())
        self.assertTrue(deploy_firebase.production_has_multilingual_catalog(
            "ai-for-god-sermon-audio", opener=lambda *_args, **_kwargs: response))

    def test_missing_catalog_allows_initial_legacy_site(self):
        def missing(request, **_kwargs):
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        self.assertFalse(deploy_firebase.production_has_multilingual_catalog(
            "ai-for-god-sermon-audio", opener=missing))

    def test_unexpected_response_fails_closed(self):
        with self.assertRaises(ValueError):
            deploy_firebase.production_has_multilingual_catalog(
                "ai-for-god-sermon-audio",
                opener=lambda *_args, **_kwargs: Response(b"<html>wrong route</html>"))


if __name__ == "__main__":
    unittest.main()
