import Foundation
import AVFoundation
import TongxingCore
import XCTest
@testable import Tongxing

@MainActor
final class AudioAlignmentControllerTests: XCTestCase {
    func testForegroundAlignmentFeedbackObservesPlaybackAndExistingResultExpiry() async throws {
        guard Bundle.main.object(forInfoDictionaryKey: "TongxingURLScheme") as? String == "tongxing-beta" else {
            throw XCTSkip("Foreground alignment is enabled only in the Beta identity")
        }
        let model = AppModel(supportDirectory: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString), contentOrigin: URL(string: "https://example.invalid")!)
        model.playback.setAlignmentPhase(.preparing)
        model.playback.setAlignmentPhase(.listening)
        model.playback.setAlignmentPhase(.aligned)
        XCTAssertEqual(model.foregroundAlignmentPhase, .aligned)
        try await Task.sleep(for: .milliseconds(8_300))
        XCTAssertNil(model.playback.alignmentPhase)
        XCTAssertNil(model.foregroundAlignmentPhase)
    }

    func testForegroundAlignmentFeedbackFollowsFastTransactionAndClearsWithController() {
        let model = AppModel(supportDirectory: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString), contentOrigin: URL(string: "https://example.invalid")!)
        XCTAssertNil(model.foregroundAlignmentPhase)
        // A terminal phase without an explicit transaction is not a popup.
        model.updateForegroundAlignmentPhase(.aligned)
        XCTAssertNil(model.foregroundAlignmentPhase)
        for result in [ListeningAlignmentPhase.aligned, .unmatched, .failed] {
            model.updateForegroundAlignmentPhase(.preparing)
            model.updateForegroundAlignmentPhase(.listening)
            model.updateForegroundAlignmentPhase(.matching)
            model.updateForegroundAlignmentPhase(result)
            XCTAssertEqual(model.foregroundAlignmentPhase, result)
            model.updateForegroundAlignmentPhase(nil)
            XCTAssertNil(model.foregroundAlignmentPhase)
        }
    }

    func testForegroundAlignmentFeedbackDoesNotReplayAfterBackground() {
        let model = AppModel(supportDirectory: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString), contentOrigin: URL(string: "https://example.invalid")!)
        model.updateForegroundAlignmentPhase(.preparing)
        model.updateForegroundAlignmentPhase(.listening)
        model.setAlignmentFeedbackForeground(false)
        XCTAssertNil(model.foregroundAlignmentPhase)
        model.updateForegroundAlignmentPhase(.failed)
        model.setAlignmentFeedbackForeground(true)
        model.updateForegroundAlignmentPhase(.failed)
        XCTAssertNil(model.foregroundAlignmentPhase)
        model.updateForegroundAlignmentPhase(.preparing)
        model.updateForegroundAlignmentPhase(.listening)
        XCTAssertEqual(model.foregroundAlignmentPhase, .listening)
    }

    func testDevCandidateSelectionRequiresBetaIdentityAndExactOrigin() throws {
        let origin = URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!
        XCTAssertTrue(AppModel.permitsDevCandidates(origin: origin, bundleIdentifier: "com.jonathanjing.tongxing.beta"))
        for identifier in ["com.jonathanjing.tongxing", "com.jonathanjing.tongxing.beta.tests", "unknown"] {
            XCTAssertFalse(AppModel.permitsDevCandidates(origin: origin, bundleIdentifier: identifier))
        }
        for url in ["https://ai-for-god-sermon-audio.web.app", "http://ai-for-god-sermon-audio-dev.web.app", "https://ai-for-god-sermon-audio-dev.web.app:444", "https://other.example", "https://user@ai-for-god-sermon-audio-dev.web.app"] {
            XCTAssertFalse(AppModel.permitsDevCandidates(origin: URL(string: url)!, bundleIdentifier: "com.jonathanjing.tongxing.beta"))
        }
        let fixtureURL = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Core/Tests/TongxingCoreTests/Fixtures/dev-candidate-catalog-readback.json")
        let fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL)) as? [String: Any])
        let catalog = try MultilingualCatalog.decode(JSONSerialization.data(withJSONObject: fixture["catalog"]!), allowDevCandidates: true)
        let page = catalog.pages[1]
        XCTAssertEqual(AppModel.selectableTargets(in: page, allowDevCandidates: true).map(\.locale), ["es", "ko", "zh-Hans"])
        XCTAssertEqual(AppModel.selectableTargets(in: page, allowDevCandidates: false).map(\.locale), ["zh-Hans"])
        XCTAssertEqual(page.targets["ko"]?.contentStatus, "machine_reviewed")
    }

    func testFrozenDevCandidateLanguagesCanBeSelectedAndReadWithoutHumanPromotion() async throws {
        guard let path = ProcessInfo.processInfo.environment["TONGXING_DEV_CATALOG_FIXTURE_ROOT"] else {
            throw XCTSkip("Frozen public Dev assets were not provided; no live network fallback")
        }
        let fixtureRoot = URL(fileURLWithPath: path)
        CandidateAppModelProtocol.fixtureRoot = fixtureRoot
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CandidateAppModelProtocol.self]
        let session = URLSession(configuration: config)
        let support = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite = "Tongxing-Candidate-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        let origin = URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!
        let model = AppModel(supportDirectory: support, contentOrigin: origin, session: session,
            statisticsDefaults: defaults, applicationBundleIdentifier: "com.jonathanjing.tongxing.beta")
        defer {
            model.playback.clear(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite)
            try? FileManager.default.removeItem(at: support)
        }
        await model.refresh()
        let page = try XCTUnwrap(model.independentPages.first { $0.id == "if-i-had-more-time-jesus-is-worthy" })
        model.selectPublishedPage(page)
        XCTAssertNil(model.fullVideoURL, "Podcast candidates must not invent a full-video path")
        XCTAssertEqual(model.availableContentLanguages.map(\.locale), ["es", "ko", "zh-Hans"])
        for locale in ["ko", "es", "zh-Hans"] {
            model.selectPublishedContentLanguage(locale)
            await model.loadSelectedPublishedTranscript()
            XCTAssertEqual(model.selectedContentLocale, locale)
            XCTAssertEqual(model.publishedTranscript?.captions.count, 839)
            XCTAssertEqual(model.publishedTranscript?.releaseStatus, "candidate")
            XCTAssertEqual(model.publishedTranscript?.contentStatus, locale == "zh-Hans" ? "human_reviewed" : "machine_reviewed")
            XCTAssertTrue(model.selectedContentReviewNotice?.contains(locale == "zh-Hans" ? "设备验收尚未完成" : "人工全文审核未批准") == true)
        }
        let production = AppModel(supportDirectory: support.appendingPathComponent("production"), contentOrigin: origin,
            session: session, statisticsDefaults: defaults, applicationBundleIdentifier: "com.jonathanjing.tongxing")
        defer { production.playback.clear() }
        await production.refresh()
        XCTAssertFalse(production.independentPages.contains { $0.id == page.id })
        production.selectPublishedPage(page)
        XCTAssertNotEqual(production.selectedPageID, page.id)
    }

    func testQueryStartUsesMonotonicElapsedOnceAndRejectsExpiredOrOutOfRange() {
        let start = ContinuousClock.now
        XCTAssertEqual(AlignmentTarget.position(offset: 100, startedAt: start,
                       now: start.advanced(by: .seconds(8.25)), duration: 300), 108.25)
        XCTAssertNil(AlignmentTarget.position(offset: 100, startedAt: start,
                     now: start.advanced(by: .seconds(31)), duration: 300))
        XCTAssertNil(AlignmentTarget.position(offset: 295, startedAt: start,
                     now: start.advanced(by: .seconds(8)), duration: 300))
        XCTAssertNil(AlignmentTarget.position(offset: .nan, startedAt: start, now: start, duration: 300))
    }

    func testPausedMatchSeeksOnceWithoutAutoplayAndReleasesCapture() async throws {
        let f = try Fixture()
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [108])
        XCTAssertEqual(f.player.resumes, 0)
        XCTAssertFalse(f.player.isPlaying)
        XCTAssertGreaterThan(f.capture.stops, 0)
        XCTAssertEqual(f.status, "已对齐至 {time}。")
        XCTAssertEqual(f.resultPosition, 108)
        XCTAssertTrue(f.failures.isEmpty)
        XCTAssertEqual(f.phases, [.preparing, .listening, .matching, .aligned])
    }

    func testFailedMatchNeverSeeksAndRestoresPriorPlayingIntent() async throws {
        let f = try Fixture(playing: true, result: Self.noMatch)
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(f.player.resumes, 1)
        XCTAssertTrue(f.player.isPlaying)
        XCTAssertEqual(f.status, "未找到可靠匹配，播放位置未改变。")
        XCTAssertEqual(f.failures, [f.status])
        XCTAssertEqual(f.phases, [.preparing, .listening, .matching, .listening, .matching, .listening, .matching, .listening, .matching, .unmatched])
    }

    func testManualSeekCancelsLateMatcherWithoutOverwritingUserPosition() async throws {
        let gate = ResultGate()
        let f = try Fixture(matcher: { _, _ in await gate.result() })
        f.controller.start()
        try await gate.waitUntilStarted()
        f.player.alignmentRevision = UUID()
        f.controller.cancel()
        f.player.position = 42
        await gate.finish(Self.match)
        try await Task.sleep(for: .milliseconds(20))
        XCTAssertEqual(f.player.position, 42)
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertFalse(f.controller.busy)
        XCTAssertTrue(f.failures.isEmpty)
    }

    func testSourceChangeDefeatsLateResultEvenWithoutExplicitCancel() async throws {
        let gate = ResultGate()
        let f = try Fixture(matcher: { _, _ in await gate.result() })
        f.controller.start()
        try await gate.waitUntilStarted()
        f.selection = nil
        await gate.finish(Self.match)
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(f.player.resumes, 0)
        XCTAssertTrue(f.failures.isEmpty)
    }

    func testRevokedCapabilityOnSameTrackDefeatsLateMatch() async throws {
        let gate = ResultGate()
        let f = try Fixture(matcher: { _, _ in await gate.result() })
        f.controller.start()
        try await gate.waitUntilStarted()
        let selected = try XCTUnwrap(f.selection)
        let old = selected.track
        let revoked = SermonTrack(id: old.id, label: old.label, voiceLabel: old.voiceLabel,
            audioUrl: old.audioUrl, file: old.file, sha256: old.sha256, durationSeconds: old.durationSeconds,
            cues: old.cues, subtitleTiming: old.subtitleTiming, scope: old.scope)
        f.selection = .init(week: selected.week, track: revoked)
        await gate.finish(Self.match)
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(f.player.resumes, 0)
    }

    func testTimeoutStopsCaptureAndLateResultCannotSeek() async throws {
        let gate = ResultGate()
        let f = try Fixture(deadline: .milliseconds(40), matcher: { _, _ in await gate.result() })
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.status, "对齐超时，请保持前台后重试。")
        XCTAssertEqual(f.failures, [f.status])
        XCTAssertEqual(f.phases, [.preparing, .listening, .matching, .failed])
        XCTAssertGreaterThan(f.capture.stops, 0)
        await gate.finish(Self.match)
        try await Task.sleep(for: .milliseconds(20))
        XCTAssertEqual(f.player.seeks, [])
    }

    func testPermissionDenialNeverChangesPositionOrLeaksBusyState() async throws {
        let f = try Fixture()
        f.capture.failure = AudioAlignmentError.permissionDenied
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(f.phases, [.preparing, .failed], "Permission dialog must never be reported as active listening")
        XCTAssertEqual(f.status, AudioAlignmentError.permissionDenied.localizedDescription)
        XCTAssertEqual(f.failures, [f.status])
        XCTAssertGreaterThan(f.capture.stops, 0)
    }

    func testInvalidCaptureReportsFailureWithoutMovingPausedPlayer() async throws {
        let f = try Fixture()
        f.player.position = 42
        f.capture.failure = AudioAlignmentError.invalidCapture
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.failures, [AudioAlignmentError.invalidCapture.localizedDescription])
        XCTAssertEqual(f.player.position, 42)
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(f.player.resumes, 0)
    }

    func testInterruptedCaptureDoesNotResumeAudioWithoutSystemPermission() async throws {
        let f = try Fixture(playing: true)
        f.capture.failure = AudioAlignmentError.interrupted
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.resumes, 0)
        XCTAssertFalse(f.player.isPlaying)
        XCTAssertEqual(f.failures, [AudioAlignmentError.interrupted.localizedDescription])
    }

    func testPlaybackStartupDelayGetsOneFinalCorrection() async throws {
        let f = try Fixture(playing: true)
        f.player.onResume = { f.elapsed = 10 }
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [108, 110])
        XCTAssertEqual(f.player.resumes, 1)
        XCTAssertEqual(f.resultPosition, 110)
    }

    func testCancellationDuringResumeCannotLaterCorrectThePosition() async throws {
        let f = try Fixture(playing: true)
        f.player.onResume = {
            f.player.isPlaying = false
            f.player.isWaiting = true
        }
        f.controller.start()
        try await eventually { f.player.resumes == 1 }
        f.player.alignmentRevision = UUID()
        f.controller.cancel()
        f.player.position = 50
        f.player.isPlaying = true
        f.elapsed = 11
        try await Task.sleep(for: .milliseconds(80))
        XCTAssertEqual(f.player.seeks, [108])
        XCTAssertEqual(f.player.position, 50)
        XCTAssertFalse(f.controller.busy)
    }

    func testNoCapabilityDoesNotRequestMicrophone() async throws {
        let f = try Fixture()
        f.selection = nil
        f.controller.start()
        XCTAssertFalse(f.controller.busy)
        XCTAssertEqual(f.capture.calls, 0)
    }

    func testPublishedCapabilityStreamsWithinBudgetAndSilenceNeverSeeks() async throws {
        let f = try Fixture(published: true)
        XCTAssertTrue(f.controller.available)
        f.controller.start()
        try await eventually(timeout: .seconds(15)) { !f.controller.busy }
        XCTAssertEqual(f.capture.requestedMaxSeconds, [15])
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(f.status, "未找到可靠匹配，播放位置未改变。")
        XCTAssertGreaterThan(f.capture.stops, 0)
    }

    func testIndependentPageUsesBoundIndexAndCancelsAfterLocaleChange() async throws {
        let hash = String(repeating: "a", count: 64)
        let trackHash = String(repeating: "b", count: 64)
        let catalogData = try JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-multilingual-catalog-v2", "generatedAt": "2026-09-24T00:00:00Z",
            "defaultPageId": "clip-1", "pages": [[
                "id": "clip-1", "date": "2026-09-20", "sourceLocale": "en",
                "sourceIdentitySha256": hash, "sourceMediaSha256": hash,
                "defaultTargetLocale": "zh-Hans", "targets": ["zh-Hans": [
                    "releasePackageUrl": "/releases/clip-1/zh-Hans.json",
                    "releasePackageJsonSha256": hash, "contentStatus": "human_reviewed",
                    "audioStatus": "human_reviewed", "capabilities": ["text", "audio", "alignment"],
                    "audioFingerprint": ["schemaVersion": "sermon-audio-fingerprint-binding-v1",
                        "pageId": "clip-1", "sourceSha256": hash, "trackSha256": trackHash,
                        "sourceStartSeconds": 0, "sourceEndSeconds": 138,
                        "algorithmVersion": "spectral-landmarks-v1", "captureSeconds": 10,
                        "indexSha256": hash, "indexUrl": "/fingerprints/aaaaaaaaaaaaaaaa-landmarks.json"]
                ]]]]
        ])
        let page = try MultilingualCatalog.decode(catalogData).defaultPage
        let indexData = try JSONSerialization.data(withJSONObject: [
            "schemaVersion": "sermon-landmark-index-v1", "algorithmVersion": "spectral-landmarks-v1",
            "sampleRate": 8000, "hopSize": 256, "fftSize": 1024,
            "sourceSha256": hash, "trackSha256": trackHash, "pageId": page.id,
            "sourceStartSeconds": 0, "sourceEndSeconds": 138,
            "window": ["startSeconds": 0, "endSeconds": 138], "durationSeconds": 138,
            "landmarkCount": 1, "postings": ["1": [0]]
        ])
        let index = try PublishedFingerprintIndex.decode(indexData)
        let player = FakePlayback()
        player.duration = 138.004
        let capture = FakeCapture()
        capture.samples = [Float](repeating: 0, count: 80_000)
        var selected: AudioAlignmentController.PublishedSelection? =
            .init(page: page, locale: "zh-Hans", trackSha256: trackHash, durationSeconds: player.duration)
        var loaded = 0
        let controller = AudioAlignmentController(playback: player, capture: capture,
            getSelection: { nil }, loadIndex: { _ in throw AudioAlignmentError.unavailable },
            getPublishedSelection: { selected }, loadPageIndex: { selection in
                loaded += 1
                try index.validate(binding: XCTUnwrap(selection.page.targets[selection.locale]?.audioFingerprint))
                return index
            }, onState: { _, _, _ in })
        XCTAssertTrue(controller.available)
        controller.start()
        try await eventually(timeout: .seconds(15)) { !controller.busy }
        XCTAssertEqual(loaded, 1)
        XCTAssertEqual(capture.requestedMaxSeconds, [15])
        XCTAssertTrue(player.seeks.isEmpty)
        selected = nil
        XCTAssertFalse(controller.available)
    }

    func testReviewedPublishedCapabilityRemainsAvailableAndStartsCapture() async throws {
        let f = try Fixture(published: true)
        let initial = try XCTUnwrap(f.selection)
        var document = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(initial.week)) as? [String: Any])
        var tracks = try XCTUnwrap(document["tracks"] as? [[String: Any]])
        tracks[0]["scope"] = "full_reviewed"
        document["tracks"] = tracks
        document["humanApproval"] = true
        let reviewed = try JSONDecoder().decode(SermonWeek.self, from: JSONSerialization.data(withJSONObject: document))
        f.selection = .init(week: reviewed, track: reviewed.tracks[0])
        XCTAssertTrue(f.controller.available)
        f.controller.start()
        try await eventually(timeout: .seconds(15)) { !f.controller.busy }
        XCTAssertEqual(f.capture.requestedMaxSeconds, [15])
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(f.status, "未找到可靠匹配，播放位置未改变。")
    }

    func testPublishedCancelledLateIndexCannotStartMicrophone() async throws {
        let gate = ResultGate()
        let f = try Fixture(published: true, publishedLoadGate: gate)
        f.controller.start()
        try await gate.waitUntilStarted()
        f.controller.cancel()
        f.player.position = 42
        await gate.finish(Self.noMatch)
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(f.capture.calls, 0)
        XCTAssertEqual(f.player.position, 42)
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertFalse(f.controller.busy)
        XCTAssertEqual(f.status, "已取消对齐。")
        XCTAssertEqual(f.phases, [.preparing, .cancelled])
    }

    func testPublishedSourceWindowChangeRejectsLateIndexWithoutResume() async throws {
        let gate = ResultGate()
        let f = try Fixture(playing: true, published: true, publishedLoadGate: gate)
        f.controller.start()
        try await gate.waitUntilStarted()
        let selected = try XCTUnwrap(f.selection)
        var document = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(selected.week)) as? [String: Any])
        document["sourceStartSeconds"] = 1701
        let changed = try JSONDecoder().decode(SermonWeek.self, from: JSONSerialization.data(withJSONObject: document))
        f.selection = .init(week: changed, track: selected.track)
        XCTAssertFalse(f.controller.available)
        await gate.finish(Self.noMatch)
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.capture.calls, 0)
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(f.player.resumes, 0)
        XCTAssertNil(f.resultPosition)
    }

    func testSameTrackCapabilityRefreshReplacesUnavailableStatus() async throws {
        let fixture = try Fixture()
        let selected = try XCTUnwrap(fixture.selection)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("TongxingAlignmentModel-\(UUID())")
        let model = AppModel(supportDirectory: directory, contentOrigin: URL(string: "https://example.invalid")!)
        defer {
            model.playback.clear()
            try? FileManager.default.removeItem(at: directory)
        }
        let unavailable = withoutAlignment(selected.track)
        await model.select(week: selected.week, track: unavailable)
        model.playback.clear()
        XCTAssertEqual(model.alignmentDisplayStatus, "本篇尚未提供现场对齐资料，请刷新目录或手动定位。")
        XCTAssertFalse(model.alignmentAvailable)

        await model.select(week: selected.week, track: selected.track)

        XCTAssertEqual(model.alignmentStatus, "请播放同一录音的原声，再点击听声对齐。")
        XCTAssertEqual(model.alignmentDisplayStatus, "音频尚未准备就绪，请稍候或重新载入音频。")
        XCTAssertFalse(model.alignmentAvailable, "A capability must not bypass player readiness")
        XCTAssertNil(model.alignmentPosition)
    }

    func testSameTrackCapabilityRevocationClearsCompletedAlignmentFeedback() async throws {
        let fixture = try Fixture()
        let selected = try XCTUnwrap(fixture.selection)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("TongxingAlignmentModel-\(UUID())")
        let model = AppModel(supportDirectory: directory, contentOrigin: URL(string: "https://example.invalid")!)
        defer {
            model.playback.clear()
            try? FileManager.default.removeItem(at: directory)
        }
        await model.select(week: selected.week, track: selected.track)
        model.playback.clear()
        model.updateAlignmentState(status: "已对齐至 {time}。", busy: false, position: 108)
        XCTAssertEqual(model.alignmentDisplayStatus, "已对齐至 {time}。")
        XCTAssertEqual(model.alignmentPosition, 108)

        // A metadata-only refresh must preserve the last result.
        await model.select(week: selected.week, track: selected.track)
        XCTAssertEqual(model.alignmentPosition, 108)
        await model.select(week: selected.week, track: withoutAlignment(selected.track))

        XCTAssertNil(model.alignmentPosition)
        XCTAssertFalse(model.alignmentBusy)
        XCTAssertFalse(model.alignmentAvailable)
        XCTAssertEqual(model.alignmentDisplayStatus, "本篇尚未提供现场对齐资料，请刷新目录或手动定位。")
    }

    func testPublishedFingerprintRefreshAndWindowChangeInvalidateOldFeedback() async throws {
        let fixture = try Fixture()
        let selected = try XCTUnwrap(fixture.selection)
        let track = withoutAlignment(selected.track)
        let hash = track.sha256
        var document = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(selected.week)) as? [String: Any])
        document["tracks"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode([track]))
        document["sourceSha256"] = hash
        document["sourceStartSeconds"] = 1700
        document["sourceEndSeconds"] = 2000
        func decodeWeek() throws -> SermonWeek {
            try JSONDecoder().decode(SermonWeek.self, from: JSONSerialization.data(withJSONObject: document))
        }
        let unavailableWeek = try decodeWeek()
        document["audioFingerprint"] = [
            "schemaVersion": "sermon-audio-fingerprint-binding-v1", "pageId": selected.week.id,
            "sourceSha256": hash, "trackSha256": hash,
            "sourceStartSeconds": 1700, "sourceEndSeconds": 2000,
            "algorithmVersion": "spectral-landmarks-v1", "captureSeconds": 10,
            "indexSha256": hash, "indexUrl": "/fingerprints/\(hash.prefix(16))-landmarks.json"
        ] as [String: Any]
        let availableWeek = try decodeWeek()
        try XCTUnwrap(availableWeek.audioFingerprint).validate(week: availableWeek, track: track)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("TongxingAlignmentModel-\(UUID())")
        let model = AppModel(supportDirectory: directory, contentOrigin: URL(string: "https://example.invalid")!)
        defer {
            model.playback.clear()
            try? FileManager.default.removeItem(at: directory)
        }
        await model.select(week: unavailableWeek, track: track)
        model.playback.clear()
        XCTAssertEqual(model.alignmentDisplayStatus, "本篇尚未提供现场对齐资料，请刷新目录或手动定位。")
        await model.select(week: availableWeek, track: track)
        XCTAssertEqual(model.alignmentStatus, "请播放同一录音的原声，再点击听声对齐。")
        XCTAssertEqual(model.alignmentDisplayStatus, "音频尚未准备就绪，请稍候或重新载入音频。")
        model.updateAlignmentState(status: "已对齐至 {time}。", busy: false, position: 108)
        document["sourceStartSeconds"] = 1701
        await model.select(week: try decodeWeek(), track: track)
        XCTAssertNil(model.alignmentPosition)
        XCTAssertFalse(model.alignmentAvailable)
        XCTAssertEqual(model.alignmentDisplayStatus, "本篇尚未提供现场对齐资料，请刷新目录或手动定位。")
    }

    func testEarlyStopAtFirstCheckpointSeeksOnceAndStopsMic() async throws {
        let counter = CallCounter()
        let f = try Fixture(matcher: { prefix, _ in
            counter.increment()
            XCTAssertEqual(prefix.samples.count, 56_000, "First checkpoint must contain seven seconds")
            return Self.match
        })
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [108])
        XCTAssertEqual(counter.count, 1)
        XCTAssertEqual(f.capture.requestedMaxSeconds, [15])
        XCTAssertEqual(f.capture.session?.cancels, 1)
        XCTAssertEqual(f.status, "已对齐至 {time}。")
        XCTAssertEqual(f.resultPosition, 108)
        XCTAssertTrue(f.failures.isEmpty)
    }

    func testMissThenHitContinuesInSameSession() async throws {
        let counter = CallCounter()
        let f = try Fixture(matcher: { prefix, _ in
            counter.increment()
            XCTAssertEqual(prefix.samples.count, counter.count == 1 ? 56_000 : 80_000)
            return counter.count == 1 ? Self.noMatch : Self.match
        })
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [108])
        XCTAssertEqual(counter.count, 2)
        XCTAssertEqual(f.capture.requestedMaxSeconds, [15])
        XCTAssertEqual(f.status, "已对齐至 {time}。")
        XCTAssertTrue(f.failures.isEmpty)
    }

    func testAllCheckpointsMissNeverSeeks() async throws {
        let counter = CallCounter()
        let f = try Fixture(matcher: { _, _ in counter.increment(); return Self.noMatch })
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [])
        XCTAssertEqual(counter.count, 4)
        XCTAssertEqual(f.capture.requestedMaxSeconds, [15])
        XCTAssertEqual(f.status, "未找到可靠匹配，播放位置未改变。")
        XCTAssertEqual(f.failures, [f.status])
    }

    func testSlowCheckpointMatchTimesOutAndLaterCheckpointHits() async throws {
        let gate = ResultGate()
        let counter = CallCounter()
        let f = try Fixture(matchBudget: .milliseconds(60), matcher: { _, _ in
            counter.increment()
            if counter.count == 1 { return await gate.result() }
            return Self.match
        })
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [108])
        XCTAssertEqual(counter.count, 2)
        XCTAssertEqual(f.status, "已对齐至 {time}。")
        await gate.finish(Self.noMatch)
    }

    func testTimedOutCheckpointLateHitCannotReplaceLaterMatch() async throws {
        let gate = ResultGate()
        let counter = CallCounter()
        let f = try Fixture(matchBudget: .milliseconds(30), matcher: { _, _ in
            counter.increment()
            if counter.count == 1 { return await gate.result() }
            return Self.match
        })
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertEqual(f.player.seeks, [108])
        XCTAssertEqual(counter.count, 2)
        XCTAssertEqual(f.capture.session?.maxWaitedSeconds, 10)
        await gate.finish(FingerprintMatchResult(matched: true, offsetSeconds: 200,
            confidence: 1, diagnostics: .init(reason: "late")))
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(f.player.seeks, [108])
    }

    func testInterruptionWhileMatchingDiscardsHitAndDoesNotResume() async throws {
        let f = try Fixture(playing: true)
        f.capture.terminalAfterMatch = AudioAlignmentError.interrupted
        f.controller.start()
        try await eventually { !f.controller.busy }
        XCTAssertTrue(f.player.seeks.isEmpty)
        XCTAssertEqual(f.player.resumes, 0)
        XCTAssertEqual(f.status, AudioAlignmentError.interrupted.localizedDescription)
        XCTAssertEqual(f.phases.last, .failed)
    }

    func testCancelWhileWaitingForCheckpointNeverMatchesOrSeeks() async throws {
        let gate = ResultGate()
        let counter = CallCounter()
        let f = try Fixture(matcher: { _, _ in counter.increment(); return Self.match })
        f.capture.checkpointWait = { _ = await gate.result() }
        f.controller.start()
        try await gate.waitUntilStarted()
        f.controller.cancel()
        XCTAssertFalse(f.controller.busy)
        XCTAssertEqual(f.capture.session?.cancels, 1)
        await gate.finish(Self.noMatch)
        try await Task.sleep(for: .milliseconds(20))
        XCTAssertEqual(counter.count, 0)
        XCTAssertTrue(f.player.seeks.isEmpty)
        XCTAssertTrue(f.failures.isEmpty)
        XCTAssertEqual(f.phases.last, .cancelled)
    }

    func testContinuousSessionWithoutBuffersStopsAtWallBudget() async throws {
        var restores = 0
        let session = ContinuousCaptureSession(owner: nil, token: UUID(),
            engineSetup: {}, restorePlayback: { _ in restores += 1 })
        let start = ContinuousClock.now
        try session.startEngine(maxSeconds: 0.03)
        do { try await session.waitUntil(seconds: 7); XCTFail("No-buffer capture must fail") }
        catch { XCTAssertEqual(error as? AudioAlignmentError, .invalidCapture) }
        XCTAssertTrue(session.isFinished)
        XCTAssertLessThan(start.duration(to: .now), .seconds(1))
        XCTAssertEqual(restores, 1)
        session.cancel()
        XCTAssertEqual(restores, 1, "Cleanup must run once")
    }

    func testContinuousSessionStartupFailureRestoresOnce() throws {
        var restores = 0
        let session = ContinuousCaptureSession(owner: nil, token: UUID(),
            engineSetup: { throw AudioAlignmentError.invalidCapture },
            restorePlayback: { _ in restores += 1 })
        XCTAssertThrowsError(try session.startEngine(maxSeconds: 15))
        XCTAssertTrue(session.isFinished)
        XCTAssertEqual(restores, 1)
        session.cancel()
        XCTAssertEqual(restores, 1)
    }

    func testContinuousAccumulatorRejectsFrameGapAndKeepsOneStartClock() throws {
        let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 8000, channels: 1))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 800))
        buffer.frameLength = 800
        for i in 0..<800 { buffer.floatChannelData![0][i] = 0.1 }
        let accumulator = CaptureAccumulator(sampleRate: 8000, seconds: 15)
        XCTAssertNil(accumulator.append(buffer, at: AVAudioTime(sampleTime: 0, atRate: 8000)))
        let first = try XCTUnwrap(accumulator.snapshot())
        XCTAssertNil(accumulator.append(buffer, at: AVAudioTime(sampleTime: 800, atRate: 8000)))
        XCTAssertEqual(accumulator.snapshot()?.startedAt, first.startedAt)
        XCTAssertEqual(accumulator.accumulatedSeconds, 0.2, accuracy: 0.0001)
        guard case .failure(let error) = accumulator.append(buffer, at: AVAudioTime(sampleTime: 2400, atRate: 8000)) else {
            return XCTFail("A missing buffer must not be spliced into continuous PCM")
        }
        XCTAssertEqual(error as? AudioAlignmentError, .interrupted)
        XCTAssertEqual(accumulator.accumulatedSeconds, 0.2, accuracy: 0.0001)
    }

    private func withoutAlignment(_ track: SermonTrack) -> SermonTrack {
        SermonTrack(id: track.id, label: track.label, voiceLabel: track.voiceLabel,
            audioUrl: track.audioUrl, file: track.file, sha256: track.sha256,
            durationSeconds: track.durationSeconds, cues: track.cues,
            subtitleTiming: track.subtitleTiming, scope: track.scope)
    }

    private static let match = FingerprintMatchResult(matched: true, offsetSeconds: 100, confidence: 0.9,
                                                      diagnostics: .init(reason: "matched"))
    private static let noMatch = FingerprintMatchResult(matched: false, offsetSeconds: nil, confidence: 0,
                                                        diagnostics: .init(reason: "no-match"))

    private func eventually(timeout: Duration = .seconds(3), _ predicate: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: timeout)
        while !predicate() {
            guard ContinuousClock.now < deadline else { XCTFail("Timed out waiting for alignment state"); return }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    @MainActor
    private final class Fixture {
        let player = FakePlayback()
        let capture = FakeCapture()
        let start = ContinuousClock.now
        var elapsed = 8.0
        var selection: AudioAlignmentController.Selection?
        var status = ""
        var failures: [String] = []
        var phases: [ListeningAlignmentPhase] = []
        var resultPosition: Double?
        var controller: AudioAlignmentController!

        init(playing: Bool = false, result: FingerprintMatchResult = AudioAlignmentControllerTests.match,
             deadline: Duration = .seconds(20), matchBudget: Duration = .seconds(3),
             matcher: AudioAlignmentController.Matcher? = nil,
             published: Bool = false, publishedLoadGate: ResultGate? = nil) throws {
            let hash = String(repeating: "a", count: 64)
            let alignment = SermonAudioAlignment(fingerprintUrl: "/alignment/\(hash)-fingerprint.json", fingerprintSha256: hash,
                sourceId: "source", referenceAudioSha256: hash, referenceDurationSeconds: 300, sourceVideoOffsetSeconds: 1700, trackSha256: hash)
            let track = SermonTrack(id: "track", label: "Candidate", voiceLabel: "Voice", audioUrl: "/media/test.mp3", file: "test.mp3",
                sha256: hash, durationSeconds: 300, cues: [], subtitleTiming: "source_video_aligned_candidate", scope: "full_candidate", alignment: published ? nil : alignment)
            var week = SermonWeek(id: "2026-09-06", date: "2026-09-06", sourceId: "source", sourceUrl: "https://example.test/source",
                title: "Synthetic", speaker: "Speaker", scripture: "", tracks: [track], videoSynchronization: "candidate_aligned",
                humanApproval: .bool(false), candidateEvidence: .object(["syncMp3Sha256": .string(hash)]))
            var publishedLoader: AudioAlignmentController.PublishedIndexLoader?
            if published {
                var doc = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(week)) as? [String: Any])
                doc["sourceSha256"] = hash
                doc["sourceStartSeconds"] = 1700
                doc["sourceEndSeconds"] = 2000
                doc["audioFingerprint"] = [
                    "schemaVersion": "sermon-audio-fingerprint-binding-v1", "pageId": week.id,
                    "sourceSha256": hash, "trackSha256": hash,
                    "sourceStartSeconds": 1700, "sourceEndSeconds": 2000,
                    "algorithmVersion": "spectral-landmarks-v1", "captureSeconds": 10,
                    "indexSha256": hash, "indexUrl": "/fingerprints/\(hash.prefix(16))-landmarks.json"
                ] as [String: Any]
                week = try JSONDecoder().decode(SermonWeek.self, from: JSONSerialization.data(withJSONObject: doc))
                let indexData = try JSONSerialization.data(withJSONObject: [
                    "schemaVersion": "sermon-landmark-index-v1", "algorithmVersion": "spectral-landmarks-v1",
                    "sampleRate": 8000, "hopSize": 256, "fftSize": 1024,
                    "sourceSha256": hash, "trackSha256": hash, "pageId": week.id,
                    "sourceStartSeconds": 1700, "sourceEndSeconds": 2000,
                    "window": ["startSeconds": 1700, "endSeconds": 2000], "durationSeconds": 300,
                    "landmarkCount": 1, "postings": ["1": [0]]
                ])
                let publishedIndex = try PublishedFingerprintIndex.decode(indexData)
                try publishedIndex.validate(binding: XCTUnwrap(week.audioFingerprint))
                publishedLoader = { _ in
                    if let publishedLoadGate { _ = await publishedLoadGate.result() }
                    return publishedIndex
                }
                capture.samples = [Float](repeating: 0, count: 80_000)
            }
            selection = .init(week: week, track: track)
            let algorithm = try JSONSerialization.jsonObject(with: JSONEncoder().encode(FingerprintAlgorithm.supported))
            let indexData = try JSONSerialization.data(withJSONObject: [
                "schemaVersion": "sermon-audio-fingerprint-v1", "durationSeconds": 300, "algorithm": algorithm,
                "landmarkCount": 0, "pairCount": 0, "encoding": "u32le-pairs-base64", "postings": "", "method": "spectral-landmarks-v1",
                "source": ["sourceId": "source", "referenceAudioSha256": hash, "sourceVideoOffsetSeconds": 1700,
                           "timeOrigin": "approved_sermon_clip_start", "timeline": "source_clip", "reviewState": "candidate"]
            ])
            let index = try FingerprintIndex.decode(indexData)
            player.isPlaying = playing; player.alignmentPlaybackIntent = playing
            capture.start = start
            controller = AudioAlignmentController(playback: player, capture: capture, getSelection: { [weak self] in self?.selection },
                loadIndex: { _ in index }, loadPublishedIndex: publishedLoader, match: matcher ?? { _, _ in result }, now: { [weak self] in
                    self!.start.advanced(by: .seconds(self!.elapsed))
                }, deadline: deadline, matchBudget: matchBudget, onState: { [weak self] status, _, position in self?.status = status; self?.resultPosition = position },
                onFailure: { [weak self] message in self?.failures.append(message) },
                onPhase: { [weak self] phase in self?.phases.append(phase) })
        }
    }

    @MainActor
    private final class FakePlayback: AlignmentPlayback {
        var alignmentRevision = UUID()
        var alignmentPlaybackIntent = false
        var isReady = true
        var isPlaying = false
        var isWaiting = false
        var position = 12.0
        var duration = 300.0
        var seeks: [Double] = []
        var resumes = 0
        var onResume: (() -> Void)?
        func pauseForAlignment() { isPlaying = false; alignmentPlaybackIntent = false }
        func resumeAfterAlignment() { resumes += 1; isPlaying = true; alignmentPlaybackIntent = true; onResume?() }
        func applyAlignedPosition(_ value: Double) async -> Bool { seeks.append(value); position = value; return true }
        func cancelAlignmentSeek() {}
    }

    @MainActor
    private final class FakeSession: ContinuousCaptureSessionProtocol {
        var startedAt = ContinuousClock.now
        var samples: [Float] = []
        var waitError: Error?
        var terminalAfterMatch: Error?
        var maxWaitedSeconds: Double = 0
        var cancels = 0
        var waitHook: (() async throws -> Void)?
        weak var capture: FakeCapture?

        var accumulatedSeconds: Double { Double(samples.count) / 8000 }
        var isFinished: Bool { false }

        func waitUntil(seconds: Double) async throws {
            maxWaitedSeconds = max(maxWaitedSeconds, seconds)
            if seconds == 0, let terminalAfterMatch { throw terminalAfterMatch }
            try await waitHook?()
            if let waitError { throw waitError }
        }

        func snapshot() -> CapturedAudio? {
            let count = Int(maxWaitedSeconds * 8000)
            let prefix = Array(samples.prefix(count)) + [Float](repeating: 0, count: max(0, count - samples.count))
            return CapturedAudio(samples: prefix, sampleRate: 8000, startedAt: startedAt)
        }

        func cancel() {
            guard cancels == 0 else { return }
            cancels += 1
            capture?.stops += 1
        }
    }

    /// Sendable call counter for @Sendable matcher stubs.
    private final class CallCounter: Sendable {
        private let lock = NSLock()
        private var _count = 0
        var count: Int { lock.lock(); defer { lock.unlock() }; return _count }
        func increment() { lock.lock(); defer { lock.unlock() }; _count += 1 }
    }

    @MainActor
    private final class FakeCapture: MicrophoneCapturing {
        var onCaptureStarted: (() -> Void)?
        var start = ContinuousClock.now
        var failure: Error?
        var calls = 0
        var stops = 0
        var requestedSeconds: [Double] = []
        var requestedMaxSeconds: [Double] = []
        var samples: [Float] = []
        var session: FakeSession?
        var checkpointWait: (() async throws -> Void)?
        var terminalAfterMatch: Error?
        func capture(seconds: Double) async throws -> CapturedAudio {
            calls += 1
            requestedSeconds.append(seconds)
            if let failure { throw failure }
            onCaptureStarted?()
            return CapturedAudio(samples: samples, sampleRate: 8000, startedAt: start)
        }
        func beginContinuousCapture(maxSeconds: Double) async throws -> any ContinuousCaptureSessionProtocol {
            calls += 1
            requestedMaxSeconds.append(maxSeconds)
            if let failure { throw failure }
            let s = FakeSession()
            s.startedAt = start
            s.samples = samples
            s.capture = self
            s.waitHook = checkpointWait
            s.terminalAfterMatch = terminalAfterMatch
            session = s
            onCaptureStarted?()
            return s
        }
        func cancel() { stops += 1; session?.cancel() }
    }

    private actor ResultGate {
        private var waiting: CheckedContinuation<FingerprintMatchResult, Never>?
        private var stored: FingerprintMatchResult?
        private var started = false
        func result() async -> FingerprintMatchResult {
            started = true
            if let stored { return stored }
            return await withCheckedContinuation { waiting = $0 }
        }
        func finish(_ value: FingerprintMatchResult) { stored = value; waiting?.resume(returning: value); waiting = nil }
        func waitUntilStarted() async throws {
            while !started { try await Task.sleep(for: .milliseconds(5)) }
        }
    }
}

/// All requests are served from frozen JSON or fail locally. Audio is never
/// downloaded; this harness validates selection and reader state, not playback.
private final class CandidateAppModelProtocol: URLProtocol {
    static var fixtureRoot: URL?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url else { client?.urlProtocol(self, didFailWithError: URLError(.badURL)); return }
        let bytes = url.pathExtension == "json" ? Self.fixtureRoot.flatMap {
            try? Data(contentsOf: $0.appendingPathComponent(String(url.path.dropFirst())))
        } : nil
        let response = HTTPURLResponse(url: url, statusCode: bytes == nil ? 404 : 200, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if let bytes { client?.urlProtocol(self, didLoad: bytes) }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}
