import XCTest

/// Store materials come from the Release app and its published production data.
/// No fixture, microphone capture, audio generation, or audition playback is used.
@MainActor
final class AppStoreScreenshotUITests: XCTestCase {
    func testCaptureProductionStoreScreenshots() throws {
        try captureProduction(language: .chinese)
    }

    func testCaptureEnglishProductionStoreScreenshots() throws {
        try captureProduction(language: .english)
    }

    private func captureProduction(language interfaceLanguage: CaptureLanguage) throws {
        #if DEBUG
        throw XCTSkip("Capture store screenshots with Tongxing / Release and production content.")
        #else
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", interfaceLanguage.appleLanguages,
                               "-AppleLocale", interfaceLanguage.appleLocale]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }

        let title = app.staticTexts["published-page-title"]
        XCTAssertTrue(title.waitForExistence(timeout: 45), "The real published sermon must load.")
        XCTAssertFalse(title.label.isEmpty)

        // Reset only visible interface/content choices through the actual controls.
        let interface = element("app-language-menu", in: app)
        try reveal(interface, in: app, towardTop: true)
        interface.tap()
        let selectedInterface = app.buttons[interfaceLanguage.menuTitle]
        XCTAssertTrue(selectedInterface.waitForExistence(timeout: 5))
        selectedInterface.tap()
        let language = app.buttons["choose-content-language"]
        try reveal(language, in: app, towardTop: true)
        language.tap()
        let chineseContent = app.buttons["content-language-zh-Hans"]
        XCTAssertTrue(chineseContent.waitForExistence(timeout: 15))
        chineseContent.tap()

        let currentMode = app.segmentedControls["listening-display"].buttons[interfaceLanguage.currentMode]
        try reveal(currentMode, in: app, towardTop: true)
        currentMode.tap()
        let subtitle = app.staticTexts["published-current-subtitle"]
        let english = app.staticTexts["published-current-english"]
        XCTAssertTrue(subtitle.waitForExistence(timeout: 45))
        XCTAssertTrue(english.waitForExistence(timeout: 15))
        XCTAssertFalse(subtitle.label.isEmpty)
        XCTAssertFalse(english.label.isEmpty)
        let searchWord = english.label.components(separatedBy: CharacterSet.letters.inverted)
            .first { $0.count >= 4 && $0.unicodeScalars.allSatisfy { $0.isASCII } }
        try reveal(subtitle, in: app, towardTop: false)
        capture("store-01-current-subtitle-\(interfaceLanguage.rawValue)", app: app)

        let fullMode = app.segmentedControls["listening-display"].buttons[interfaceLanguage.fullMode]
        try reveal(fullMode, in: app, towardTop: true)
        fullMode.tap()
        let reference = app.staticTexts.matching(NSPredicate(format:
            "identifier BEGINSWITH %@", "published-caption-english-")).firstMatch
        XCTAssertTrue(reference.waitForExistence(timeout: 15))
        try reveal(reference, in: app, towardTop: false)
        capture("store-02-full-transcript-english-\(interfaceLanguage.rawValue)", app: app)

        // The home lookup entry follows the current card; do not scroll through
        // hundreds of published transcript rows to reach the same control.
        try reveal(currentMode, in: app, towardTop: true)
        currentMode.tap()
        let locate = app.buttons["open-english-locate"]
        try reveal(locate, in: app, towardTop: false)
        locate.tap()
        let search = app.textFields["english-locate-search"]
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        if let searchWord {
            search.tap()
            search.typeText(searchWord + "\n")
            let result = app.staticTexts.matching(NSPredicate(format:
                "identifier BEGINSWITH %@", "locate-english-")).firstMatch
            XCTAssertTrue(result.waitForExistence(timeout: 10), "Search uses a word from the actual English subtitle.")
        }
        capture("store-03-english-lookup-\(interfaceLanguage.rawValue)", app: app)
        app.buttons["english-locate-close"].tap()
        XCTAssertTrue(fullMode.waitForExistence(timeout: 5))

        try reveal(language, in: app, towardTop: true)
        language.tap()
        XCTAssertTrue(app.buttons["content-language-zh-Hans"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["content-language-ko"].exists)
        XCTAssertTrue(app.buttons["content-language-es"].exists)
        capture("store-04-published-content-languages-\(interfaceLanguage.rawValue)", app: app)
        try closeSheet(interfaceLanguage.languageSheet, done: interfaceLanguage.done, in: app)

        let chooser = app.buttons["choose-sermon"]
        try reveal(chooser, in: app, towardTop: true)
        chooser.tap()
        let publishedSermon = app.buttons.matching(NSPredicate(format:
            "identifier BEGINSWITH %@", "published-page-")).firstMatch
        XCTAssertTrue(publishedSermon.waitForExistence(timeout: 15))
        capture("store-05-sermon-catalog-\(interfaceLanguage.rawValue)", app: app)
        try closeSheet(interfaceLanguage.sermonSheet, done: interfaceLanguage.done, in: app)

        app.buttons["more-options"].tap()
        let demos = element("voice-demo-disclosure", in: app)
        let demoVisible = revealIfPossible(demos, in: app, towardTop: false)
        var capturedDemo = false
        if demoVisible {
            demos.tap()
            let speaker = app.descendants(matching: .any).matching(NSPredicate(format:
                "identifier BEGINSWITH %@", "voice-demo-speaker-")).firstMatch
            if speaker.waitForExistence(timeout: 25), revealIfPossible(speaker, in: app, towardTop: false) {
                speaker.tap()
                let original = app.buttons.matching(NSPredicate(format:
                    "identifier BEGINSWITH %@", "voice-demo-original-")).firstMatch
                if original.waitForExistence(timeout: 10), revealIfPossible(original, in: app, towardTop: false) {
                    capture("store-06-production-voice-auditions-\(interfaceLanguage.rawValue)", app: app)
                    capturedDemo = true
                }
            }
        }
        if !capturedDemo {
            let privacy = element("privacy-support-link", in: app)
            try reveal(privacy, in: app, towardTop: true)
            privacy.tap()
            XCTAssertTrue(element("privacy-support-page", in: app).waitForExistence(timeout: 10))
            capture("store-06-privacy-and-support-\(interfaceLanguage.rawValue)", app: app)
            // Close from the owning About navigation root, independent of
            // whether SwiftUI inherits its Done toolbar onto the pushed page.
            let back = app.navigationBars[interfaceLanguage.privacySheet].buttons.element(boundBy: 0)
            XCTAssertTrue(back.waitForExistence(timeout: 5))
            back.tap()
            XCTAssertTrue(app.navigationBars[interfaceLanguage.aboutSheet].waitForExistence(timeout: 5))
        }
        try closeSheet(interfaceLanguage.aboutSheet, done: interfaceLanguage.done, in: app)
        XCTAssertTrue(app.buttons["more-options"].waitForExistence(timeout: 5))
        #endif
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func closeSheet(_ title: String, done doneTitle: String, in app: XCUIApplication) throws {
        let done = app.navigationBars[title].buttons[doneTitle]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        done.tap()
        let bar = app.navigationBars[title]
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: bar)
        guard XCTWaiter.wait(for: [closed], timeout: 5) == .completed else {
            throw CaptureFailure.sheetDidNotClose
        }
    }

    private func reveal(_ target: XCUIElement, in app: XCUIApplication, towardTop: Bool) throws {
        guard revealIfPossible(target, in: app, towardTop: towardTop) else {
            XCTFail("Cannot reveal real UI control: \(target.identifier)")
            throw CaptureFailure.unreachable
        }
    }

    private func revealIfPossible(_ target: XCUIElement, in app: XCUIApplication, towardTop: Bool) -> Bool {
        _ = target.waitForExistence(timeout: 8)
        for _ in 0..<10 {
            // XCTest can report controls underneath the floating dock as hittable.
            let play = app.buttons["playback-toggle"]
            let progress = element("playback-progress", in: app)
            let frame = target.frame
            let trailingRail = play.exists && play.frame.midX >= app.frame.maxX - 84
                && play.frame.width <= 52
            // Sheets cover the underlying playback dock, so it must not clip them.
            let inAbout = app.navigationBars["更多选项"].exists || app.navigationBars["More options"].exists
            let bottom = !inAbout && !trailingRail && progress.exists
                ? min(app.frame.maxY, progress.frame.minY - 24) : app.frame.maxY
            if target.exists && target.isHittable && frame.minY >= app.frame.minY
                && frame.maxY < bottom - 4 { return true }
            let reading = app.scrollViews["listening-scroll"]
            let surface: XCUIElement
            if inAbout {
                surface = app.collectionViews.firstMatch.exists ? app.collectionViews.firstMatch
                    : (app.tables.firstMatch.exists ? app.tables.firstMatch : app.scrollViews.firstMatch)
            } else {
                surface = reading.exists ? reading : app.scrollViews.firstMatch
            }
            guard surface.exists else { return false }
            let scrollFrame = surface.frame.intersection(app.frame)
            let safeBottom = min(scrollFrame.maxY, bottom - 8)
            guard safeBottom > scrollFrame.minY + 60 else { return false }
            let upper = CGPoint(x: scrollFrame.midX, y: scrollFrame.minY + (safeBottom - scrollFrame.minY) * 0.25)
            let lower = CGPoint(x: scrollFrame.midX, y: scrollFrame.minY + (safeBottom - scrollFrame.minY) * 0.75)
            let origin = app.coordinate(withNormalizedOffset: .zero)
            origin.withOffset(CGVector(dx: towardTop ? upper.x : lower.x, dy: towardTop ? upper.y : lower.y))
                .press(forDuration: 0.05, thenDragTo: origin.withOffset(
                    CGVector(dx: towardTop ? lower.x : upper.x, dy: towardTop ? lower.y : upper.y)))
        }
        return target.exists && target.isHittable
    }

    private func capture(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private enum CaptureFailure: Error { case unreachable, sheetDidNotClose }

    /// Labels are kept in sync with App/Resources/Localizable.xcstrings.
    /// Content remains Simplified Chinese in both interface-language captures.
    private enum CaptureLanguage: String {
        case chinese = "zh"
        case english = "en"

        var appleLanguages: String { self == .english ? "(en)" : "(zh-Hans)" }
        var appleLocale: String { self == .english ? "en_US" : "zh_CN" }
        var menuTitle: String { self == .english ? "English" : "简体中文" }
        var currentMode: String { self == .english ? "Listen" : "现场收听" }
        var fullMode: String { self == .english ? "Full transcript" : "字幕全文" }
        var languageSheet: String { self == .english ? "Choose sermon language" : "选择证道语言" }
        var sermonSheet: String { self == .english ? "Choose a sermon" : "选择证道" }
        var aboutSheet: String { self == .english ? "More options" : "更多选项" }
        var privacySheet: String { self == .english ? "Privacy & Support" : "隐私与支持" }
        var done: String { self == .english ? "Done" : "完成" }
    }
}
