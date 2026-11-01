import XCTest

@MainActor
final class WeeklyGuidePreviewUITests: XCTestCase {
    // These two tests use the real local Chinese payload and verified Dev
    // sermon identities, rather than the synthetic guide fixture.
    func testLiveChineseWeekFiveShowsIndependentLists() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-resi-20261011-54475d42"]
        let chooser = app.scrollViews.firstMatch
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            chooser.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 15))
        language.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 10))
        chinese.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        let section = app.buttons["guide-section-page-83"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 20))
        for _ in 0..<10 {
            if section.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(section.isHittable)
        section.tap()
        XCTAssertTrue(app.staticTexts["创造之日"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["“反创造”之号"].exists)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "live-chinese-week-five-structured-table"
        image.lifetime = .keepAlways
        add(image)
    }

    func testLiveChineseWeekOneImageCanBeOpenedAndClosed() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["legacy-week-2026-09-13-same_video-weekendlive-a9e91f52eb4c2484"]
        let chooser = app.scrollViews.firstMatch
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            chooser.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 15))
        let playback = app.buttons["playback-toggle"].label
        entry.tap()
        let section = app.buttons["guide-section-page-31"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 20))
        for _ in 0..<10 {
            if section.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(section.isHittable)
        section.tap()
        // The outer section groups accessibility identifiers; select the
        // image by its source-backed alternative text instead.
        let image = app.buttons["尼布甲尼撒梦中巨像的插画，五个部位对应的解释见本页文字。"]
        XCTAssertTrue(image.waitForExistence(timeout: 10))
        for _ in 0..<4 {
            if image.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(image.isHittable)
        image.tap()
        let zoomIn = app.buttons["放大图片"]
        XCTAssertTrue(zoomIn.waitForExistence(timeout: 10))
        zoomIn.tap()
        XCTAssertTrue(app.buttons["缩小图片"].isEnabled)
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "live-chinese-week-one-image-zoom"
        shot.lifetime = .keepAlways
        add(shot)
        app.buttons["关闭"].tap()
        let visiblePlay = app.buttons.matching(identifier: "playback-toggle").allElementsBoundByIndex.first(where: { $0.isHittable })
        XCTAssertEqual(visiblePlay?.label, playback)
    }

    func testLiveChineseWeekOneMapAndSecondImage() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["legacy-week-2026-09-13-same_video-weekendlive-a9e91f52eb4c2484"]
        let chooser = app.scrollViews.firstMatch
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            chooser.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 15))
        entry.tap()
        let section = app.buttons["guide-section-page-33"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 20))
        for _ in 0..<10 {
            if section.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(section.isHittable)
        section.tap()
        XCTAssertTrue(app.staticTexts["七教会与拔摩岛"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["1. 别迦摩"].exists)
        XCTAssertTrue(app.staticTexts["8. 拔摩岛"].exists)
        XCTAssertTrue(app.staticTexts["地点约略位置示意，并非教会建筑精确位置。"].exists)
        let sources = app.staticTexts["查看地图来源"]
        for _ in 0..<6 {
            if sources.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(sources.isHittable)
        sources.tap()
        XCTAssertTrue(app.links["别迦摩"].waitForExistence(timeout: 5))
        let mapShot = XCTAttachment(screenshot: app.screenshot())
        mapShot.name = "live-chinese-week-one-map-source"
        mapShot.lifetime = .keepAlways
        add(mapShot)
        let secondImage = app.buttons["原手册中人子形象的插画。"]
        for _ in 0..<20 {
            if secondImage.exists && secondImage.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(secondImage.exists && secondImage.isHittable)
        secondImage.tap()
        XCTAssertTrue(app.buttons["放大图片"].waitForExistence(timeout: 10))
        app.buttons["关闭"].tap()
    }

    func testLiveChineseWeekSixTableRetainsUnlabeledFirstColumn() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-resi-20261018-15030286"]
        XCTAssertTrue(week.waitForExistence(timeout: 10))
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 15))
        language.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 10))
        chinese.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        let section = app.buttons["guide-section-page-92"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 20))
        for _ in 0..<10 {
            if section.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(section.isHittable)
        section.tap()
        let row = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "书卷的赐予者")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "live-chinese-week-six-unlabeled-table"
        shot.lifetime = .keepAlways
        add(shot)
    }

    // Actual Dev catalog and same-origin v2 guide, not a UI fixture.
    func testLiveDevKoreanWeekThreeOpensMatchingRemoteGuide() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }

        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-2026-09-27-weekend-sermon-drive-530"]
        let scroll = app.scrollViews.firstMatch
        XCTAssertTrue(scroll.waitForExistence(timeout: 10))
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 15))
        language.tap()
        let korean = app.buttons["content-language-ko"]
        XCTAssertTrue(korean.waitForExistence(timeout: 10))
        korean.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        XCTAssertTrue(app.staticTexts["韩语机器翻译 · 未经人工审校"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["第 3 周 · 예수님은 합당하십니다"].exists)
        let section = app.buttons["guide-section-source-page-56"]
        XCTAssertTrue(section.exists)
        XCTAssertTrue(section.label.contains("합당하신 분"))
        XCTAssertFalse(app.staticTexts["本周研读手册尚不可用"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "live-dev-korean-week-three-guide"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    func testLiveDevSpanishWeekThreeOpensMatchingRemoteGuide() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }

        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-2026-09-27-weekend-sermon-drive-530"]
        let scroll = app.scrollViews.firstMatch
        XCTAssertTrue(scroll.waitForExistence(timeout: 10))
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable)
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 15))
        language.tap()
        let spanish = app.buttons["content-language-es"]
        XCTAssertTrue(spanish.waitForExistence(timeout: 10))
        spanish.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        XCTAssertTrue(app.staticTexts["西语机器翻译 · 未经人工审校"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["第 3 周 · Jesús es digno"].exists)
        let section = app.buttons["guide-section-source-page-56"]
        XCTAssertTrue(section.exists)
        XCTAssertTrue(section.label.contains("Aquel que es digno"))
        XCTAssertFalse(app.staticTexts["本周研读手册尚不可用"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "live-dev-spanish-week-three-guide"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    // Week six is a v5 family with distinct Chinese and Korean sources.
    func testLiveDevKoreanWeekSixMatchesItsOwnSource() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 30))
        choose.tap()
        let week = app.buttons["published-page-resi-20261018-15030286"]
        XCTAssertTrue(week.waitForExistence(timeout: 10))
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 15))
        language.tap()
        let korean = app.buttons["content-language-ko"]
        XCTAssertTrue(korean.waitForExistence(timeout: 10))
        korean.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        XCTAssertTrue(app.staticTexts["韩语机器翻译 · 未经人工审校"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["第 6 周 · 예수님은 자기 백성을 보내시고 부활시키십니다"].exists)
        XCTAssertTrue(app.buttons["guide-section-source-page-86"].exists)
        XCTAssertFalse(app.staticTexts["本周研读手册尚不可用"].exists)
    }

    func testLandscapeAutomaticallyShowsGuideAndRotationKeepsPlayback() {
        let app = launchLandscapeGuide(prepareAudio: true)
        defer { app.terminate(); XCUIDevice.shared.orientation = .portrait }
        let guide = app.scrollViews["guide-scroll"]
        let listening = app.scrollViews["listening-scroll"]
        XCTAssertTrue(guide.waitForExistence(timeout: 15))
        XCTAssertTrue(listening.exists)
        XCTAssertLessThanOrEqual(guide.frame.maxX, listening.frame.minX + 1)
        XCTAssertFalse(app.buttons["guide-close"].exists)
        XCTAssertFalse(app.buttons["open-guide-beta-preview"].exists)
        XCTAssertEqual(app.buttons.matching(identifier: "playback-toggle").count, 1)
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.isHittable)
        let before = play.label
        let rightFrame = listening.frame
        let pausedPosition = play.value as? String
        let menu = app.buttons["guide-chapter-menu"]
        recordGuideHitRegions(app: app, phase: "after-download-and-rotation")
        XCTAssertTrue(menu.isHittable)
        XCTAssertEqual(menu.label, "本周研读手册")
        let navigationFrame = app.navigationBars.firstMatch.frame
        XCTAssertGreaterThanOrEqual(menu.frame.minY, navigationFrame.minY - 2)
        XCTAssertLessThanOrEqual(menu.frame.maxY, navigationFrame.maxY + 2)
        let headerTop = menu.frame.minY
        attachLandscape("landscape-guide-header-top", app: app)
        menu.tap()
        XCTAssertTrue(app.buttons["guide-section-group"].waitForExistence(timeout: 5))
        app.buttons["guide-section-group"].tap()
        let body = app.staticTexts["测试用讨论内容，不代表教会手册。"]
        XCTAssertTrue(body.waitForExistence(timeout: 5))
        XCTAssertTrue(body.isHittable)
        guide.swipeUp()
        XCTAssertEqual(menu.frame.minY, headerTop, accuracy: 1)
        XCTAssertEqual(play.label, before)
        XCTAssertEqual(play.value as? String, pausedPosition)
        XCTAssertEqual(listening.frame, rightFrame)
        attachLandscape("landscape-guide-and-listening", app: app)
        play.tap()
        XCTAssertNotEqual(play.label, before)
        let playing = play.label
        XCUIDevice.shared.orientation = .portrait
        XCTAssertTrue(app.buttons["open-guide-beta-preview"].waitForExistence(timeout: 10))
        XCTAssertFalse(guide.exists)
        XCTAssertEqual(app.buttons["playback-toggle"].label, playing)
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(guide.waitForExistence(timeout: 10))
        XCTAssertEqual(app.buttons["playback-toggle"].label, playing)
        let playingPosition = playbackSeconds(app.buttons["playback-toggle"])
        XCTAssertNotNil(playingPosition)
        let advanced = expectation(for: NSPredicate { _, _ in
            guard let before = playingPosition,
                  let now = self.playbackSeconds(app.buttons["playback-toggle"]) else { return false }
            return now > before
        }, evaluatedWith: nil)
        wait(for: [advanced], timeout: 5)
        XCTAssertEqual(app.buttons["playback-toggle"].label, playing)
        // A system Menu can keep XCTest waiting for UI idleness until this
        // 36-second fixture ends. Verify rotation progress first, then pause
        // before exercising the menu again and checking stable position.
        app.buttons["playback-toggle"].tap()
        XCTAssertEqual(app.buttons["playback-toggle"].label, before)
        let positionAfterRotation = playbackSeconds(app.buttons["playback-toggle"])
        XCTAssertNotNil(positionAfterRotation)
        recordGuideHitRegions(app: app, phase: "after-second-rotation")
        XCTAssertTrue(menu.isHittable)
        menu.tap()
        XCTAssertTrue(app.buttons["guide-section-group"].waitForExistence(timeout: 5))
        app.buttons["guide-section-group"].tap()
        XCTAssertTrue(body.isHittable)
        XCTAssertEqual(app.buttons["playback-toggle"].label, before)
        XCTAssertEqual(playbackSeconds(app.buttons["playback-toggle"]), positionAfterRotation)
    }

    private func playbackSeconds(_ button: XCUIElement) -> Int? {
        guard let value = button.value as? String,
              let time = value.components(separatedBy: "，").first else { return nil }
        let fields = time.split(separator: ":")
        guard (2...3).contains(fields.count) else { return nil }
        var seconds = 0
        for field in fields {
            guard let part = Int(field), part >= 0 else { return nil }
            seconds = seconds * 60 + part
        }
        return seconds
    }

    private func recordGuideHitRegions(app: XCUIApplication, phase: String) {
        let menu = app.buttons["guide-chapter-menu"]
        let detail = "phase=\(phase) menu=\(menu.frame) hittable=\(menu.isHittable) "
            + "navigation=\(app.navigationBars.allElementsBoundByIndex.map(\.frame)) "
            + "guide=\(app.scrollViews["guide-scroll"].frame) "
            + "listening=\(app.scrollViews["listening-scroll"].frame)"
        print(detail)
        let attachment = XCTAttachment(string: detail)
        attachment.name = "guide-hit-regions-\(phase)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testOpenPortraitGuideMovesIntoLandscapePane() {
        let app = launchLandscapeGuide(prepareAudio: true, startLandscape: false)
        defer { app.terminate(); XCUIDevice.shared.orientation = .portrait }
        let scroll = app.scrollViews["listening-scroll"]
        let entry = app.buttons["open-guide-beta-preview"]
        for _ in 0..<12 {
            if entry.isHittable { break }
            scroll.swipeDown()
        }
        XCTAssertTrue(entry.isHittable)
        let position = app.buttons["playback-toggle"].value as? String
        entry.tap()
        XCTAssertTrue(app.buttons["guide-close"].waitForExistence(timeout: 10))
        XCUIDevice.shared.orientation = .landscapeLeft
        let dismissed = expectation(for: NSPredicate(format: "exists == false"),
                                    evaluatedWith: app.buttons["guide-close"])
        wait(for: [dismissed], timeout: 10)
        XCTAssertTrue(app.scrollViews["guide-scroll"].exists)
        XCTAssertTrue(app.scrollViews["listening-scroll"].exists)
        XCTAssertEqual(app.buttons.matching(identifier: "playback-toggle").count, 1)
        XCTAssertEqual(app.buttons["playback-toggle"].value as? String, position)
        attachLandscape("portrait-guide-to-landscape-pane", app: app)
    }

    func testLandscapeUnavailableGuideKeepsListeningVisible() {
        let app = launchLandscapeGuide(withGuide: false)
        defer { app.terminate(); XCUIDevice.shared.orientation = .portrait }
        XCTAssertTrue(app.scrollViews["guide-scroll"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["本周研读手册尚不可用"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.scrollViews["listening-scroll"].exists)
        XCTAssertTrue(app.buttons["playback-toggle"].isHittable)
        XCTAssertFalse(app.buttons["guide-chapter-menu"].exists)
        attachLandscape("landscape-guide-unavailable", app: app)
    }

    func testLandscapeLargeTextKeepsChaptersAndPlayerReachable() {
        let app = launchLandscapeGuide(largeText: true)
        defer { app.terminate(); XCUIDevice.shared.orientation = .portrait }
        XCTAssertTrue(app.scrollViews["guide-scroll"].waitForExistence(timeout: 15))
        let menu = app.buttons["guide-chapter-menu"]
        XCTAssertTrue(menu.isHittable)
        menu.tap()
        app.buttons["guide-section-group"].tap()
        let body = app.staticTexts["测试用讨论内容，不代表教会手册。"]
        XCTAssertTrue(body.waitForExistence(timeout: 5))
        XCTAssertTrue(body.isHittable)
        XCTAssertTrue(app.buttons["playback-toggle"].isHittable)
        attachLandscape("landscape-guide-large-text", app: app)
    }

    private func launchLandscapeGuide(withGuide: Bool = true, largeText: Bool = false,
                                      prepareAudio: Bool = false, startLandscape: Bool = true) -> XCUIApplication {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
            + (withGuide ? ["--ui-testing-study-guide"] : [])
            + (largeText ? ["--ui-testing-large-text"] : [])
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        XCTAssertTrue(app.staticTexts["sermon-title"].waitForExistence(timeout: 15))
        if prepareAudio {
            let download = app.buttons["download-audio"]
            let scroll = app.scrollViews["listening-scroll"]
            for _ in 0..<12 {
                // XCTest can report a button behind the floating player as hittable.
                // Bring the entire download button above the dock before tapping it.
                if download.isHittable,
                   download.frame.maxY < app.buttons["playback-toggle"].frame.minY - 12 { break }
                scroll.swipeUp()
            }
            XCTAssertTrue(download.isHittable)
            XCTAssertLessThan(download.frame.maxY, app.buttons["playback-toggle"].frame.minY - 12)
            download.tap()
            let downloaded = expectation(for: NSPredicate(format: "label CONTAINS %@", "正在使用已下载音频"),
                                         evaluatedWith: app.descendants(matching: .any).matching(identifier: "download-status").firstMatch)
            wait(for: [downloaded], timeout: 15)
            let ready = expectation(for: NSPredicate(format: "enabled == true"),
                                    evaluatedWith: app.buttons["playback-toggle"])
            wait(for: [ready], timeout: 15)
        }
        if startLandscape { XCUIDevice.shared.orientation = .landscapeLeft }
        return app
    }

    private func attachLandscape(_ name: String, app: XCUIApplication) {
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = name
        image.lifetime = .keepAlways
        add(image)
    }

    func testGuideNavigationKeepsPlaybackAndShowsReviewDisclosure() {
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "--ui-testing-study-guide", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 20))
        XCTAssertTrue(entry.label.contains("本周研读手册"))
        let play = app.buttons["playback-toggle"]
        XCTAssertTrue(play.waitForExistence(timeout: 10))
        let playLabel = play.label
        entry.tap()
        XCTAssertTrue(app.staticTexts["中文机器翻译 · 未经人工审校"].waitForExistence(timeout: 10))
        let visiblePlay = app.buttons.matching(identifier: "playback-toggle").allElementsBoundByIndex.first(where: { $0.isHittable })
        XCTAssertEqual(visiblePlay?.label, playLabel)
        XCTAssertFalse(app.buttons["playback-dock-collapse-toggle"].exists)
        let group = app.buttons["guide-section-group"]
        XCTAssertTrue(group.exists)
        group.tap()
        XCTAssertTrue(app.staticTexts["测试用讨论内容，不代表教会手册。"].waitForExistence(timeout: 5))
        let question = app.staticTexts["测试用讨论内容，不代表教会手册。"]
        let visible = expectation(for: NSPredicate(format: "hittable == true"), evaluatedWith: question)
        wait(for: [visible], timeout: 5)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "guide-test-discussion"
        image.lifetime = .keepAlways
        add(image)
        let close = app.buttons["guide-close-bottom"]
        if !close.isHittable { app.scrollViews["guide-scroll"].swipeUp() }
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons["playback-toggle"].label, playLabel)
    }
    func testUnmappedSermonShowsUnavailableInsteadOfAnotherWeek() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing", "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_UI_TEST_RUN_ID"] = UUID().uuidString
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 20))
        entry.tap()
        XCTAssertTrue(app.staticTexts["本周研读手册尚不可用"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts["第 7 周 · 耶稣得胜"].exists)
        app.buttons["guide-close"].tap()
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
    }

    // This verifies the real locally staged bundle against the live Dev page.
    // A clean checkout has no licensed payload and skips this optional readback.
    func testLocalGuideBundleDisplaysCurrentDevWeekWhenAvailable() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        guard app.staticTexts["published-page-title"].waitForExistence(timeout: 30) ||
              app.otherElements["published-page"].waitForExistence(timeout: 5) else {
            throw XCTSkip("Live Dev published page was not available")
        }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 10))
        choose.tap()
        let week = app.buttons["published-page-resi-20261018-15030286"]
        guard week.waitForExistence(timeout: 10) else {
            throw XCTSkip("The checked Dev page is no longer in the live catalog")
        }
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 10))
        language.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 10))
        chinese.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        let unavailable = app.staticTexts["本周研读手册尚不可用"]
        if unavailable.waitForExistence(timeout: 3) {
            throw XCTSkip("Local guide payload or mapping is not available for the live Dev page")
        }
        XCTAssertTrue(app.staticTexts["中文机器翻译 · 未经人工审校"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["guide-section-scripture-cuv1919"].exists)
        XCTAssertTrue(app.buttons["guide-close"].exists)
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "local-guide-real-bundle"
        image.lifetime = .keepAlways
        add(image)
    }

    // Live Dev readback; uses the real app catalog and staged Bundle, not UI fixtures.
    func testLiveDevLegacyWeekOneOpensMatchingGuide() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }

        let choose = app.buttons["choose-sermon"]
        guard choose.waitForExistence(timeout: 30) else {
            throw XCTSkip("Live Dev sermon selector is unavailable")
        }
        choose.tap()
        let week = app.buttons["legacy-week-2026-09-13-same_video-weekendlive-a9e91f52eb4c2484"]
        let scroll = app.scrollViews.firstMatch
        guard scroll.waitForExistence(timeout: 10) else {
            throw XCTSkip("Live Dev sermon list is unavailable")
        }
        for _ in 0..<35 {
            if week.exists && week.isHittable { break }
            scroll.swipeUp()
        }
        guard week.exists && week.isHittable else {
            throw XCTSkip("The verified legacy week-one sermon is absent or cannot be reached in the live Dev catalog")
        }
        week.tap()
        let heading = app.staticTexts["sermon-title"]
        XCTAssertTrue(heading.waitForExistence(timeout: 20))
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 10))
        entry.tap()
        XCTAssertTrue(app.staticTexts["第 1 周 · 耶稣与你同在"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.staticTexts["中文机器翻译 · 未经人工审校"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "live-dev-legacy-week-one-guide"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }


    // Production check for the 2026-11-01 page: the remote v1 manifest, its
    // release binding and the guide bytes are all served by the production
    // origin (the Debug scheme sets TONGXING_CONTENT_ORIGIN to production).
    func testProductionWeekEightGuideLoads() {
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"]
        app.launchEnvironment["TONGXING_TEST_HOST"] = "0"
        app.launch()
        defer { app.terminate() }
        let choose = app.buttons["choose-sermon"]
        XCTAssertTrue(choose.waitForExistence(timeout: 45))
        choose.tap()
        let week = app.buttons["published-page-revelation-jesus-marks-his-own-20261101"]
        let chooser = app.scrollViews.firstMatch
        for _ in 0..<45 {
            if week.exists && week.isHittable { break }
            chooser.swipeUp()
        }
        XCTAssertTrue(week.exists && week.isHittable, "week 8 page missing from the production chooser")
        week.tap()
        let language = app.buttons["choose-content-language"]
        XCTAssertTrue(language.waitForExistence(timeout: 20))
        language.tap()
        let chinese = app.buttons["content-language-zh-Hans"]
        XCTAssertTrue(chinese.waitForExistence(timeout: 10))
        chinese.tap()
        let entry = app.buttons["open-guide-beta-preview"]
        XCTAssertTrue(entry.waitForExistence(timeout: 15))
        entry.tap()
        let section = app.buttons["guide-section-page-109"]
        let scroll = app.scrollViews["guide-scroll"]
        XCTAssertTrue(section.waitForExistence(timeout: 30), "guide sheet did not load the production manifest")
        XCTAssertFalse(app.staticTexts["本周研读手册尚不可用"].exists)
        XCTAssertTrue(app.staticTexts["手册第 107 页"].waitForExistence(timeout: 10))
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "production-week-eight-guide"
        shot.lifetime = .keepAlways
        add(shot)
        section.tap()
        XCTAssertTrue(app.staticTexts["第 8 周　启示录 14 章"].waitForExistence(timeout: 10) ||
                      app.staticTexts["耶稣为属祂的人盖印"].waitForExistence(timeout: 10))
        let detail = XCTAttachment(screenshot: app.screenshot())
        detail.name = "production-week-eight-guide-detail"
        detail.lifetime = .keepAlways
        add(detail)
    }
}
