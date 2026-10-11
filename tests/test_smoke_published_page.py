import unittest

from scripts import smoke_published_page as smoke

SHA = "e16380a609b2dc75059a12b7ad3cfedc304b73ac4aa49578e9264de6ba22d1b7"
CATALOG = {"schemaVersion": "sermon-multilingual-catalog-v4", "defaultPageId": "resi-20261011-54475d42",
           "pages": [{"id": "resi-20261011-54475d42", "date": "2026-10-11", "defaultTargetLocale": "zh-Hans",
                      "targets": {"zh-Hans": {"releasePackageUrl": "/releases-v4/resi-20261011-54475d42/zh-Hans.json"},
                                  "ko": {"releasePackageUrl": "/releases-v4/resi-20261011-54475d42/ko.json"}}}]}
RELEASE = {"pageId": "resi-20261011-54475d42", "targetLocale": "zh-Hans",
           "assets": [{"role": "content", "path": "/content/x/zh-Hans.json", "sha256": "a" * 64},
                      {"role": "audio", "path": "/media/x/zh-Hans.mp3", "sha256": SHA}]}
ENGAGEMENT = {"schemaVersion": 1, "enabled": True, "appVersion": "8e1b4c2d9f0a7b65"}
GOOD_DOM = ('<html><head><title>启示录：耶稣带来的安慰与盼望 · 耶稣警告 · 同行</title></head><body>'
            '<span id="edition-label">机器检查版</span><p id="current-text" class="current-text">弟兄姊妹，很高兴能和大家在一起。</p>'
            '<div id="full-reading-list"><div>弟兄姊妹</div><div>我是这里的牧师之一。</div></div></body></html>')
STALE_DOM = ('<html><head><title>同行</title></head><body><p id="current-text">配音就绪后，字幕会显示在这里。</p>'
             '<div id="full-reading-list"></div></body></html>')
CHROME_LOG = ('[61275:259:1011/222314.102938:INFO:CONSOLE(12)] "ready", source: https://x.web.app/app.mjs (12)\n'
              '[61275:259:1011/222315.000000:ERROR:CONSOLE(208)] "Uncaught TypeError: Cannot read properties of null '
              '(reading \'addEventListener\')", source: https://x.web.app/app.mjs (208)\n'
              '[61275:259:1011/222316.000000:WARNING:CONSOLE(5)] "deprecated", source: https://x.web.app/theme.js (5)\n')


class DomAndLogTests(unittest.TestCase):
    def test_dom_inspection_reads_title_caption_and_full_reading(self):
        dom = smoke.inspect_dom(GOOD_DOM)
        self.assertEqual(dom["title"], "启示录：耶稣带来的安慰与盼望 · 耶稣警告 · 同行")
        self.assertEqual(dom["captionText"], "弟兄姊妹，很高兴能和大家在一起。")
        self.assertGreater(dom["fullReadingChars"], 0)
        self.assertEqual(dom["editionLabel"], "机器检查版")

    def test_console_errors_keep_only_error_level_lines(self):
        errors = smoke.console_errors(CHROME_LOG)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["source"], "https://x.web.app/app.mjs")
        self.assertEqual(errors[0]["line"], 208)
        self.assertIn("Cannot read properties of null", errors[0]["message"])

    def test_evaluation_names_each_visible_failure(self):
        self.assertEqual(smoke.evaluate(smoke.inspect_dom(GOOD_DOM), [], 200), [])
        problems = smoke.evaluate(smoke.inspect_dom(STALE_DOM), smoke.console_errors(CHROME_LOG), 400)
        self.assertEqual(len(problems), 4)
        self.assertTrue(problems[0].startswith("title does not name the sermon"))
        self.assertIn("no subtitle", problems[1])
        self.assertIn("console error", problems[2])
        self.assertIn("HTTP 400", problems[3])

    def test_feedback_source_matches_the_reader_track_identity(self):
        source = smoke.feedback_source(CATALOG, RELEASE, ENGAGEMENT, "zh-Hans")
        self.assertEqual(source, {"schemaVersion": 1, "week": "2026-10-11",
                                  "trackId": "resi-20261011-54475d42-zh-Hans-" + SHA[:12],
                                  "audioSha256": SHA, "appVersion": ENGAGEMENT["appVersion"]})
        with self.assertRaisesRegex(ValueError, "bound audio hash"):
            smoke.feedback_source(CATALOG, {**RELEASE, "assets": [{"role": "audio", "path": "/m.mp3", "sha256": "xyz"}]},
                                  ENGAGEMENT, "zh-Hans")


class SmokeFlowTests(unittest.TestCase):
    def run_smoke(self, dom, log, status):
        documents = {"https://x.web.app/multilingual-v4.json": CATALOG, "https://x.web.app/engagement.json": ENGAGEMENT,
                     "https://x.web.app/releases-v4/resi-20261011-54475d42/zh-Hans.json": RELEASE,
                     "https://x.web.app/releases-v4/resi-20261011-54475d42/ko.json": {**RELEASE, "targetLocale": "ko"}}
        posted = []
        return smoke.smoke("https://x.web.app", "resi-20261011-54475d42", ("zh-Hans", "ko", "es"), browser="/fake/chrome",
                           loader=lambda browser, url, budget_ms, timeout: (dom, log),
                           fetch=lambda url, timeout: documents[url],
                           post=lambda origin, source, timeout: posted.append(source) or status), posted

    def test_passing_page_reports_every_locale_and_posts_one_session_each(self):
        report, posted = self.run_smoke(GOOD_DOM, "", 200)
        self.assertEqual(report["schemaVersion"], smoke.SCHEMA)
        self.assertEqual([row["status"] for row in report["locales"]], ["pass", "pass", "fail"])
        self.assertEqual(report["status"], "fail")  # es is not published for this page
        self.assertEqual(report["locales"][2]["problems"], ["locale is not published for this page"])
        self.assertEqual(len(posted), 2)
        self.assertEqual(report["locales"][0]["url"], "https://x.web.app/?week=resi-20261011-54475d42&contentLang=zh-Hans")

    def test_stale_shell_and_unsynced_feedback_fail_the_smoke(self):
        report, _ = self.run_smoke(STALE_DOM, CHROME_LOG, 400)
        row = report["locales"][0]
        self.assertEqual(row["status"], "fail")
        self.assertEqual(row["sessionStatus"], 400)
        self.assertEqual(len(row["consoleErrors"]), 1)
        self.assertEqual(len(row["problems"]), 4)

    def test_unknown_page_is_refused_before_any_browser_run(self):
        with self.assertRaisesRegex(ValueError, "not in the live v4 catalog"):
            smoke.smoke("https://x.web.app", "missing", ("zh-Hans",), browser="/fake/chrome",
                        loader=lambda *a, **k: self.fail("browser must not run"),
                        fetch=lambda url, timeout: CATALOG if url.endswith("v4.json") else ENGAGEMENT,
                        post=lambda *a: 200)


if __name__ == "__main__":
    unittest.main()
