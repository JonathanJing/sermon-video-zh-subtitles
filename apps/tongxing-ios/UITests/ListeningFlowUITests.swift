import XCTest
import UIKit

/// Real application UI and AVPlayer, with generated silence and an injected
/// URLSession transport. The offline relaunch simulates transport failure;
/// these tests do not establish real-network, audible, lock-screen, or venue QA.
@MainActor
final class ListeningFlowUITests: XCTestCase {
    func testPrivacyNoticeIsAvailableWithoutMicrophonePermission() throws {
        let app = launchFixture()
        app.terminate()
        app.launchArguments.append("--ui-testing-offline")
        app.launch()
        try waitFor(element("catalog-notice", in: app), "label CONTAINS '上次保存的证道目录'")
        app.buttons["more-options"].tap()
        let privacy = element("privacy-support", in: app)
        for _ in 0..<6 {
            if privacy.exists && privacy.isHittable { break }
            app.collectionViews.firstMatch.swipeUp()
        }
        XCTAssertTrue(privacy.isHittable)
        privacy.tap()
        XCTAssertTrue(app.navigationBars["隐私与支持"].waitForExistence(timeout: 5))
        XCTAssertTrue(element("full-privacy-policy", in: app).isHittable)
        XCTAssertTrue(element("privacy-support-website", in: app).isHittable)
        XCTAssertTrue(element("privacy-contact-email", in: app).isHittable)
        XCTAssertEqual(app.alerts.count, 0)
        let localData = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "删除 App 可移除本机 App 资料；系统备份需在系统设置中管理")).firstMatch
        for _ in 0..<6 {
            if localData.exists && localData.isHittable { break }
            app.collectionViews.firstMatch.swipeUp()
        }
        XCTAssertTrue(localData.isHittable)
        screenshot("privacy-notice-offline-content", app: app)
    }

    func testEnglishInterfaceAndOriginalTranscriptPreserveSelectedPosition() throws {
        let app = launchFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        try seekToSecondSubtitle(in: app)
        try showTranscript(in: app)
        let english = element("transcript-english-1", in: app)
        try reveal(english, in: app, direction: .up, scrollIdentifier: "transcript-reading-scroll")
        XCTAssertTrue(english.label.contains("Second synthetic source sentence"))
        try closeReadingPaneIfPresented(in: app)
        app.buttons["more-options"].tap()
        let language = element("interface-language", in: app)
        try reveal(language, in: app, direction: .up)
        language.tap()
        app.buttons["English"].tap()
        app.buttons["Done"].tap()
        try waitFor(app.buttons["playback-toggle"], "label == 'Play'")
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
        XCTAssertEqual(element("sermon-title", in: app).label, "界面测试证道")
        try showTranscript(in: app)
        try reveal(english, in: app, direction: .up, scrollIdentifier: "transcript-reading-scroll")
        XCTAssertTrue(english.label.contains("Second synthetic source sentence"))
        screenshot("english-interface-source-bilingual-transcript", app: app)
        try closeReadingPaneIfPresented(in: app)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12'")
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
        try closeReadingPaneIfPresented(in: app)
        let current = app.buttons["current-cue"]
        XCTAssertTrue(current.isHittable)
        current.tap()
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
        try verifyAccessiblePlaybackControls(in: app)
    }

    func testIPadWideAccessibilityTextFallsBackToCompactReadableControls() throws {
        let app = try launchLandscapeFixture(largeText: true)
        XCTAssertGreaterThanOrEqual(app.frame.width, 840,
                                    "必须在实际宽窗口中验证无障碍字号回退")
        try waitFor(element("compact-layout", in: app), "exists == true")
        XCTAssertFalse(element("duo-layout", in: app).exists)
        XCTAssertFalse(element("reading-pane", in: app).exists)
        try verifyAccessiblePlaybackControls(in: app)
        screenshot("ipad-wide-accessibility3-compact-fallback", app: app)
    }

    private func verifyAccessiblePlaybackControls(in app: XCUIApplication) throws {
        try downloadSelection(in: app)
        let play = app.buttons["playback-toggle"]
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

    /// Run on an iPad whose actual portrait window becomes compact (for example
    /// iPad mini). There is no launch argument that forces a layout branch.
    func testIPadWideOutlineAndTranscriptReadingOnlySeekWithTimestampButton() throws {
        let app = try launchWideFixture()
        let pane = element("reading-pane", in: app)
        let current = element("current-subtitle", in: app)
        try waitForReadingMode(.outline, in: app)
        XCTAssertTrue(element("outline-reading-scroll", in: app).exists)
        XCTAssertTrue(app.staticTexts["测试大纲：起点"].isHittable)
        XCTAssertTrue(app.staticTexts["测试大纲：回应"].isHittable)
        XCTAssertTrue(current.isHittable, "宽屏默认应同时显示大纲和当前字幕")
        XCTAssertLessThanOrEqual(pane.frame.maxX, current.frame.minX + 1,
                                 "阅读面板和当前字幕应在两个并排区域中")
        XCTAssertEqual(app.buttons.matching(identifier: "playback-toggle").count, 1)

        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        app.buttons["current-cue"].tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:00，'")
        try showTranscript(in: app)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:00，'")
        let transcript = app.scrollViews["transcript-reading-scroll"]
        let thirdPassage = transcript.staticTexts["乙音轨：第三句，用于验证继续收听。"]
        try reveal(thirdPassage, in: app, direction: .up, scrollIdentifier: "transcript-reading-scroll")
        thirdPassage.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:00，'")
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放",
                       "切换、滚动和点击正文不能自动定位或开始播放")

        try selectReadingMode(.outline, in: app)
        try selectReadingMode(.transcript, in: app)
        // Do not reveal again: that would hide a lost reading anchor by scrolling
        // back to the expected passage as part of the assertion itself.
        try waitForReadingViewport(thirdPassage, in: app)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:00，'")
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放")

        // Start within the current cue, so a mistaken seek to its start would
        // change the asserted time instead of passing unnoticed at 00:00.
        app.buttons["nudge-forward"].tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:01，'")
        let returnToCurrent = app.buttons["reader-current-cue"]
        XCTAssertTrue(returnToCurrent.isHittable)
        returnToCurrent.tap()
        try waitForReadingViewport(transcript.staticTexts["乙音轨：第一句，用于验证选轨。"], in: app)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:01，'")
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放",
                       "阅读面板回到当前句只应滚动，不能改变播放时间或开始播放")

        let timestamp = app.buttons["subtitle-cue-1"]
        try reveal(timestamp, in: app, direction: .down, scrollIdentifier: "transcript-reading-scroll")
        timestamp.tap()
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12，'")
        try waitFor(current, "value == '乙音轨：第二句，用于验证时间定位。'")
        try selectReadingMode(.outline, in: app)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12，'")
        XCTAssertTrue(app.staticTexts["测试大纲：起点"].isHittable)
        XCTAssertEqual(app.buttons["playback-toggle"].label, "开始播放")
        screenshot("ipad-wide-outline-current-subtitle-explicit-seek", app: app)
    }

    func testIPadPlaybackAndReadingSelectionSurviveWideCompactWideRotation() throws {
        let app = try launchWideFixture()
        try selectSecondTrack(in: app)
        try downloadSelection(in: app)
        app.buttons["current-cue"].tap()
        try seekToSecondSubtitle(in: app)
        let thirdPassage = app.scrollViews["transcript-reading-scroll"]
            .staticTexts["乙音轨：第三句，用于验证继续收听。"]
        try reveal(thirdPassage, in: app, direction: .up, scrollIdentifier: "transcript-reading-scroll")
        let wideWidth = app.frame.width
        let progress = element("playback-progress", in: app)
        let play = app.buttons["playback-toggle"]
        play.tap()
        try waitFor(play, "label == '暂停播放'")
        try waitFor(progress, "value CONTAINS '正在收听'")
        let beforeRotation = try playbackSeconds(in: app)

        XCUIDevice.shared.orientation = .portrait
        try waitFor(element("compact-layout", in: app), "exists == true")
        XCTAssertLessThan(app.frame.width, wideWidth, "必须真实收窄窗口，不能只替换布局标记")
        XCTAssertFalse(element("duo-layout", in: app).exists)
        XCTAssertTrue(element("current-subtitle", in: app).isHittable)
        XCTAssertTrue(play.isHittable)
        XCTAssertEqual(play.label, "暂停播放", "收窄窗口不能暂停或重新开始播放")
        XCTAssertGreaterThanOrEqual(try playbackSeconds(in: app), beforeRotation)
        try openReadingPaneIfNeeded(in: app)
        try waitForReadingMode(.transcript, in: app)
        XCTAssertTrue(element("transcript-reading-scroll", in: app).exists)
        // Observe restoration directly; scrolling here would mask a lost anchor
        // or an unwanted jump to the currently playing cue.
        try waitForReadingViewport(thirdPassage, in: app)
        try closeReadingPaneIfPresented(in: app)
        screenshot("ipad-portrait-compact-playback-continues", app: app)

        XCUIDevice.shared.orientation = .landscapeLeft
        try waitFor(element("duo-layout", in: app), "exists == true")
        XCTAssertGreaterThan(app.frame.width, app.frame.height)
        try waitForReadingMode(.transcript, in: app)
        XCTAssertTrue(element("reading-pane", in: app).exists)
        XCTAssertTrue(app.segmentedControls["reading-mode-picker"].isHittable)
        try waitForReadingViewport(thirdPassage, in: app)
        XCTAssertEqual(element("sermon-title", in: app).label, "界面测试证道")
        XCTAssertEqual(play.label, "暂停播放", "重新展开必须保留播放意图")
        XCTAssertEqual(app.buttons.matching(identifier: "playback-toggle").count, 1)
        let afterRotation = try playbackSeconds(in: app)
        XCTAssertGreaterThan(afterRotation, beforeRotation, "跨布局期间应由同一播放器继续推进")
        play.tap()
        try waitFor(progress, "value CONTAINS '已暂停'")
        let pausedPosition = try playbackSeconds(in: app)
        XCTAssertGreaterThanOrEqual(pausedPosition, afterRotation)
        // Returning to the same explicit cue also verifies that the selected
        // second track survived both changes of the actual window dimensions.
        let timestamp = app.buttons["subtitle-cue-1"]
        try reveal(timestamp, in: app, direction: .down, scrollIdentifier: "transcript-reading-scroll")
        timestamp.tap()
        try waitFor(progress, "value BEGINSWITH '00:12，'")
        try waitFor(element("current-subtitle", in: app), "value == '乙音轨：第二句，用于验证时间定位。'")
        XCTAssertEqual(play.label, "开始播放")
        screenshot("ipad-landscape-reading-selection-and-track-retained", app: app)
    }

    private func launchWideFixture() throws -> XCUIApplication {
        let app = try launchLandscapeFixture()
        try waitFor(element("duo-layout", in: app), "exists == true")
        return app
    }

    private func launchLandscapeFixture(largeText: Bool = false) throws -> XCUIApplication {
        guard UIDevice.current.userInterfaceIdiom == .pad else {
            throw XCTSkip("此用例仅在 iPad 执行；iPhone 继续运行通用单屏回归。")
        }
        let previousOrientation = XCUIDevice.shared.orientation
        XCUIDevice.shared.orientation = .landscapeLeft
        addTeardownBlock {
            await MainActor.run { XCUIDevice.shared.orientation = previousOrientation }
        }
        let app = launchFixture(largeText: largeText)
        XCTAssertGreaterThan(app.frame.width, app.frame.height,
                             "此用例需要可在横竖屏间跨越宽屏阈值的 iPad")
        return app
    }

    private func launchFixture(largeText: Bool = false) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing"] + (largeText ? ["--ui-testing-large-text"] : [])
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
        XCTAssertTrue(element("sermon-title", in: app).waitForExistence(timeout: 15))
        XCTAssertEqual(element("sermon-title", in: app).label, "界面测试证道")
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
        try showTranscript(in: app)
        let timestamp = app.buttons["subtitle-cue-1"]
        try reveal(timestamp, in: app, direction: .up, scrollIdentifier: "transcript-reading-scroll")
        XCTAssertTrue(timestamp.isEnabled)
        timestamp.tap()
        try closeReadingPaneIfPresented(in: app)
        try waitFor(element("playback-progress", in: app), "value BEGINSWITH '00:12，'")
        try waitFor(element("playback-progress", in: app), "value CONTAINS '已定位 00:12'")
    }

    private enum ReadingMode { case outline, transcript }

    private func openReadingPaneIfNeeded(in app: XCUIApplication) throws {
        guard !element("reading-pane", in: app).exists else { return }
        let open = app.buttons["open-reading-pane"]
        try reveal(open, in: app, direction: .down)
        open.tap()
        try waitFor(element("reading-pane", in: app), "exists == true")
    }

    private func selectReadingMode(_ mode: ReadingMode, in app: XCUIApplication) throws {
        try openReadingPaneIfNeeded(in: app)
        let picker = app.segmentedControls["reading-mode-picker"]
        try waitFor(picker, "exists == true AND hittable == true")
        let option = picker.buttons.element(boundBy: mode == .outline ? 0 : 1)
        try waitFor(option, "exists == true AND hittable == true")
        if !option.isSelected { option.tap() }
        try waitForReadingMode(mode, in: app)
    }

    private func waitForReadingMode(_ mode: ReadingMode, in app: XCUIApplication) throws {
        let option = app.segmentedControls["reading-mode-picker"].buttons.element(boundBy: mode == .outline ? 0 : 1)
        try waitFor(option, "exists == true AND selected == true")
        XCTAssertTrue(option.isSelected, "阅读模式必须由系统分段按钮的实际选中状态确认")
    }

    private func showTranscript(in app: XCUIApplication) throws {
        try selectReadingMode(.transcript, in: app)
    }

    private func closeReadingPaneIfPresented(in app: XCUIApplication) throws {
        let close = app.buttons["close-reading-pane"]
        guard close.exists else { return }
        close.tap()
        try waitFor(close, "exists == false")
    }

    private func playbackSeconds(in app: XCUIApplication) throws -> Int {
        let value = element("playback-progress", in: app).value as? String ?? ""
        let parts = value.prefix(5).split(separator: ":")
        guard parts.count == 2, let minutes = Int(parts[0]), let seconds = Int(parts[1]) else {
            XCTFail("播放器没有可解析的实际时间：\(value)")
            throw FlowFailure.unreachable
        }
        return minutes * 60 + seconds
    }

    private enum ScrollDirection { case up, down }

    private func waitForReadingViewport(_ target: XCUIElement, in app: XCUIApplication) throws {
        let scroll = app.scrollViews["transcript-reading-scroll"]
        let visible = NSPredicate { _, _ in
            guard scroll.exists, target.exists, target.isHittable else { return false }
            let viewport = scroll.frame.intersection(app.frame)
            return !target.frame.isEmpty && viewport.contains(target.frame)
        }
        let expectation = XCTNSPredicateExpectation(predicate: visible, object: target)
        guard XCTWaiter.wait(for: [expectation], timeout: 15) == .completed else {
            screenshot("reading-anchor-not-restored", app: app)
            XCTFail("阅读位置恢复后，目标正文应直接保留在阅读面板可见范围内")
            throw FlowFailure.timeout
        }
    }

    private func reveal(_ target: XCUIElement, in app: XCUIApplication, direction: ScrollDirection,
                        scrollIdentifier: String = "listening-scroll") throws {
        let scroll = app.scrollViews[scrollIdentifier]
        for _ in 0..<10 {
            // safeAreaBar leaves the ScrollView's accessibility frame extending
            // beneath the floating dock. Clip to actual visible reading bounds;
            // a whole-ScrollView percentage can land on the large-text play button.
            let visibleFrame = scroll.frame.intersection(app.frame)
            let top = max(visibleFrame.minY, app.navigationBars.firstMatch.frame.maxY) + 16
            // The sidebar and compact reading sheet have their own viewport;
            // the dock belongs to the separate main listening page.
            let isReadingViewport = scrollIdentifier == "transcript-reading-scroll"
            let bottom = isReadingViewport ? visibleFrame.maxY - 16
                : min(visibleFrame.maxY, element("playback-progress", in: app).frame.minY - 36)
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
