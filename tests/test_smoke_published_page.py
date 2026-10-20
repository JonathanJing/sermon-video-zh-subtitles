import copy
import unittest

from tools.ops import smoke_published_page as smoke

ORIGIN = "https://x.web.app"
PAGE = "resi-20261011-54475d42"
CATALOG = {"schemaVersion": "sermon-multilingual-catalog-v4", "defaultPageId": PAGE,
           "pages": [{"id": PAGE, "date": "2026-10-11", "defaultTargetLocale": "zh-Hans",
                      "targets": {"zh-Hans": {"releasePackageUrl": f"/releases-v4/{PAGE}/zh-Hans.json"},
                                  "ko": {"releasePackageUrl": f"/releases-v4/{PAGE}/ko.json"}}}]}


def release(locale):
    return {"pageId": PAGE, "targetLocale": locale,
            "assets": [{"role": "content", "path": f"/content/{PAGE}/{locale}.json", "sha256": "a" * 64},
                       {"role": "captions", "path": f"/captions/{PAGE}/{locale}.json", "sha256": "b" * 64},
                       {"role": "audio", "path": f"/media/{PAGE}/{locale}.mp3", "sha256": "c" * 64}]}


CONTENT = {"zh-Hans": {"title": "耶稣警告", "cues": [{"text": "弟兄姊妹，很高兴能和大家在一起。"}, {"text": "我是这里的牧师之一。"}]},
           "ko": {"title": "예수님은 경고하십니다", "cues": [{"text": "교회 공동체 여러분, 함께하게 되어 기쁩니다."}]}}
CAPTIONS = {"zh-Hans": {"cues": [{"text": "弟兄姊妹，很高兴能和大家在一起。"}]}, "ko": {"cues": [{"text": "교회 공동체 여러분."}]}}
DOCUMENTS = {ORIGIN + "/multilingual-v4.json": CATALOG}
for loc in ("zh-Hans", "ko"):
    DOCUMENTS[ORIGIN + f"/releases-v4/{PAGE}/{loc}.json"] = release(loc)
    DOCUMENTS[ORIGIN + f"/content/{PAGE}/{loc}.json"] = CONTENT[loc]
    DOCUMENTS[ORIGIN + f"/captions/{PAGE}/{loc}.json"] = CAPTIONS[loc]


SRC = {loc: smoke.track_source(CATALOG["pages"][0], loc, "c" * 64) for loc in ("zh-Hans", "ko")}
ANCHOR = SRC["zh-Hans"]  # the default page in its default locale


def sessions(*sources, status=200):
    return [{"method": "POST", "status": status, "source": source} for source in sources]


def observation(locale="zh-Hans", **changes):
    first = CONTENT[locale]["cues"][0]["text"]
    value = {"status": "ok", "elapsedMs": 5000, "consoleErrors": [], "sessionRequests": sessions(SRC[locale], ANCHOR),
             "dom": {"title": f"{CONTENT[locale]['title']} · 同行 · 证道中文听译", "week": PAGE, "contentLang": locale,
                     "contentLanguage": locale, "audioSrc": f"/media/{PAGE}/{locale}.mp3", "captionText": first,
                     "fullReading": "完整文稿 00:05 " + first}}
    dom_changes = changes.pop("dom", {})
    value.update(changes)
    value["dom"].update(dom_changes)
    return value


def expected(locale="zh-Hans"):
    return smoke.expected_identity(ORIGIN, CATALOG["pages"][0], locale, release(locale), lambda url, timeout: DOCUMENTS[url], 5)


REQUIRED = {f"/media/{PAGE}/zh-Hans.mp3", "/app.mjs", "/index.html"}


class EvaluateTests(unittest.TestCase):
    def check(self, observed, locale="zh-Hans", **kwargs):
        return smoke.evaluate(expected(locale), observed, required_paths=REQUIRED, anchor=ANCHOR, **kwargs)

    def test_correct_page_passes(self):
        self.assertEqual(self.check(observation()), ([], []))
        self.assertEqual(self.check(observation("ko"), "ko"), ([], []))

    def test_a_shell_that_falls_back_to_another_sermon_or_language_fails(self):
        # Review finding: the page rendered something, just not the requested release.
        cases = {
            "another week": dict(dom={"week": "resi-20261004-69ba7a66"}),
            "chinese instead of korean": dict(dom={"contentLang": "zh-Hans"}),
            "selector on chinese": dict(dom={"contentLanguage": "zh-Hans"}),
            "another audio": dict(dom={"audioSrc": f"/media/{PAGE}/zh-Hans.mp3"}),
            "another title": dict(dom={"title": "耶稣警告 · 同行 · 证道中文听译"}),
            "another caption": dict(dom={"captionText": "弟兄姊妹，很高兴能和大家在一起。"}),
            "another full text": dict(dom={"fullReading": "弟兄姊妹，很高兴能和大家在一起。"}),
        }
        for name, change in cases.items():
            with self.subTest(name):
                problems, _ = self.check(observation("ko", **copy.deepcopy(change)), "ko")
                self.assertEqual(len(problems), 1, problems)

    def test_console_errors_exceptions_and_required_loads_fail_but_optional_loads_warn(self):
        errors = [{"kind": "console.error", "message": "boom", "source": "https://x.web.app/app.mjs", "line": 3},
                  {"kind": "exception", "message": "TypeError: null", "source": "https://x.web.app/app.mjs", "line": 208},
                  {"kind": "log.network", "message": "404", "source": f"https://x.web.app/media/{PAGE}/zh-Hans.mp3"},
                  {"kind": "log.network", "message": "404", "source": "https://x.web.app/alignment/other-page.json"}]
        problems, warnings = self.check(observation(consoleErrors=errors))
        self.assertEqual(len(problems), 3)
        self.assertEqual(warnings, ["optional resource failed: /alignment/other-page.json: 404"])

    def test_the_pages_own_session_requests_are_required_and_must_succeed(self):
        failed = sessions(SRC["zh-Hans"]) + sessions(ANCHOR, status=400)
        self.assertIn("/api/session answered 200, 400", self.check(observation(sessionRequests=failed))[0])
        self.assertIn("the page made no /api/session request", self.check(observation(sessionRequests=[]))[0])
        limited = observation(sessionRequests=sessions(SRC["zh-Hans"], status=429) + sessions(ANCHOR),
                              consoleErrors=[{"kind": "log.network", "message": "429", "source": "https://x.web.app/api/session"}])
        problems, warnings = self.check(limited)
        self.assertEqual(problems, ["/api/session rate-limited (429): too many sessions from this address; rerun one smoke at a time"])
        self.assertEqual(warnings, [])
        self.assertEqual(self.check(observation(sessionRequests=[]), check_session=False), ([], []))

    def test_session_requests_must_name_this_releases_track(self):
        # Review finding: a stale identity (the previous locale's track) still answers 200.
        stale = observation("ko", sessionRequests=sessions(SRC["zh-Hans"], ANCHOR))
        problems, _ = self.check(stale, "ko")
        self.assertEqual(problems, ["no /api/session request names this release's track"])
        other = dict(SRC["ko"], trackId="resi-20261004-69ba7a66-ko-804c81b719c0", week="2026-10-04")
        problems, _ = self.check(observation("ko", sessionRequests=sessions(SRC["ko"], other)), "ko")
        self.assertEqual(problems, ["/api/session names another track: 2026-10-04 resi-20261004-69ba7a66-ko-804c81b719c0"])
        unseen = observation(sessionRequests=[{"method": "POST", "status": 200, "source": None}] + sessions(SRC["zh-Hans"]))
        self.assertEqual(self.check(unseen)[0], ["an /api/session request body was not observed"])
        # The usage anchor is allowed beside this release's track, and on the default page they coincide.
        self.assertEqual(self.check(observation("ko", sessionRequests=sessions(SRC["ko"], ANCHOR, ANCHOR)), "ko"), ([], []))
        self.assertEqual(self.check(observation(sessionRequests=sessions(SRC["zh-Hans"]))), ([], []))

    def test_a_browser_that_misses_the_deadline_fails(self):
        problems, _ = self.check({"status": "timeout", "reason": "no result within 60000 ms"})
        self.assertEqual(problems, ["browser did not finish: timeout (no result within 60000 ms)"])
        self.assertTrue(self.check({"status": "error", "reason": "observer exit 1"})[0])


class SmokeFlowTests(unittest.TestCase):
    def run_smoke(self, loader):
        return smoke.smoke(ORIGIN, PAGE, ("zh-Hans", "ko", "es"), browser="/fake/chrome", loader=loader,
                           fetch=lambda url, timeout: DOCUMENTS[url], shell=lambda: {"/app.mjs"})

    def test_each_locale_is_loaded_once_and_judged_against_its_release(self):
        calls = []
        def loader(browser, url, settle_ms, deadline_ms):
            calls.append(url)
            return observation("ko" if url.endswith("contentLang=ko") else "zh-Hans")
        report = self.run_smoke(loader)
        self.assertEqual(report["schemaVersion"], smoke.SCHEMA)
        self.assertEqual([row["status"] for row in report["locales"]], ["pass", "pass", "fail"])
        self.assertEqual(report["locales"][2]["problems"], ["locale is not published for this page"])
        # Each judged locale names the release the live catalog served, so a later run can bind the pass to it.
        self.assertEqual(report["locales"][1]["releasePackageUrl"], f"/releases-v4/{PAGE}/ko.json")
        self.assertIn("releasePackageJsonSha256", report["locales"][1])
        self.assertEqual(calls, [f"{ORIGIN}/?week={PAGE}&contentLang=zh-Hans", f"{ORIGIN}/?week={PAGE}&contentLang=ko"])

    def test_a_stale_shell_showing_chinese_for_korean_fails_korean_only(self):
        report = self.run_smoke(lambda browser, url, settle_ms, deadline_ms: observation("zh-Hans"))
        self.assertEqual(report["locales"][0]["status"], "pass")
        self.assertEqual(report["locales"][1]["status"], "fail")
        self.assertGreaterEqual(len(report["locales"][1]["problems"]), 4)

    def test_unknown_page_is_refused_before_any_browser_run(self):
        with self.assertRaisesRegex(ValueError, "not in the live v4 catalog"):
            smoke.smoke(ORIGIN, "missing", ("zh-Hans",), browser="/fake/chrome",
                        loader=lambda *a, **k: self.fail("browser must not run"),
                        fetch=lambda url, timeout: DOCUMENTS[url], shell=set)

    def test_observer_output_that_is_not_json_is_an_error(self):
        from unittest.mock import patch
        import subprocess
        with patch.object(smoke.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "crash")):
            self.assertEqual(smoke.load_in_browser("/b", "https://x", settle_ms=1, deadline_ms=1000)["status"], "error")
        with patch.object(smoke.subprocess, "run", side_effect=subprocess.TimeoutExpired("node", 1)):
            self.assertEqual(smoke.load_in_browser("/b", "https://x", settle_ms=1, deadline_ms=1000)["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
