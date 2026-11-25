import XCTest

/// The listening-page picker separates published podcasts from sermons by the
/// catalog media type. Baseline mode captures the same fixture, device and
/// expansion state before the change so the pair stays comparable; the
/// assertions only run against the changed build.
@MainActor
final class ContentPickerUITests: XCTestCase {
    private let sermonID = "resi-20261004-69ba7a66"
    private let podcastID = "if-i-had-more-time-jesus-is-worthy"

    func testPickerSeparatesSermonsFromPodcasts() throws {
        let baseline = ProcessInfo.processInfo.environment["TONGXING_CAPTURE_CONTENT_TABS_BASELINE"] == "1"
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-source-categories",
                               "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }

        XCTAssertTrue(app.staticTexts["published-page-title"].waitForExistence(timeout: 15))
        let entry = app.buttons["choose-sermon"]
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        if baseline {
            XCTAssertTrue(entry.label.contains("选择证道周次"), "Baseline entry copy: \(entry.label)")
        } else {
            XCTAssertTrue(entry.label.contains("选择证道与播客"),
                          "Entry copy names both content kinds: \(entry.label)")
        }
        entry.tap()

        let done = app.buttons["完成"]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        expandPicker(app, done: done)

        let sermon = app.buttons["published-page-\(sermonID)"]
        let podcast = app.buttons["published-page-\(podcastID)"]

        if baseline {
            // Pre-change build: one mixed list with no content-kind control.
            XCTAssertTrue(app.navigationBars["选择证道"].waitForExistence(timeout: 5))
            XCTAssertTrue(sermon.waitForExistence(timeout: 10))
            XCTAssertTrue(podcast.exists)
            XCTAssertFalse(app.segmentedControls["picker-content-tabs"].exists)
            capture("picker-content-tabs-before", app: app)
            return
        }

        XCTAssertTrue(app.navigationBars["证道与播客"].waitForExistence(timeout: 5))
        let tabs = app.segmentedControls["picker-content-tabs"]
        XCTAssertTrue(tabs.waitForExistence(timeout: 10), "The picker separates the two content kinds.")
        // The page on screen is a sermon, so the sheet must open on that tab.
        XCTAssertTrue(tabs.buttons["周日证道"].isSelected, "The sermon page must open the sermon tab")
        XCTAssertTrue(sermon.waitForExistence(timeout: 10))
        XCTAssertFalse(podcast.exists, "A podcast must not sit in the sermon list.")
        capture("picker-content-tabs-sermons", app: app)

        tabs.buttons["播客"].tap()
        XCTAssertTrue(podcast.waitForExistence(timeout: 10))
        XCTAssertFalse(sermon.exists, "A sermon must not sit in the podcast list.")
        capture("picker-content-tabs-podcasts", app: app)

        tabs.buttons["周日证道"].tap()
        XCTAssertTrue(sermon.waitForExistence(timeout: 10))

        // Reopening after closing from another tab still follows the content, not
        // the tab the user left behind (reported 2026-11-16).
        app.buttons["完成"].tap()
        XCTAssertTrue(app.navigationBars["证道与播客"].waitForNonExistence(timeout: 5))
        app.buttons["choose-sermon"].tap()
        let reopened = app.segmentedControls["picker-content-tabs"]
        XCTAssertTrue(reopened.waitForExistence(timeout: 10))
        XCTAssertTrue(reopened.buttons["周日证道"].isSelected, "Reopen must return to the sermon tab")
        capture("picker-content-tabs-reopened", app: app)

        // Choosing the podcast switches the page; the next open follows it.
        // A tap that lands while the sheet is still settling can be dropped;
        // confirm the segment switched before looking for the podcast row.
        let podcastTab = reopened.buttons["播客"]
        podcastTab.tap()
        let podRow = app.buttons["published-page-\(podcastID)"]
        if !podRow.waitForExistence(timeout: 5) && !podcastTab.isSelected { podcastTab.tap() }
        XCTAssertTrue(podRow.waitForExistence(timeout: 10))
        podRow.tap()
        XCTAssertTrue(app.staticTexts["published-page-title"].waitForExistence(timeout: 15))
        app.buttons["choose-sermon"].tap()
        let podcastDefault = app.segmentedControls["picker-content-tabs"]
        XCTAssertTrue(podcastDefault.waitForExistence(timeout: 10))
        XCTAssertTrue(podcastDefault.buttons["播客"].isSelected, "A podcast page must open the podcast tab")
        capture("picker-content-tabs-podcast-default", app: app)
        podcastDefault.buttons["周日证道"].tap()
        let sermonAgain = app.buttons["published-page-\(sermonID)"]
        XCTAssertTrue(sermonAgain.waitForExistence(timeout: 10))
        sermonAgain.tap()
        XCTAssertTrue(app.staticTexts["published-page-title"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.navigationBars["证道与播客"].exists)
    }

    /// The system segmented control keeps 13 pt labels at every Dynamic Type
    /// size, so large type swaps in two labeled buttons instead.
    func testPickerLargeTypeUsesLabeledButtons() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-source-categories",
                               "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN",
                               "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }

        XCTAssertTrue(app.staticTexts["published-page-title"].waitForExistence(timeout: 15))
        app.buttons["choose-sermon"].tap()
        let sermons = app.buttons["周日证道"]
        XCTAssertTrue(sermons.waitForExistence(timeout: 10), "Large type keeps the kind switcher.")
        XCTAssertFalse(app.segmentedControls["picker-content-tabs"].exists)
        let podcasts = app.buttons["播客"]
        XCTAssertTrue(podcasts.exists)
        XCTAssertTrue(app.buttons["published-page-\(sermonID)"].waitForExistence(timeout: 10))
        podcasts.tap()
        XCTAssertTrue(app.buttons["published-page-\(podcastID)"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["published-page-\(sermonID)"].exists)
        capture("picker-content-tabs-large-type", app: app)
    }

    /// Same gesture the existing picker tests use: drag the sheet to its large
    /// detent so every section is on screen for the capture.
    private func expandPicker(_ app: XCUIApplication, done: XCUIElement) {
        let origin = app.coordinate(withNormalizedOffset: .zero)
        let grabber = origin.withOffset(CGVector(dx: app.frame.width / 2,
                                                 dy: done.frame.minY - app.frame.minY - 12))
        grabber.press(forDuration: 0.1, thenDragTo: origin.withOffset(
            CGVector(dx: app.frame.width / 2, dy: 70)))
    }

    private func capture(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
