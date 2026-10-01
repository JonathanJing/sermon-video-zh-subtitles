import XCTest

/// Real application UI and AVPlayer, with generated silence and an injected
/// URLSession transport. The offline relaunch simulates transport failure;
/// Fixture tests do not establish real-network, audible, lock-screen, or venue QA.
/// The explicit live Dev Demo smoke below uses real Hosting assets when opted in.
@MainActor
final class ListeningFlowUITests: XCTestCase {
    func testPlaybackStatusAndMoreLabelAreVisibleAtRegularTextSize() {
        let app = launchFixture()
        let status = app.staticTexts["playback-status-detail"]
        XCTAssertTrue(status.waitForExistence(timeout: 5))
        XCTAssertTrue(status.isHittable)
        XCTAssertFalse(status.label.isEmpty)
        let more = app.buttons["playback-more"]
        XCTAssertEqual(more.label, "定位")
        let play = app.buttons["playback-toggle"]
        let moreFrame = more.frame
        let besideTrailingRail = abs(play.frame.midX - more.frame.midX) < 16
            && more.frame.minY > play.frame.maxY
        more.tap()
        assertPlaybackMorePopoverNearButton(in: app, buttonFrame: moreFrame,
                                          besideTrailingRail: besideTrailingRail)
        XCTAssertTrue(app.alerts["playback-more-panel"].exists)
        screenshot("playback-more-near-button", app: app)
        app.buttons["playback-more-close"].tap()
    }

    func testDuoOuterPlayerKeepsReadingAreaWhenMoreOpens() throws {
        let app = launchFixture()
        try XCTSkipUnless(abs(app.frame.width - 466) < 2 && abs(app.frame.height - 678) < 2,
                          "This geometry check targets the iPhone Duo outer portrait display; observed \(app.frame)")

        let more = app.buttons["playback-more"]
        XCTAssertTrue(more.waitForExistence(timeout: 5))
        XCTAssertEqual(more.label, "定位")
        XCTAssertTrue(app.staticTexts["playback-status-detail"].isHittable,
                      "播放状态应在正常字号下可见")
        let sideRegionStart = app.frame.maxX - 84
        for identifier in ["nudge-backward", "playback-toggle", "nudge-forward", "playback-more"] {
            let button = app.buttons[identifier]
            XCTAssertTrue(button.isHittable, "\(identifier) must remain usable")
            XCTAssertGreaterThanOrEqual(button.frame.midX, sideRegionStart,
                                        "\(identifier) should share the system side region")
        }
        assertNavigationActionsAbovePlayer(in: app)
        XCTAssertLessThanOrEqual(app.buttons["playback-toggle"].frame.width, 45,
                                 "系统侧边栏的播放按钮应收进栏宽")
        app.buttons["choose-sermon"].tap()
        XCTAssertTrue(app.buttons["legacy-week-ui-test-week"].waitForExistence(timeout: 5))
        app.buttons["完成"].tap()
        app.buttons["more-options"].tap()
        XCTAssertTrue(element("privacy-support-link", in: app).waitForExistence(timeout: 5))
        app.buttons["完成"].tap()
        XCTAssertFalse(app.buttons["align-live-audio"].exists)
        let playerFrame = app.buttons["playback-toggle"].frame
        let moreFrame = more.frame
        more.tap()
        XCTAssertTrue(app.buttons["align-live-audio"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["precision-controls"].exists)
        assertPlaybackMorePopoverNearButton(in: app, buttonFrame: moreFrame, besideTrailingRail: true)
        XCTAssertTrue(app.alerts["playback-more-panel"].exists,
                      "更多浮窗应呈现模态辅助功能特征")
        screenshot("duo-outer-more-popover", app: app)
        app.buttons["playback-more-close"].tap()
        XCTAssertTrue(more.waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons["playback-toggle"].frame, playerFrame,
                       "更多不能撑高或移动常驻播放栏")
        screenshot("duo-outer-player", app: app)
    }

    func testDuoInnerLandscapeUsesTrailingPlayerRail() throws {
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launchFixture()
        try XCTSkipUnless(abs(app.frame.width - 951) < 2 && abs(app.frame.height - 669) < 2,
                          "This geometry check targets the iPhone Duo inner landscape display; observed \(app.frame)")
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(play.frame.minX, app.frame.midX)
        XCTAssertGreaterThanOrEqual(play.frame.midX, app.frame.maxX - 84,
                                    "播放栏应进入状态栏下方的系统侧边区域")
        assertNavigationActionsAbovePlayer(in: app)
        let more = app.buttons["playback-more"]
        XCTAssertTrue(more.isHittable)
        let moreFrame = more.frame
        more.tap()
        assertPlaybackMorePopoverNearButton(in: app, buttonFrame: moreFrame, besideTrailingRail: true)
        screenshot("duo-inner-more-popover", app: app)
        app.buttons["playback-more-close"].tap()
        screenshot("duo-inner-trailing-player", app: app)
    }

    func testAnonymousStatisticsDefaultOffAndOptInOut() throws {
        let app = launchFixture()
        app.buttons["more-options"].tap()
        let link = element("privacy-support-link", in: app)
        XCTAssertTrue(link.waitForExistence(timeout: 5))
        link.tap()
        let toggle = app.switches["anonymous-statistics-toggle"]
        try reveal(toggle, in: app, direction: .up)
        XCTAssertEqual(toggle.value as? String, "0")
        toggle.switches.firstMatch.tap()
        XCTAssertEqual(toggle.value as? String, "1")
        screenshot("anonymous-statistics-enabled", app: app)
        toggle.switches.firstMatch.tap()
        XCTAssertEqual(toggle.value as? String, "0")
        screenshot("anonymous-statistics-disabled", app: app)
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
        try revealDemo(demos, in: app, direction: .up)
        demos.tap()
        let speaker = element("voice-demo-speaker-speaker_0", in: app)
        try revealDemo(speaker, in: app, direction: .up)
        speaker.tap()
        let original = element("voice-demo-original-speaker_0", in: app)
        let chinese = element("voice-demo-sample-speaker_0-zh-Hans", in: app)
        try waitFor(original, "exists == true")
        XCTAssertTrue(chinese.exists)
        XCTAssertTrue(original.label.contains("讲员原始英文片段"))
        XCTAssertTrue(chinese.label.contains("中文"))
        screenshot("voice-demo-more-original-and-samples", app: app)
    }

    func testVoiceDemoPausesResumesAndLanguageChangeStopsAudio() throws {
        let app = launchFixture(voiceClips: true)
        app.buttons["more-options"].tap()
        let demos = app.buttons["voice-demo-disclosure"]
        try revealDemo(demos, in: app, direction: .up); demos.tap()
        let speaker = app.buttons["voice-demo-speaker-speaker_0"]
        try revealDemo(speaker, in: app, direction: .up); speaker.tap()
        let original = app.buttons["voice-demo-original-speaker_0"]
        try revealDemo(original, in: app, direction: .up); original.tap()
        try waitFor(original, "label BEGINSWITH '暂停'")
        screenshot("voice-demo-playing", app: app)
        original.tap()
        try waitFor(original, "label BEGINSWITH '播放'")
        XCTAssertEqual(original.value as? String, "已暂停")
        original.tap()
        try waitFor(original, "label BEGINSWITH '暂停'")
        let chinese = app.buttons["voice-demo-sample-speaker_0-zh-Hans"]
        try revealDemo(chinese, in: app, direction: .up); chinese.tap()
        try waitFor(chinese, "label BEGINSWITH '暂停'")
        let korean = app.buttons["voice-demo-locale-speaker_0-ko"]
        try revealDemo(korean, in: app, direction: .up); korean.tap()
        let sample = app.buttons["voice-demo-sample-speaker_0-ko"]
        try waitFor(sample, "label BEGINSWITH '播放'")
        XCTAssertFalse(app.buttons["voice-demo-sample-speaker_0-zh-Hans"].exists)
        try waitFor(original, "label BEGINSWITH '播放'")
        let transcript = app.buttons["voice-demo-transcript-speaker_0"]
        try revealDemo(transcript, in: app, direction: .up); transcript.tap()
        XCTAssertTrue(app.staticTexts["Synthetic ko sample."].waitForExistence(timeout: 5))
        screenshot("voice-demo-korean-transcript", app: app)
        sample.tap()
        try waitFor(sample, "label BEGINSWITH '暂停'")
        try revealDemo(speaker, in: app, direction: .down); speaker.tap()
        speaker.tap()
        try waitFor(sample, "label BEGINSWITH '播放'")
        screenshot("voice-demo-collapsed-paused", app: app)
    }

    func testVoiceDemoVideoUsesVerifiedClipAndReturnsPaused() throws {
        let app = launchFixture(voiceClips: true)
        app.buttons["more-options"].tap()
        let demos = app.buttons["voice-demo-disclosure"]
        try revealDemo(demos, in: app, direction: .up); demos.tap()
        let speaker = app.buttons["voice-demo-speaker-speaker_0"]
        try revealDemo(speaker, in: app, direction: .up); speaker.tap()
        let original = app.buttons["voice-demo-original-speaker_0"]
        try revealDemo(original, in: app, direction: .up); original.tap()
        try waitFor(original, "label BEGINSWITH '暂停'")
        let video = app.buttons["voice-demo-video-speaker_0"]
        try revealDemo(video, in: app, direction: .up); video.tap()
        XCTAssertTrue(element("voice-demo-video-player", in: app).waitForExistence(timeout: 10))
        screenshot("voice-demo-verified-video", app: app)
        app.navigationBars["同片段视频"].buttons["完成"].tap()
        try waitFor(original, "label BEGINSWITH '播放'")
        XCTAssertEqual(original.value as? String, "已暂停")
    }

    /// Run explicitly with a Debug/Beta configuration whose existing origin is Firebase Dev.
    /// This checks real original-audio progress and in-app verified-video presentation/return.
    /// Native AVKit play/pause controls are not asserted: their accessibility varies by OS.
    func testLiveDevVoiceDemoOriginalProgressAndInAppVideoReturnsPaused() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_LIVE_DEMO"] == "1",
                          "Opt in with TONGXING_LIVE_DEMO=1 to check real Firebase Dev demo assets.")
        continueAfterFailure = false
        let app = XCUIApplication()
        // No --ui-testing argument or injected transport: use the app's configured content origin.
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer {
            screenshot("live-dev-demo-final-ui-state", app: app)
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "live-dev-demo-final-accessibility-hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            app.terminate()
        }

        let more = app.buttons["more-options"]
        XCTAssertTrue(more.waitForExistence(timeout: 30))
        more.tap()
        let demos = app.buttons["voice-demo-disclosure"]
        try revealDemo(demos, in: app, direction: .up)
        demos.tap()
        // The frozen real catalog uses eric_geiger, never the synthetic speaker_0 fixture.
        let speaker = app.buttons["voice-demo-speaker-eric_geiger"]
        XCTAssertTrue(speaker.waitForExistence(timeout: 60))
        XCTAssertTrue(speaker.label.contains("Eric Geiger"))
        try revealDemo(speaker, in: app, direction: .up)
        speaker.tap()
        let original = app.buttons["voice-demo-original-eric_geiger"]
        try revealDemo(original, in: app, direction: .up)
        original.tap()
        try waitFor(original, "label BEGINSWITH '暂停'", timeout: 60)
        let clock = original.staticTexts.matching(NSPredicate(format: "label CONTAINS '/'")).firstMatch
        try waitFor(clock, "exists == true", timeout: 15)
        try waitFor(clock, "exists == true AND NOT (label BEGINSWITH '00:00/')", timeout: 15)
        screenshot("live-dev-demo-eric-original-time-advanced", app: app)
        original.tap()
        try waitFor(original, "label BEGINSWITH '播放'")
        XCTAssertEqual(original.value as? String, "已暂停")

        let video = app.buttons["voice-demo-video-eric_geiger"]
        try revealDemo(video, in: app, direction: .up)
        video.tap()
        XCTAssertTrue(element("voice-demo-video-player", in: app).waitForExistence(timeout: 60),
                      "Verified real clip must open inside the app rather than in a browser.")
        let done = app.buttons["voice-demo-video-done"]
        XCTAssertTrue(done.waitForExistence(timeout: 10))
        screenshot("live-dev-demo-eric-video-in-app", app: app)
        done.tap()
        XCTAssertTrue(app.navigationBars["更多选项"].waitForExistence(timeout: 10))
        try revealDemo(original, in: app, direction: .down)
        try waitFor(original, "label BEGINSWITH '播放'")
        XCTAssertEqual(original.value as? String, "已暂停",
                       "Closing the video must not resume the English audition.")
        screenshot("live-dev-demo-eric-video-returned-original-paused", app: app)
    }

    func testVoiceDemoLargeTextLanguageChoiceRemainsUsable() throws {
        let app = launchFixture(largeText: true, voiceClips: true)
        app.buttons["more-options"].tap()
        let demos = app.buttons["voice-demo-disclosure"]
        try revealDemo(demos, in: app, direction: .up); demos.tap()
        let speaker = app.buttons["voice-demo-speaker-speaker_0"]
        try revealDemo(speaker, in: app, direction: .up); speaker.tap()
        let spanish = app.buttons["voice-demo-locale-speaker_0-es"]
        try revealDemo(spanish, in: app, direction: .up); spanish.tap()
        let audio = app.buttons["voice-demo-sample-speaker_0-es"]
        try revealDemo(audio, in: app, direction: .up)
        XCTAssertTrue(audio.isEnabled)
        XCTAssertTrue(audio.label.contains("Español"))
        XCTAssertGreaterThan(audio.frame.height, 80, "Sheet must inherit the accessibility text size")
        audio.tap()
        try waitFor(audio, "label BEGINSWITH '暂停'")
        audio.tap()
        try waitFor(audio, "label BEGINSWITH '播放'")
        screenshot("voice-demo-accessibility-spanish-paused", app: app)
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
        XCTAssertTrue(app.staticTexts["published-audio-locale"].waitForExistence(timeout: 10))

        app.buttons["choose-content-language"].tap()
        XCTAssertTrue(app.buttons["content-language-es"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["content-language-ko"].exists)
        app.buttons["content-language-es"].tap()
        XCTAssertTrue(app.webViews["verified-content-page"].waitForExistence(timeout: 10))
        app.buttons["完成"].tap()

        XCTAssertFalse(app.buttons["prepare-published-audio"].exists)
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

    func testSermonHeadingAndPickerUseTitleSeriesDateSpeakerWithoutSeeking() throws {
        try verifySermonHeading(largeText: false)
    }

    func testSermonHeadingLargeTextKeepsLongSeriesAndPickerReachable() throws {
        try verifySermonHeading(largeText: true)
    }

    private func verifySermonHeading(largeText: Bool) throws {
        let app = launchFixture(largeText: largeText, dualScript: true)
        let series = app.staticTexts["published-page-series"]
        XCTAssertTrue(series.waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["published-page-title"].label, "测试完整视频证道")
        XCTAssertEqual(series.label, "启示录：耶稣带来的安慰与盼望")
        XCTAssertEqual(app.staticTexts["published-page-details"].label, "2026-09-27 · Eric Geiger")
        XCTAssertLessThan(app.staticTexts["published-page-title"].frame.minY, series.frame.minY)
        XCTAssertLessThan(series.frame.minY, app.staticTexts["published-page-details"].frame.minY)
        screenshot(largeText ? "sermon-heading-large" : "sermon-heading", app: app)
        let play = app.buttons["playback-toggle"]
        try waitFor(play, "exists == true AND enabled == true AND hittable == true")
        play.tap()
        try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:00，')")
        play.tap()
        try waitFor(play, "label == '开始播放'")
        let position = element("playback-progress", in: app).value as? String
        app.buttons["choose-sermon"].tap()
        let row = app.buttons["published-page-ui-test-full-video"]
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        XCTAssertTrue(row.label.contains("测试完整视频证道"))
        XCTAssertTrue(row.label.contains("启示录：耶稣带来的安慰与盼望"))
        XCTAssertTrue(row.label.contains("2026-09-27 · Eric Geiger"))
        XCTAssertFalse(row.label.contains("한국어"))
        XCTAssertTrue(row.isHittable)
        if largeText {
            XCTAssertGreaterThan(row.frame.height, 160, "Picker rows must inherit the accessibility text size")
        }
        screenshot(largeText ? "sermon-picker-large" : "sermon-picker", app: app)
        app.buttons["完成"].tap()
        XCTAssertEqual(element("playback-progress", in: app).value as? String, position)
    }

    func testDualScriptCatalogOpensCurrentPageBeforeLegacyAndPreparesAudio() throws {
        let app = launchFixture(dualScript: true)
        XCTAssertEqual(app.staticTexts["published-page-title"].label, "测试完整视频证道")
        XCTAssertTrue(element("watch-full-video", in: app).exists)
        app.buttons["watch-full-video"].tap()
        XCTAssertTrue(app.staticTexts["native-full-video"].waitForExistence(timeout: 5))
        app.buttons["完成"].tap()
        XCTAssertTrue(app.staticTexts["published-audio-locale"].waitForExistence(timeout: 10))
        app.buttons["choose-content-language"].tap()
        app.buttons["content-language-ko"].tap()
        try waitFor(app.staticTexts["published-audio-locale"], "label CONTAINS '한국어'")
        XCTAssertFalse(app.buttons["prepare-published-audio"].exists)
        XCTAssertTrue(app.buttons["playback-toggle"].isEnabled)
        XCTAssertTrue(app.staticTexts["published-current-subtitle"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["published-current-subtitle"].label, "짧은 자막입니다.")
        XCTAssertEqual(app.staticTexts["published-current-english"].label, "This is the approved English source.")
        app.segmentedControls["listening-display"].buttons["字幕全文"].tap()
        XCTAssertTrue(app.staticTexts["published-caption-english-g1"].waitForExistence(timeout: 5))
        screenshot("dual-script-native-english-captions", app: app)
        app.buttons["choose-sermon"].tap()
        XCTAssertTrue(app.buttons["published-page-ui-test-full-video"].waitForExistence(timeout: 5))
        app.buttons["legacy-week-ui-test-week"].tap()
        XCTAssertEqual(app.staticTexts["sermon-title"].label, "界面测试证道")
    }

    func testEnglishLocateFromHomeReturnsToCurrentSubtitleAndCanUndo() throws {
        let app = launchFixture(locateFlow: true)
        try locateSecondEnglishSegment(in: app, fromDock: false)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        XCTAssertEqual(app.staticTexts["published-current-subtitle"].label, "中文第二句：灯塔在港口旁。")
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放", "手动定位必须保留暂停状态")
        XCTAssertFalse(element("english-locate-sheet", in: app).exists)
        screenshot("english-locate-home-second-segment-paused", app: app)
        app.buttons["playback-more"].tap()
        let undo = app.buttons["undo-seek"]
        try waitFor(undo, "exists == true AND hittable == true")
        undo.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:00'")
        XCTAssertEqual(app.staticTexts["published-current-subtitle"].label, "中文第一句：开始收听。")
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放")
        screenshot("english-locate-undo-original-position", app: app)
    }

    func testEnglishLocateFromDockAndFullTranscriptLanguageChangesKeepPosition() throws {
        let app = launchFixture(locateFlow: true)
        try locateSecondEnglishSegment(in: app, fromDock: true)
        let progress = element("playback-progress", in: app)
        try waitFor(progress, "value BEGINSWITH '00:12'")
        app.segmentedControls["listening-display"].buttons["字幕全文"].tap()
        let secondChinese = app.staticTexts["published-caption-text-g2"]
        try waitFor(secondChinese, "exists == true AND label == '中文第二句：灯塔在港口旁。'")
        XCTAssertTrue(app.staticTexts["published-caption-english-g2"].exists)
        XCTAssertTrue(app.buttons["published-caption-time-g2"].isSelected)
        let timestamp = app.buttons["published-caption-time-g2"]
        try reveal(timestamp, in: app, direction: .up)
        for _ in 0..<2 {
            timestamp.tap()
            try waitFor(progress, "value BEGINSWITH '00:12'")
            XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放",
                           "Repeated timestamp activation must retain pause and position")
        }
        screenshot("full-transcript-locate-chinese-at12", app: app)

        let language = element("app-language-menu", in: app)
        for _ in 0..<4 where !language.isHittable {
            app.scrollViews["listening-scroll"].swipeDown()
        }
        XCTAssertTrue(language.isHittable)
        language.tap()
        app.buttons["English"].tap()
        try waitFor(app.buttons["playback-toggle"], "label == 'Play'")
        try waitFor(progress, "value BEGINSWITH '00:12'")
        XCTAssertTrue(secondChinese.exists, "界面语言切换后全文模式应保留当前段落")
        XCTAssertTrue(app.buttons["published-caption-time-g2"].isSelected)
        XCTAssertEqual(app.segmentedControls["listening-display"].buttons["Full transcript"].isSelected, true)

        for (locale, sentence) in [
            ("ko", "한국어 두 번째 문장: 등대는 항구 옆에 있습니다."),
            ("zh-Hans", "中文第二句：灯塔在港口旁。")
        ] {
            let chooser = app.buttons["choose-content-language"]
            try reveal(chooser, in: app, direction: .down)
            chooser.tap()
            app.buttons["content-language-\(locale)"].tap()
            try waitFor(app.staticTexts["published-caption-text-g2"], "exists == true AND label == '\(sentence)'")
            try waitFor(app.buttons["playback-toggle"], "enabled == true AND label == 'Play'")
            try waitFor(progress, "value BEGINSWITH '00:12'")
            XCTAssertTrue(app.segmentedControls["listening-display"].buttons["Full transcript"].isSelected,
                          "制作语言切换不能离开全文模式")
            XCTAssertTrue(app.staticTexts["published-caption-english-g2"].label.contains("lighthouse"))
            XCTAssertTrue(app.buttons["published-caption-time-g2"].isSelected,
                          "制作语言切换必须保留全文中当前时间段的选择")
            screenshot("full-transcript-\(locale)-preserves-position12", app: app)
        }
    }

    func testEnglishLocateLateTranscriptArrivesNearRetainedCurrentPosition() throws {
        let app = launchFixture(locateFlow: true, delayedTranscript: true)
        try locateSecondEnglishSegment(in: app, fromDock: false)
        let progress = element("playback-progress", in: app)
        try waitFor(progress, "value BEGINSWITH '00:12'")
        let chooser = app.buttons["choose-content-language"]
        try reveal(chooser, in: app, direction: .down)
        chooser.tap()
        app.buttons["content-language-ko"].tap()
        try waitFor(app.staticTexts["published-audio-locale"], "exists == true AND label CONTAINS '한국어'")
        try waitFor(app.buttons["playback-toggle"], "enabled == true AND label == '开始播放'")
        try waitFor(progress, "value BEGINSWITH '00:12'")
        app.buttons["playback-more"].tap()
        app.buttons["locate-english-action"].tap()
        XCTAssertTrue(element("english-locate-sheet", in: app).waitForExistence(timeout: 5))
        let currentEnglish = app.staticTexts["locate-english-g2"]
        XCTAssertFalse(currentEnglish.exists, "本轮必须先打开定位页，再收到延迟文稿")
        // No reveal/swipe: the sheet itself must land at the retained 12s row
        // when its initially empty transcript is delivered asynchronously.
        let landed = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            currentEnglish.exists && currentEnglish.isHittable
                && currentEnglish.frame.minY < app.frame.midY
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [landed], timeout: 15), .completed)
        XCTAssertTrue(currentEnglish.label.contains("lighthouse"))
        screenshot("english-locate-delayed-transcript-near-current12", app: app)
        app.buttons["english-locate-close"].tap()
        try waitFor(progress, "value BEGINSWITH '00:12'")
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放")
    }

    func testEnglishLocateWhilePlayingShowsConfirmationAndKeepsPlaying() throws {
        let app = launchFixture(locateFlow: true)
        let play = app.buttons["playback-toggle"]
        try waitFor(play, "exists == true AND enabled == true")
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        try locateSecondEnglishSegment(in: app, fromDock: true)
        XCTAssertEqual(play.label, "暂停播放")
        XCTAssertTrue(app.staticTexts["locate-confirmation"].exists)
        XCTAssertTrue(app.buttons["locate-undo"].exists)
        screenshot("english-locate-playing-confirmation", app: app)
        play.tap()
    }

    func testEnglishLocateLargeTextKeepsSearchAndSeekReachable() throws {
        let app = launchFixture(largeText: true, locateFlow: true)
        try locateSecondEnglishSegment(in: app, fromDock: false)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放")
        screenshot("english-locate-large-text-current-at12", app: app)
    }

    func testCaptureFailureShowsReasonRetryAndEnglishLocateWithoutReset() throws {
        try assertCaptureFailureFeedback(largeText: false)
    }

    func testCaptureFailureLargeTextKeepsFallbackReachable() throws {
        try assertCaptureFailureFeedback(largeText: true)
    }

    func testImmediateRepeatedCaptureFailureAlwaysShowsFeedback() throws {
        try assertCaptureFailureFeedback(largeText: false, immediateFailure: true)
    }

    private func assertCaptureFailureFeedback(largeText: Bool, immediateFailure: Bool = false) throws {
        let app = launchFixture(largeText: largeText, locateFlow: true, alignmentFailure: true,
                                immediateFailure: immediateFailure)
        try locateSecondEnglishSegment(in: app, fromDock: true)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        app.buttons["playback-more"].tap()
        app.buttons["align-live-audio"].tap()
        let failure = app.alerts["听音对齐未完成"]
        XCTAssertTrue(failure.waitForExistence(timeout: 5))
        XCTAssertTrue(failure.staticTexts["未能取得有效声音，请重试。"].exists)
        XCTAssertFalse(app.alerts["playback-more-panel"].exists)
        XCTAssertTrue(failure.buttons["重试对齐"].isHittable)
        screenshot(largeText ? "alignment-capture-failure-large-after" : "alignment-capture-failure-after", app: app)
        failure.buttons["重试对齐"].tap()
        XCTAssertTrue(failure.waitForExistence(timeout: 5))
        failure.buttons["关闭"].tap()
        XCTAssertFalse(failure.exists)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放")
        app.buttons["playback-more"].tap()
        app.buttons["align-live-audio"].tap()
        XCTAssertTrue(failure.waitForExistence(timeout: 5))
        failure.buttons["按英文找位置"].tap()
        XCTAssertTrue(element("english-locate-sheet", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["english-locate-search"].exists)
        screenshot("alignment-failure-english-fallback", app: app)
    }

    func testUnavailableAlignmentOffersEnglishLocate() throws {
        let app = launchFixture(locateFlow: true)
        try waitFor(app.buttons["playback-toggle"], "exists == true AND enabled == true")
        app.buttons["playback-more"].tap()
        app.buttons["align-live-audio"].tap()
        let fallback = app.alerts.buttons.matching(NSPredicate(
            format: "label == %@ AND identifier != %@", "按英文找位置", "locate-english-action")).firstMatch
        XCTAssertTrue(fallback.waitForExistence(timeout: 5))
        fallback.tap()
        XCTAssertTrue(element("english-locate-sheet", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["english-locate-search"].exists)
        screenshot("alignment-unavailable-english-locate-fallback", app: app)
    }

    private func locateSecondEnglishSegment(in app: XCUIApplication, fromDock: Bool) throws {
        let play = app.buttons["playback-toggle"]
        try waitFor(play, "exists == true AND enabled == true")
        if fromDock {
            app.buttons["playback-more"].tap()
            let locate = app.buttons["locate-english-action"]
            try waitFor(locate, "exists == true AND hittable == true")
            locate.tap()
        } else {
            let locate = app.buttons["open-english-locate"]
            try reveal(locate, in: app, direction: .up)
            locate.tap()
        }
        let sheet = element("english-locate-sheet", in: app)
        XCTAssertTrue(sheet.waitForExistence(timeout: 5))
        let search = app.textFields["english-locate-search"]
        try waitFor(search, "exists == true AND hittable == true")
        search.tap()
        search.typeText("lighthouse\n")
        let row = element("locate-row-g2", in: app)
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        XCTAssertFalse(element("locate-row-g1", in: app).exists)
        XCTAssertFalse(element("locate-row-g3", in: app).exists)
        screenshot("english-locate-search-lighthouse", app: app)
        let select = app.buttons["locate-segment-g2"]
        try waitFor(select, "exists == true AND enabled == true AND hittable == true")
        select.tap()
        try waitFor(sheet, "exists == false")
        try waitFor(app.staticTexts["published-current-subtitle"], "label == '中文第二句：灯塔在港口旁。'")
    }

    /// Explicit Release-only production check; default Debug UI runs skip it.
    func testLiveProductionCurrentWeekNativeThreeLanguages() throws {
        #if DEBUG
        throw XCTSkip("Run this selected test with Release to verify production content.")
        #else
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        XCTAssertTrue(app.staticTexts["published-page-title"].waitForExistence(timeout: 30))
        app.buttons["choose-sermon"].tap()
        let currentPage = app.buttons["published-page-2026-09-27-weekend-sermon-drive-530"]
        let previousWeek = app.buttons["legacy-week-2026-09-20-same_video-7c193fd4-bc90-4f3b-aa00-37dfe8423aa0"]
        XCTAssertTrue(currentPage.waitForExistence(timeout: 10))
        XCTAssertTrue(previousWeek.waitForExistence(timeout: 5))
        XCTAssertLessThan(currentPage.frame.minY, previousWeek.frame.minY)
        screenshot("production-native-current-week-first-in-picker", app: app)
        currentPage.tap()
        app.buttons["watch-full-video"].tap()
        XCTAssertTrue(app.staticTexts["native-full-video"].waitForExistence(timeout: 5))
        screenshot("production-native-full-video-in-app", app: app)
        app.buttons["完成"].tap()
        for locale in ["zh-Hans", "ko", "es"] {
            app.buttons["choose-content-language"].tap()
            app.buttons["content-language-\(locale)"].tap()
            XCTAssertTrue(app.staticTexts["published-current-subtitle"].waitForExistence(timeout: 30))
            XCTAssertTrue(app.staticTexts["published-current-english"].waitForExistence(timeout: 10))
            let prepare = app.buttons["prepare-published-audio"]
            if prepare.exists {
                prepare.tap()
                XCTAssertTrue(app.staticTexts["published-audio-locale"].waitForExistence(timeout: 60))
            }
            XCTAssertTrue(app.staticTexts["published-audio-locale"].label.contains(appLanguageNames[locale]!))
            app.buttons["playback-toggle"].tap()
            try waitFor(element("playback-progress", in: app), "NOT (value BEGINSWITH '00:00，')")
            screenshot("production-native-\(locale)-playing-english", app: app)
            app.buttons["playback-toggle"].tap()
            app.segmentedControls["listening-display"].buttons["字幕全文"].tap()
            XCTAssertTrue(app.staticTexts["published-caption-english-translation-0-u001"].waitForExistence(timeout: 10))
            screenshot("production-native-\(locale)-transcript-english", app: app)
            app.segmentedControls["listening-display"].buttons["现场收听"].tap()
        }
        #endif
    }

    private var appLanguageNames: [String: String] {
        ["zh-Hans": "简体中文", "ko": "한국어", "es": "Español"]
    }

    func testFreshLaunchOpensCurrentPublishedPageAndPreparesAudio() throws {
        let app = launchFixture(independentDefault: true)
        XCTAssertTrue(app.staticTexts["published-page-title"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["published-page-title"].label, "ui-test-clip")
        XCTAssertTrue(app.staticTexts["published-audio-locale"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["prepare-published-audio"].exists)
        XCTAssertTrue(app.buttons["playback-toggle"].exists)
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
        XCTAssertFalse(app.buttons["prepare-published-audio"].exists)
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
        assertNavigationActionsAbovePlayer(in: app)
        app.buttons["choose-sermon"].tap()
        XCTAssertTrue(app.buttons["legacy-week-ui-test-week"].waitForExistence(timeout: 5))
        app.buttons["完成"].tap()
        app.buttons["more-options"].tap()
        XCTAssertTrue(element("privacy-support-link", in: app).waitForExistence(timeout: 5))
        app.buttons["完成"].tap()
        try assertAlignmentAvailableInMore(in: app)
        screenshot("landscape-alignment-in-more", app: app)
    }

    private func assertNavigationActionsAbovePlayer(in app: XCUIApplication,
                                                    file: StaticString = #filePath, line: UInt = #line) {
        let choose = app.buttons["choose-sermon"]
        let options = app.buttons["more-options"]
        let progress = element("playback-progress", in: app)
        XCTAssertTrue(choose.isHittable, file: file, line: line)
        XCTAssertTrue(options.isHittable, file: file, line: line)
        XCTAssertLessThan(choose.frame.maxY, options.frame.minY + 1, file: file, line: line)
        XCTAssertLessThan(options.frame.maxY + 8, progress.frame.minY,
                          "导航组和播放组需要清晰间距", file: file, line: line)
        XCTAssertEqual(choose.frame.midX, app.buttons["playback-toggle"].frame.midX, accuracy: 8,
                       "两组控件应在同一右侧轴线上", file: file, line: line)
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

    private func launchFixture(largeText: Bool = false, offline: Bool = false,
                               dualScript: Bool = false,
                               independentDefault: Bool = false,
                               locateFlow: Bool = false,
                               delayedTranscript: Bool = false, alignmentFailure: Bool = false,
                               immediateFailure: Bool = false, voiceClips: Bool = false) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing"] + (largeText ? ["--ui-testing-large-text"] : [])
            + (offline ? ["--ui-testing-offline"] : [])
            + (dualScript ? ["--ui-testing-dual-script"] : [])
            + (independentDefault ? ["--ui-testing-current-page-default"] : [])
            + (locateFlow ? ["--ui-testing-locate-flow"] : [])
            + (delayedTranscript ? ["--ui-testing-delayed-transcript"] : [])
            + (alignmentFailure ? ["--ui-testing-alignment-failure"] : [])
            + (immediateFailure ? ["--ui-testing-alignment-failure-immediate"] : [])
            + (voiceClips ? ["--ui-testing-voice-clips"] : [])
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
        } else if dualScript || independentDefault || locateFlow {
            XCTAssertTrue(app.staticTexts["published-page-title"].waitForExistence(timeout: 15))
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
            let playFrame = app.buttons["playback-toggle"].frame
            let usesTrailingRail = playFrame.midX >= app.frame.maxX - 84
                && playFrame.width <= 52
            // Duo puts progress in a side rail: its Y must not truncate the
            // reading viewport as it does for a bottom playback dock.
            let bottom = usesTrailingRail ? visibleFrame.maxY - 16
                : min(visibleFrame.maxY, element("playback-progress", in: app).frame.minY - 36)
            let readingWidth = usesTrailingRail
                ? min(visibleFrame.maxX, playFrame.minX - 16) - visibleFrame.minX
                : visibleFrame.width
            guard bottom - top >= 80 else {
                screenshot("insufficient-reading-region", app: app)
                XCTFail("实际界面没有足够的阅读区域供滚动")
                throw FlowFailure.unreachable
            }
            let readingFrame = CGRect(x: visibleFrame.minX, y: top,
                                      width: readingWidth, height: bottom - top)
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
            let x = readingFrame.midX - app.frame.minX
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

    // More is a separate Form, with no listening dock inside its scroll bounds.
    private func revealDemo(_ target: XCUIElement, in app: XCUIApplication, direction: ScrollDirection) throws {
        let form = app.collectionViews.firstMatch
        for _ in 0..<12 {
            let bounds = form.frame.intersection(app.frame).insetBy(dx: 12, dy: 16)
            let top = max(bounds.minY, app.navigationBars["更多选项"].frame.maxY + 12)
            let viewport = CGRect(x: bounds.minX, y: top, width: bounds.width, height: bounds.maxY - top)
            if target.exists && viewport.contains(target.frame) && target.isHittable { return }
            if target.exists && target.frame.midY < viewport.midY { form.swipeDown(velocity: .slow) }
            else { form.swipeUp(velocity: .slow) }
        }
        screenshot("unreachable-demo-\(target.identifier)", app: app)
        XCTFail("Demo 控件未进入可点击区域：\(target.identifier)")
        throw FlowFailure.unreachable
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func assertPlaybackMorePopoverNearButton(in app: XCUIApplication, buttonFrame: CGRect,
                                                    besideTrailingRail: Bool,
                                                    file: StaticString = #filePath, line: UInt = #line) {
        let panel = element("playback-more-panel", in: app)
        XCTAssertTrue(panel.waitForExistence(timeout: 5), file: file, line: line)
        guard panel.exists else { return }
        let panelFrame = panel.frame
        let horizontalGap = max(0, max(panelFrame.minX - buttonFrame.maxX, buttonFrame.minX - panelFrame.maxX))
        let verticalGap = max(0, max(panelFrame.minY - buttonFrame.maxY, buttonFrame.minY - panelFrame.maxY))
        XCTAssertLessThanOrEqual((horizontalGap * horizontalGap + verticalGap * verticalGap).squareRoot(), 44,
                                 "播放更多浮窗应贴近更多按钮", file: file, line: line)
        if besideTrailingRail {
            XCTAssertLessThanOrEqual(panelFrame.maxX, buttonFrame.minX + 4,
                                     "竖栏的更多浮窗应在按钮左侧", file: file, line: line)
        } else {
            XCTAssertLessThanOrEqual(panelFrame.maxY, buttonFrame.minY + 4,
                                     "底栏的更多浮窗应在按钮上方", file: file, line: line)
        }
        XCTAssertTrue(app.frame.contains(panelFrame), "播放更多浮窗应完整位于屏幕内", file: file, line: line)
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
