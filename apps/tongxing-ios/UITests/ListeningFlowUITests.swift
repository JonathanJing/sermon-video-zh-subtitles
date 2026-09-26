import XCTest

/// Real application UI and AVPlayer, with generated silence and an injected
/// URLSession transport. The offline relaunch simulates transport failure;
/// these tests do not establish real-network, audible, lock-screen, or venue QA.
@MainActor
final class ListeningFlowUITests: XCTestCase {
    func testDuoOuterPlayerKeepsReadingAreaWhenMoreOpens() throws {
        let app = launchFixture()
        try XCTSkipUnless(abs(app.frame.width - 466) < 2 && abs(app.frame.height - 678) < 2,
                          "This geometry check targets the iPhone Duo outer portrait display")

        let more = app.buttons["playback-more"]
        XCTAssertTrue(more.waitForExistence(timeout: 5))
        let safeTrailingEdge = app.frame.maxX - 84
        for identifier in ["nudge-backward", "playback-toggle", "nudge-forward", "playback-more"] {
            let button = app.buttons[identifier]
            XCTAssertTrue(button.isHittable, "\(identifier) must remain usable")
            XCTAssertLessThanOrEqual(button.frame.maxX, safeTrailingEdge + 1,
                                     "\(identifier) must avoid the reserved right edge")
        }
        XCTAssertFalse(app.buttons["align-live-audio"].exists)
        let playerFrame = app.buttons["playback-toggle"].frame
        more.tap()
        XCTAssertTrue(app.buttons["align-live-audio"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["precision-controls"].exists)
        XCTAssertEqual(app.buttons["playback-toggle"].frame, playerFrame,
                       "更多不能撑高或移动常驻播放栏")
        screenshot("duo-outer-more-popover", app: app)
        app.buttons["playback-more-close"].tap()
        XCTAssertTrue(more.waitForExistence(timeout: 5))
        screenshot("duo-outer-player", app: app)
    }

    func testDuoInnerLandscapeUsesTrailingPlayerRail() throws {
        let app = launchFixture()
        try XCTSkipUnless(abs(app.frame.width - 951) < 2 && abs(app.frame.height - 669) < 2,
                          "This geometry check targets the iPhone Duo inner landscape display")
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(play.frame.minX, app.frame.midX)
        XCTAssertLessThanOrEqual(play.frame.maxX, app.frame.maxX - 84 + 1)
        XCTAssertTrue(app.buttons["playback-more"].isHittable)
        screenshot("duo-inner-trailing-player", app: app)
    }

    func testPrivacySupportIsAvailableOfflineFromMoreOptions() throws {
        let app = launchFixture(offline: true)
        app.buttons["more-options"].tap()
        let link = element("privacy-support-link", in: app)
        XCTAssertTrue(link.waitForExistence(timeout: 5))
        link.tap()
        XCTAssertTrue(element("privacy-support-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(element("privacy-contact-email", in: app).exists)
    }

    func testMoreExpandsVoiceDemosWithOriginalEnglishBeforeSamples() throws {
        let app = launchFixture()
        app.buttons["more-options"].tap()
        let demos = element("voice-demo-disclosure", in: app)
        try reveal(demos, in: app, direction: .up)
        demos.tap()
        let speaker = element("voice-demo-speaker-speaker_0", in: app)
        try waitFor(speaker, "exists == true")
        try reveal(speaker, in: app, direction: .up)
        speaker.tap()
        let original = element("voice-demo-original-speaker_0", in: app)
        let chinese = element("voice-demo-sample-speaker_0-zh-Hans", in: app)
        try waitFor(original, "exists == true")
        XCTAssertTrue(chinese.exists)
        XCTAssertTrue(original.label.contains("讲员原始英文片段"))
        XCTAssertTrue(chinese.label.contains("中文"))
        screenshot("voice-demo-more-original-and-samples", app: app)
    }

    func testTargetLanguageSheetShowsOnlyPublishedCapabilities() throws {
        let app = launchFixture()
        let chooser = app.buttons["choose-content-language"]
        XCTAssertTrue(chooser.isHittable)
        XCTAssertTrue(chooser.value as? String == "简体中文，Text only" || chooser.value as? String == "简体中文，仅文字")
        chooser.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        let korean = app.buttons["content-language-ko"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 5))
        XCTAssertTrue(korean.exists)
        XCTAssertEqual(chinese.value as? String, "已选择")
        XCTAssertTrue(korean.label.contains("한국어"))
        XCTAssertTrue(korean.label.contains("仅文字"))
        screenshot("target-language-sheet-published-capabilities", app: app)
    }

    func testPublishedLanguagePageOpensWebViewAndNativePlayerRemains() throws {
        let app = launchFixture()
        app.buttons["choose-content-language"].tap()
        app.buttons["content-language-ko"].tap()
        XCTAssertTrue(app.webViews["verified-content-page"].waitForExistence(timeout: 10))
        // StorageTests verifies the exact HTML bytes and hash. WebKit sometimes
        // presents a blank content process on CI; that visual check needs its
        // own device acceptance rather than making this routing test intermittent.
        app.buttons["完成"].tap()
        XCTAssertTrue(app.buttons["playback-toggle"].waitForExistence(timeout: 5))
        expandCompactDockIfNeeded(in: app)
        XCTAssertTrue(app.buttons["align-live-audio"].exists)
        XCTAssertEqual(app.staticTexts["sermon-title"].label, "界面测试证道")
    }

    func testIndependentPublishedPageKeepsLocalesSeparateFromLegacyWeek() throws {
        let app = launchFixture()
        app.buttons["choose-sermon"].tap()
        let independent = app.buttons["published-page-ui-test-clip"]
        XCTAssertTrue(independent.waitForExistence(timeout: 5))
        independent.tap()
        XCTAssertEqual(app.staticTexts["published-page-title"].label, "ui-test-clip")
        XCTAssertFalse(app.buttons["playback-toggle"].exists)

        app.buttons["choose-content-language"].tap()
        XCTAssertTrue(app.buttons["content-language-es"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["content-language-ko"].exists)
        app.buttons["content-language-es"].tap()
        XCTAssertTrue(app.webViews["verified-content-page"].waitForExistence(timeout: 10))
        app.buttons["完成"].tap()

        let prepare = app.buttons["prepare-published-audio"]
        XCTAssertTrue(prepare.waitForExistence(timeout: 5))
        prepare.tap()
        XCTAssertTrue(app.staticTexts["published-audio-locale"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["published-audio-locale"].label.contains("Español"))
        let play = app.buttons["playback-toggle"]
        try waitFor(play, "exists == true AND enabled == true AND hittable == true")
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:00，')")

        app.buttons["choose-sermon"].tap()
        app.buttons["legacy-week-ui-test-week"].tap()
        XCTAssertEqual(app.staticTexts["sermon-title"].label, "界面测试证道")
        XCTAssertTrue(app.buttons["playback-toggle"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["published-audio-locale"].exists)
        app.buttons["choose-content-language"].tap()
        XCTAssertTrue(app.buttons["content-language-ko"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["content-language-es"].exists)
    }

    func testLiveDevSecondClipShowsThreeLanguagesAndPlaysReviewedAudio() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_LIVE_DEV_SMOKE"] == "1",
                          "Run explicitly against Firebase Dev")
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        defer { app.terminate() }
        XCTAssertTrue(app.buttons["choose-sermon"].waitForExistence(timeout: 20))
        app.buttons["choose-sermon"].tap()
        let clip = app.buttons["published-page-2026-09-20-laodicea-clip"]
        for _ in 0..<8 where !clip.exists {
            app.scrollViews.element(boundBy: app.scrollViews.count - 1).swipeUp()
        }
        XCTAssertTrue(clip.waitForExistence(timeout: 5))
        clip.tap()
        let title = app.staticTexts["published-page-title"]
        if !title.waitForExistence(timeout: 3), clip.exists { clip.tap() }
        XCTAssertTrue(title.waitForExistence(timeout: 10))
        XCTAssertEqual(title.label, "2026-09-20-laodicea-clip")

        app.buttons["choose-content-language"].tap()
        for locale in ["zh-Hans", "ko", "es"] {
            XCTAssertTrue(app.buttons["content-language-\(locale)"].waitForExistence(timeout: 10))
        }
        app.buttons["完成"].tap()
        let titles = [
            "zh-Hans": "老底嘉：不冷不热的警告（片段）",
            "es": "Laodicea: la advertencia contra la tibieza (fragmento)",
            "ko": "라오디게아: 미지근함에 대한 경고 (발췌)",
        ]
        for locale in ["zh-Hans", "es", "ko"] {
            app.buttons["choose-content-language"].tap()
            app.buttons["content-language-\(locale)"].tap()
            let web = app.webViews["verified-content-page"]
            XCTAssertTrue(web.waitForExistence(timeout: 20))
            XCTAssertTrue(web.staticTexts[titles[locale]!].waitForExistence(timeout: 10))
            screenshot("live-dev-second-clip-\(locale)-content", app: app)
            app.buttons["完成"].tap()
        }
        let prepare = app.buttons["prepare-published-audio"]
        XCTAssertTrue(prepare.waitForExistence(timeout: 10))
        prepare.tap()
        XCTAssertTrue(app.staticTexts["published-audio-locale"].waitForExistence(timeout: 30))
        XCTAssertTrue(app.staticTexts["published-audio-locale"].label.contains("한국어"))
        let play = app.buttons["playback-toggle"]
        try waitFor(play, "exists == true AND enabled == true AND hittable == true")
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:00，')")
        screenshot("live-dev-second-clip-korean-playing", app: app)
    }

    func testUnavailableAlignmentExplainsReason() throws {
        let app = launchFixture()
        expandCompactDockIfNeeded(in: app)
        let alignment = app.buttons["align-live-audio"]
        try waitFor(alignment, "exists == true AND enabled == true AND hittable == true")
        alignment.tap()
        let explanation = app.alerts["现场自动对齐暂不可用"]
        XCTAssertTrue(explanation.waitForExistence(timeout: 5))
        XCTAssertTrue(explanation.staticTexts["本篇尚未提供现场对齐资料，请刷新目录或手动定位。"].exists)
        screenshot("unavailable-alignment-explanation", app: app)
        explanation.buttons["关闭"].tap()
        XCTAssertFalse(explanation.exists)
    }

    func testMorePrecisionOpensSheetAfterPopoverCloses() throws {
        let app = launchFixture()
        try downloadSelection(in: app)
        expandCompactDockIfNeeded(in: app)
        let precision = app.buttons["precision-controls"]
        try waitFor(precision, "exists == true AND enabled == true AND hittable == true")
        precision.tap()
        XCTAssertTrue(app.navigationBars["定位 / 精调"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["playback-more-close"].exists)
    }

    func testPlaybackDockSwipeCollapsesWithoutPausingAndExpands() throws {
        let app = launchFixture()
        try downloadSelection(in: app)
        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:00，')")
        collapseDock(in: app)
        try waitFor(element("playback-progress", in: app), "exists == false")
        XCTAssertFalse(app.buttons["nudge-forward"].exists)
        XCTAssertFalse(app.buttons["align-live-audio"].exists)
        XCTAssertEqual(app.buttons.matching(identifier: "playback-toggle").count, 1)
        XCTAssertEqual(play.label, "暂停播放", "收起操作不能暂停音频")
        XCTAssertTrue(play.isHittable)
        play.tap()
        try waitFor(play, "label == '开始播放'")
        screenshot("collapsed-player-paused", app: app)
        expandDock(in: app)
        try waitFor(element("playback-progress", in: app), "exists == true")
        try assertAlignmentAvailableInMore(in: app)
        XCTAssertEqual(play.label, "开始播放", "展开操作不能改变暂停状态")
        screenshot("expanded-player-restored", app: app)
    }

    func testAccessibilityTextDockCanCollapseAndExpand() throws {
        let app = launchFixture(largeText: true)
        collapseDock(in: app)
        try waitFor(element("playback-progress", in: app), "exists == false")
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.isHittable)
        XCTAssertGreaterThanOrEqual(play.frame.width, 44)
        XCTAssertGreaterThanOrEqual(play.frame.height, 44)
        XCTAssertTrue(app.frame.contains(play.frame))
        expandDock(in: app)
        try waitFor(element("playback-progress", in: app), "exists == true")
        try assertAlignmentAvailableInMore(in: app)
    }

    private func collapseDock(in app: XCUIApplication) {
        let progress = element("playback-progress", in: app)
        let start = progress.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: 70)))
    }

    private func expandDock(in app: XCUIApplication) {
        let start = app.buttons["playback-toggle"].coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: -100)))
    }

    func testLiveAlignmentRemainsAvailableOnFirstScreenAndTranscript() throws {
        let app = launchFixture()
        try assertAlignmentAvailableInMore(in: app)
        app.segmentedControls["listening-display"].buttons["字幕全文"].tap()
        try assertAlignmentAvailableInMore(in: app)
        screenshot("alignment-in-more-transcript", app: app)
    }

    func testLandscapeKeepsLiveAlignmentAvailableInMore() throws {
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launchFixture()
        let play = app.buttons["playback-toggle"]
        XCTAssertGreaterThan(play.frame.minX, app.frame.midX,
                             "宽而矮的阅读区应把播放栏移到右侧")
        try assertAlignmentAvailableInMore(in: app)
        screenshot("landscape-alignment-in-more", app: app)
    }

    func testOpeningTranscriptWhilePlayingLocatesCurrentCueOnlyOnce() throws {
        let app = launchFixture(largeText: true)
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        try seekToSecondSubtitle(in: app)
        let modes = app.segmentedControls["listening-display"]
        let currentMode = modes.buttons["现场收听"]
        try reveal(currentMode, in: app, direction: .down)
        currentMode.tap()
        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        modes.buttons["字幕全文"].tap()

        // Do not use reveal here: it would conceal a missing automatic scroll.
        let timestamp = app.buttons["subtitle-cue-1"]
        let located = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            let top = app.navigationBars.firstMatch.frame.maxY
            let bottom = self.element("playback-progress", in: app).frame.minY - 36
            return timestamp.exists && timestamp.isHittable
                && timestamp.frame.minY >= top && timestamp.frame.maxY <= bottom
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [located], timeout: 5), .completed)
        screenshot("playing-transcript-auto-located-current-cue", app: app)

        try reveal(currentMode, in: app, direction: .down)
        let movedAway = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            currentMode.frame.minY < app.navigationBars.firstMatch.frame.maxY
        }, object: nil)
        movedAway.isInverted = true
        XCTAssertEqual(XCTWaiter.wait(for: [movedAway], timeout: 2), .completed,
                       "播放推进不能抢走手动滚动位置")
        play.tap()
        try waitFor(play, "label == '开始播放'")
        currentMode.tap()
        modes.buttons["字幕全文"].tap()
        XCTAssertGreaterThanOrEqual(currentMode.frame.minY, app.navigationBars.firstMatch.frame.maxY,
                                    "暂停时打开全文应保留阅读入口位置")
        XCTAssertEqual(play.label, "开始播放")
        screenshot("paused-transcript-preserves-reading-position", app: app)
    }

    func testEnglishInterfaceAndOriginalTranscriptPreserveSelectedPosition() throws {
        let app = launchFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        try seekToSecondSubtitle(in: app)
        let english = element("transcript-english-1", in: app)
        let comparison = element("transcript-english-toggle-1", in: app)
        try reveal(comparison, in: app, direction: .up)
        XCTAssertFalse(english.exists)
        comparison.tap()
        try reveal(english, in: app, direction: .up)
        XCTAssertTrue(english.label.contains("Second synthetic source sentence"))
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        comparison.tap()
        XCTAssertFalse(english.exists)
        comparison.tap()
        app.buttons["more-options"].tap()
        let language = element("interface-language", in: app)
        try reveal(language, in: app, direction: .up)
        language.tap()
        app.buttons["English"].tap()
        app.buttons["Done"].tap()
        try waitFor(app.buttons["playback-toggle"], "label == 'Play'")
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        XCTAssertEqual(element("sermon-title", in: app).label, "界面测试证道")
        XCTAssertTrue(english.label.contains("Second synthetic source sentence"))
        screenshot("english-interface-source-bilingual-transcript", app: app)
    }

    func testTopInterfaceLanguagesKeepChinesePlaybackAndAlignment() throws {
        let app = launchFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        try seekToSecondSubtitle(in: app)
        let menu = element("app-language-menu", in: app)
        XCTAssertTrue(menu.exists)
        for _ in 0..<4 where !menu.isHittable {
            app.scrollViews["listening-scroll"].swipeDown()
        }
        XCTAssertTrue(menu.isHittable)
        for (option, code, playLabel) in [
            ("한국어", "KO", "재생 시작"),
            ("Español", "ES", "Reproducir"),
            ("Tiếng Việt", "VI", "Bắt đầu phát")
        ] {
            menu.tap()
            app.buttons[option].tap()
            XCTAssertEqual(menu.value as? String, code)
            try waitFor(app.buttons["playback-toggle"], "label == '\(playLabel)'")
            try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
            XCTAssertEqual(element("sermon-title", in: app).label, "界面测试证道")
            expandCompactDockIfNeeded(in: app)
            XCTAssertTrue(app.buttons["align-live-audio"].exists)
            app.buttons["playback-more-close"].tap()
        }
    }

    func testTopInterfaceLanguageCanChangeBeforeCatalogLoads() {
        let app = launchFixture(offline: true)
        let menu = element("app-language-menu", in: app)
        XCTAssertTrue(menu.waitForExistence(timeout: 5))
        menu.tap()
        app.buttons["한국어"].tap()
        XCTAssertTrue(app.staticTexts["설교를 불러올 수 없습니다"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["새로고침"].exists)
    }

    func testSelectTrackDownloadPlayPauseAndSeekToSubtitle() throws {
        let app = launchFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)

        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        try waitFor(element("playback-progress", in: app), "value CONTAINS '正在收听'")
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:00，')")
        play.tap()
        try waitFor(play, "label == '开始播放'")
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已暂停'")

        try seekToSecondSubtitle(in: app)
        expandCompactDockIfNeeded(in: app)
        let current = app.buttons["current-cue"]
        XCTAssertTrue(current.isHittable)
        current.tap()
        let currentMode = app.segmentedControls["listening-display"].buttons["现场收听"]
        try reveal(currentMode, in: app, direction: .down)
        currentMode.tap()
        try waitFor(element("current-subtitle", in: app), "value == '乙音轨：第二句，用于验证时间定位。'")
        XCTAssertEqual(play.label, "开始播放", "字幕定位必须保留暂停状态")
        screenshot("selected-track-paused-at-second-subtitle", app: app)
    }

    func testDownloadedTrackAndBookmarkSurviveOfflineRelaunch() throws {
        let app = launchFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        try seekToSecondSubtitle(in: app)
        screenshot("downloaded-track-bookmark-before-relaunch", app: app)

        app.terminate()
        app.launchArguments.append("--ui-testing-offline")
        app.launch()
        try waitFor(element("sermon-title", in: app), "label == '界面测试证道'")
        try waitFor(element("catalog-notice", in: app), "label CONTAINS '上次保存的证道目录'")

        // The product starts on the catalog default track. Re-select the actual
        // downloaded second track through its ordinary menu after relaunch.
        try selectSecondTrack(in: app)
        let restoredDownload = element("download-status", in: app)
        try waitFor(restoredDownload, "label CONTAINS '正在使用已下载音频'")
        let saved = element("resume-position", in: app)
        try waitFor(saved, "label CONTAINS '00:12'")
        let restore = app.buttons["restore-position"]
        try reveal(restore, in: app, direction: .down)
        try waitFor(restore, "enabled == true")
        restore.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12，'")
        try waitFor(element("current-subtitle", in: app), "value == '乙音轨：第二句，用于验证时间定位。'")
        XCTAssertFalse(saved.exists, "恢复后应关闭旧的位置卡片")
        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(element("playback-progress", in: app), "value CONTAINS '正在收听'")
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:12，')")
        play.tap()
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已暂停'")
        screenshot("offline-catalog-downloaded-audio-and-restored-position", app: app)
    }

    func testAccessibilityTextKeepsDownloadAndPlaybackControlsReachable() throws {
        let app = launchFixture(largeText: true)
        try downloadSelection(in: app)
        let play = app.buttons["playback-toggle"]
        try assertAlignmentAvailableInMore(in: app)
        let forward = app.buttons["nudge-forward"]
        let backward = app.buttons["nudge-backward"]
        for control in [play, forward, backward] {
            XCTAssertTrue(control.isHittable, "大字模式的主要播放控件必须可点击：\(control.identifier)")
            XCTAssertGreaterThanOrEqual(control.frame.minX, app.frame.minX)
            XCTAssertLessThanOrEqual(control.frame.maxX, app.frame.maxX)
            XCTAssertLessThanOrEqual(control.frame.maxY, app.frame.maxY)
        }
        forward.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:01，'")
        backward.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:00，'")
        play.tap()
        try waitFor(element("playback-progress", in: app), "value CONTAINS '正在收听'")
        play.tap()
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已暂停'")
        screenshot("accessibility3-download-and-playback-controls", app: app)
    }

    private func assertAlignmentAvailableInMore(in app: XCUIApplication,
                                              file: StaticString = #filePath, line: UInt = #line) throws {
        expandCompactDockIfNeeded(in: app)
        let align = app.buttons["align-live-audio"]
        try waitFor(align, "exists == true AND hittable == true")
        XCTAssertEqual(app.buttons.matching(identifier: "align-live-audio").count, 1,
                       "首页只能出现一个现场对齐入口", file: file, line: line)
        XCTAssertTrue(app.frame.contains(align.frame),
                      "无需滚动就应完整显示现场对齐按钮", file: file, line: line)
        app.buttons["playback-more-close"].tap()
    }

    private func expandCompactDockIfNeeded(in app: XCUIApplication) {
        let more = app.buttons["playback-more"]
        if more.exists && !app.buttons["playback-more-close"].exists { more.tap() }
    }

    private func launchFixture(largeText: Bool = false, offline: Bool = false) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing"] + (largeText ? ["--ui-testing-large-text"] : [])
            + (offline ? ["--ui-testing-offline"] : [])
        app.launchArguments += ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        addTeardownBlock { [weak self] in
            guard let self else { return }
            await MainActor.run {
                self.screenshot("final-ui-state", app: app)
                let hierarchy = XCTAttachment(string: app.debugDescription)
                hierarchy.name = "final-accessibility-hierarchy"
                hierarchy.lifetime = .keepAlways
                self.add(hierarchy)
                app.terminate()
            }
        }
        app.launch()
        if offline {
            XCTAssertTrue(app.staticTexts["暂时无法读取证道"].waitForExistence(timeout: 15))
        } else {
            XCTAssertTrue(element("sermon-title", in: app).waitForExistence(timeout: 15))
            XCTAssertEqual(element("sermon-title", in: app).label, "界面测试证道")
        }
        return app
    }

    private func selectSecondTrack(in app: XCUIApplication) throws {
        app.buttons["more-options"].tap()
        let track = app.buttons["track-option-fixture-second"]
        try waitFor(track, "exists == true AND hittable == true")
        track.tap()
        try waitFor(element("current-subtitle", in: app), "value == '乙音轨：第一句，用于验证选轨。'")
    }

    private func downloadSelection(in app: XCUIApplication) throws {
        let download = app.buttons["download-audio"]
        try reveal(download, in: app, direction: .up)
        download.tap()
        try waitFor(element("download-status", in: app), "label CONTAINS '正在使用已下载音频'")
        try waitFor(app.buttons["playback-toggle"], "enabled == true AND hittable == true")
    }

    private func seekToSecondSubtitle(in app: XCUIApplication) throws {
        let transcriptMode = app.segmentedControls["listening-display"].buttons["字幕全文"]
        try reveal(transcriptMode, in: app, direction: .down)
        transcriptMode.tap()
        let timestamp = app.buttons["subtitle-cue-1"]
        try reveal(timestamp, in: app, direction: .up)
        XCTAssertTrue(timestamp.isEnabled)
        timestamp.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12，'")
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已定位 00:12'")
    }

    private enum ScrollDirection { case up, down }

    private func reveal(_ target: XCUIElement, in app: XCUIApplication, direction: ScrollDirection) throws {
        let scroll = app.scrollViews["listening-scroll"]
        for _ in 0..<10 {
            // safeAreaBar leaves the ScrollView's accessibility frame extending
            // beneath the floating dock. Clip to actual visible reading bounds;
            // a whole-ScrollView percentage can land on the large-text play button.
            let visibleFrame = scroll.frame.intersection(app.frame)
            let top = max(visibleFrame.minY, app.navigationBars.firstMatch.frame.maxY) + 16
            let bottom = min(visibleFrame.maxY, element("playback-progress", in: app).frame.minY - 36)
            guard bottom - top >= 80 else {
                screenshot("insufficient-reading-region", app: app)
                XCTFail("实际界面没有足够的阅读区域供滚动")
                throw FlowFailure.unreachable
            }
            let readingFrame = CGRect(x: visibleFrame.minX, y: top,
                                      width: visibleFrame.width, height: bottom - top)
            let targetFrame = target.exists ? target.frame : nil
            // XCTest can report hittable for controls hidden behind Liquid Glass.
            // Every control used by these flows fits in this viewport, so require
            // the whole control to enter the reading region before its normal tap.
            if let targetFrame, !targetFrame.isEmpty, readingFrame.contains(targetFrame), target.isHittable {
                return
            }
            let upwards = targetFrame.map { $0.midY > readingFrame.midY } ?? (direction == .up)
            let requestedDistance = targetFrame.map { abs($0.midY - readingFrame.midY) } ?? readingFrame.height
            let distance = min(readingFrame.height * 0.72, max(40, requestedDistance))
            let startY = upwards ? bottom - readingFrame.height * 0.12 : top + readingFrame.height * 0.12
            let origin = app.coordinate(withNormalizedOffset: .zero)
            let x = visibleFrame.midX - app.frame.minX
            let start = origin.withOffset(CGVector(dx: x, dy: startY - app.frame.minY))
            let end = origin.withOffset(CGVector(dx: x, dy: startY + (upwards ? -distance : distance) - app.frame.minY))
            // Holding briefly at the destination avoids a fling past the target;
            // the next iteration still re-evaluates direction from its new frame.
            start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.15)
        }
        screenshot("unreachable-\(target.identifier)", app: app)
        XCTFail("实际界面无法滚动到可点击控件：\(target.identifier)")
        throw FlowFailure.unreachable
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func waitFor(_ element: XCUIElement, _ predicate: String,
                         timeout: TimeInterval = 15, file: StaticString = #filePath, line: UInt = #line) throws {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: predicate), object: element)
        guard XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed else {
            XCTFail("界面条件未满足：\(element.identifier), \(predicate)", file: file, line: line)
            throw FlowFailure.timeout
        }
    }

    private func screenshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private enum FlowFailure: Error { case unreachable, timeout }
}
