import XCTest

@MainActor
final class WeeklyPosterPublishedUITests: XCTestCase {
    func testCapturePublishedPostersAcrossContentLanguages() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_LIVE_POSTER_SMOKE"] == "1", "Explicit live Dev media smoke only")
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_EXPECTED_CHANNEL"] == "beta", "Dev poster smoke is Beta-only")
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launch()
        XCTAssertTrue(app.buttons["choose-content-language"].waitForExistence(timeout: 45))
        // From 08:00 local on the service date the verified poster may already
        // be open by itself; capture that state instead of tapping a hidden card.
        if app.staticTexts["weekly-update-title"].waitForExistence(timeout: 15) {
            captureAndVerifyPoster(app, "weekly-poster-published-launch-auto-present")
            app.buttons["weekly-update-done"].tap()
        }
        capture(app, "weekly-poster-published-home")
        for locale in ["zh-Hans", "ko", "es"] {
            if locale != "zh-Hans" {
                let language = app.buttons["choose-content-language"]
                for _ in 0..<5 where !language.isHittable { app.swipeDown() }
                language.tap()
                let target = app.buttons["content-language-\(locale)"]
                XCTAssertTrue(target.waitForExistence(timeout: 10))
                target.tap()
            }
            let title = app.staticTexts["weekly-update-title"]
            if !title.exists {
                let open = app.buttons["weekly-update-open"]
                let reopen = app.buttons["weekly-update-reopen"]
                let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                    open.exists || reopen.exists || title.exists
                }, object: nil)
                XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 30), .completed)
                // The auto-presented sheet can still land during this wait.
                if !title.exists {
                    let button = open.exists ? open : reopen
                    for _ in 0..<5 where !button.isHittable { app.swipeDown() }
                    button.tap()
                }
            }
            captureAndVerifyPoster(app, "weekly-poster-published-\(locale)")
            app.buttons["weekly-update-done"].tap()
        }
    }

    private func captureAndVerifyPoster(_ app: XCUIApplication, _ name: String) {
        XCTAssertTrue(app.staticTexts["weekly-update-title"].waitForExistence(timeout: 10))
        let image = app.images["weekly-update-poster"]
        let verified = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "本周海报"), object: image)
        XCTAssertEqual(XCTWaiter.wait(for: [verified], timeout: 30), .completed)
        capture(app, name)
    }

    private func capture(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
