import AVFoundation
import CryptoKit
import Foundation
import MediaPlayer
import TongxingCore
import XCTest
@testable import Tongxing

/// Hosted iOS integration tests use generated silence and private temporary state.
/// Posted audio-session notifications verify application control flow; they do
/// not represent a real phone call, headphone route, lock-screen or venue test.
@MainActor
final class PlaybackControllerTests: XCTestCase {
    func testSelectingSameIdentityPreservesPositionAndOffset() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        try await fixture.load()
        fixture.player.jump(to: 4)
        try await eventually("initial position") { abs(fixture.player.position - 4) < 0.1 }
        fixture.player.nudge(1)
        try await eventually("adjusted position") { abs(fixture.player.position - 5) < 0.1 }

        let renamed = fixture.week(title: "Updated synthetic title")
        fixture.player.load(week: renamed, track: fixture.track, url: fixture.audioURL)

        XCTAssertTrue(fixture.player.isReady)
        XCTAssertEqual(fixture.player.position, 5, accuracy: 0.1)
        XCTAssertEqual(fixture.player.offset, 1, accuracy: 0.01)
        XCTAssertEqual(MPNowPlayingInfoCenter.default().nowPlayingInfo?[MPMediaItemPropertyTitle] as? String,
                       "Updated synthetic title")
    }

    func testChangedSourceDoesNotRestoreOldBookmarkWithIdenticalAudioHash() async throws {
        let fixture = try Fixture(bookmark: (6, 0.75))
        defer { fixture.dispose() }
        try await fixture.load()
        XCTAssertEqual(try XCTUnwrap(fixture.player.resumePosition).position, 6, accuracy: 0.1)

        fixture.player.load(week: fixture.week(sourceID: "different-source"),
                            track: fixture.track, url: fixture.audioURL)
        try await eventually("replacement source ready") { fixture.player.isReady }

        XCTAssertNil(fixture.player.resumePosition)
        XCTAssertEqual(fixture.player.position, 0, accuracy: 0.1)
        XCTAssertEqual(fixture.player.offset, 0)
        XCTAssertFalse(fixture.player.isPlaying)
    }

    func testOldPendingSeekCannotOverwriteNewTrackBookmark() async throws {
        let fixture = try Fixture(bookmark: (6, 0.75), bookmarkTrackID: "different-track")
        defer { fixture.dispose() }
        try await fixture.load()
        let otherTrack = fixture.makeTrack(id: "different-track")

        // Both requests occur before any MainActor seek completion can run.
        fixture.player.jump(to: 7)
        fixture.player.load(week: fixture.week(track: otherTrack), track: otherTrack, url: fixture.audioURL)
        try await eventually("new track ready") { fixture.player.isReady }
        try await settleCallbacks()

        XCTAssertEqual(fixture.player.position, 0, accuracy: 0.1)
        XCTAssertEqual(fixture.player.offset, 0)
        XCTAssertEqual(try XCTUnwrap(fixture.player.resumePosition).position, 6, accuracy: 0.1)
        XCTAssertNil(fixture.player.undoPosition)
        XCTAssertFalse(fixture.player.isPlaying)
    }

    func testPauseDuringPendingRestorePreventsAutoplay() async throws {
        let fixture = try Fixture(bookmark: (6, 0.75))
        defer { fixture.dispose() }
        try await fixture.load()

        fixture.player.play()
        fixture.player.pause()
        try await eventually("restore completes while paused") {
            fixture.player.resumePosition == nil && abs(fixture.player.position - 6) < 0.1
        }
        try await settleCallbacks()

        XCTAssertFalse(fixture.player.isPlaying)
        XCTAssertFalse(fixture.player.isWaiting)
        XCTAssertEqual(fixture.player.offset, 0.75, accuracy: 0.01)
        let saved = try fixture.savedPosition()
        XCTAssertEqual(saved.position, 6, accuracy: 0.1)
        XCTAssertEqual(saved.offset, 0.75, accuracy: 0.01)
    }

    func testNudgeDuringPendingRestoreKeepsRequestedPlayback() async throws {
        let fixture = try Fixture(bookmark: (6, 0.75))
        defer { fixture.dispose() }
        try await fixture.load()

        fixture.player.play()
        fixture.player.nudge(1)
        try await eventually("adjusted restore starts playback") { fixture.player.isPlaying }
        fixture.player.pause()

        XCTAssertEqual(fixture.player.position, 7, accuracy: 0.5)
        XCTAssertEqual(fixture.player.offset, 1.75, accuracy: 0.01)
        XCTAssertNil(fixture.player.resumePosition)
    }

    func testPlayHonorsPendingRestartInsteadOfOlderResumeCard() async throws {
        let fixture = try Fixture(bookmark: (6, 0.75))
        defer { fixture.dispose() }
        try await fixture.load()

        fixture.player.restart()
        fixture.player.play()
        try await eventually("play starts at requested beginning") { fixture.player.isPlaying }
        fixture.player.pause()

        XCTAssertLessThan(fixture.player.position, 1)
        XCTAssertEqual(fixture.player.offset, 0)
        XCTAssertNil(fixture.player.resumePosition)
    }

    func testRapidNudgesAndUndoPreserveLatestPositionAndOffset() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        try await fixture.load()
        fixture.player.jump(to: 4)
        try await eventually("initial jump") { abs(fixture.player.position - 4) < 0.1 }

        fixture.player.nudge(1)
        fixture.player.nudge(1)
        fixture.player.nudge(-0.25)
        try await eventually("combined adjustments") { abs(fixture.player.position - 5.75) < 0.1 }
        XCTAssertEqual(fixture.player.offset, 1.75, accuracy: 0.01)

        fixture.player.undo()
        try await eventually("last adjustment undone") { abs(fixture.player.position - 6) < 0.1 }
        XCTAssertEqual(fixture.player.offset, 2, accuracy: 0.01)
        XCTAssertNil(fixture.player.undoPosition)
    }

    func testCumulativeOffsetRemainsAdmissibleToPersistedHistory() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        try await fixture.load()
        fixture.player.nudge(10)
        try await eventually("large adjustment") { abs(fixture.player.position - 10) < 0.1 }
        fixture.player.jump(to: 1)
        try await eventually("absolute jump retains adjustment") { abs(fixture.player.position - 1) < 0.1 }
        fixture.player.nudge(5)
        try await eventually("position after cumulative adjustment") { abs(fixture.player.position - 6) < 0.1 }

        let saved = try fixture.savedPosition()
        XCTAssertEqual(saved.position, 6, accuracy: 0.1)
        XCTAssertEqual(saved.offset, fixture.player.duration, accuracy: 0.01)
    }

    func testSyntheticMediaResetRetainsActualLocalURLAndWaitsForUser() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        try await fixture.load()
        fixture.player.jump(to: 5)
        try await eventually("saved reset position") { abs(fixture.player.position - 5) < 0.1 }

        // Same-identity metadata updates must retain the actual loaded audio URL.
        let missingURL = fixture.directory.appendingPathComponent("does-not-exist.wav")
        fixture.player.load(week: fixture.week(title: "Updated metadata"), track: fixture.track, url: missingURL)
        NotificationCenter.default.post(name: AVAudioSession.mediaServicesWereResetNotification, object: nil)
        try await eventually("local source rebuilt after synthetic reset") {
            fixture.player.isReady && fixture.player.resumePosition != nil
        }

        XCTAssertFalse(fixture.player.isPlaying)
        XCTAssertFalse(fixture.player.isWaiting)
        XCTAssertEqual(try XCTUnwrap(fixture.player.resumePosition).position, 5, accuracy: 0.1)
    }

    func testUserPauseDuringSyntheticInterruptionPreventsSystemResume() async throws {
        let fixture = try Fixture()
        defer { fixture.dispose() }
        try await fixture.load()
        fixture.player.jump(to: 4)
        try await eventually("interruption test start position") { abs(fixture.player.position - 4) < 0.1 }
        fixture.player.play()
        try await eventually("audio playing before synthetic interruption") { fixture.player.isPlaying }

        NotificationCenter.default.post(name: AVAudioSession.interruptionNotification, object: nil,
            userInfo: [AVAudioSessionInterruptionTypeKey: AVAudioSession.InterruptionType.began.rawValue])
        try await eventually("synthetic interruption handled") { fixture.player.message.contains("系统中断") }
        fixture.player.pause()
        NotificationCenter.default.post(name: AVAudioSession.interruptionNotification, object: nil,
            userInfo: [
                AVAudioSessionInterruptionTypeKey: AVAudioSession.InterruptionType.ended.rawValue,
                AVAudioSessionInterruptionOptionKey: AVAudioSession.InterruptionOptions.shouldResume.rawValue,
            ])
        try await settleCallbacks()

        XCTAssertFalse(fixture.player.isPlaying)
        XCTAssertFalse(fixture.player.isWaiting)
        XCTAssertEqual(try fixture.savedPosition().position, fixture.player.position, accuracy: 0.5)
    }

    func testPauseWhileSessionActivationIsPendingPreventsLatePlayback() async throws {
        let activation = DelayedAudioSessionActivator()
        addTeardownBlock { await activation.cancelAll() }
        let fixture = try Fixture(audioSessionActivator: activation)
        defer { fixture.dispose() }
        try await fixture.load()
        fixture.player.jump(to: 4)
        try await eventually("activation test position") { abs(fixture.player.position - 4) < 0.1 }

        fixture.player.play()
        try await waitForActivationRequests(activation, count: 1)
        XCTAssertTrue(fixture.player.isWaiting)
        fixture.player.pause()
        try await activation.succeed(0)
        try await settleCallbacks()

        XCTAssertFalse(fixture.player.isPlaying)
        XCTAssertFalse(fixture.player.isWaiting)
        XCTAssertEqual(fixture.player.position, 4, accuracy: 0.1)
    }

    func testOlderActivationFailureCannotClearNewPlayRequest() async throws {
        let activation = DelayedAudioSessionActivator()
        addTeardownBlock { await activation.cancelAll() }
        let fixture = try Fixture(audioSessionActivator: activation)
        defer { fixture.dispose() }
        try await fixture.load()

        fixture.player.play()
        try await waitForActivationRequests(activation, count: 1)
        fixture.player.pause()
        fixture.player.play()
        try await waitForActivationRequests(activation, count: 2)
        try await activation.fail(0)
        try await settleCallbacks()
        XCTAssertTrue(fixture.player.isWaiting)
        XCTAssertFalse(fixture.player.message.contains("无法启用"))

        try await activation.succeed(1)
        try await eventually("new request still starts playback") { fixture.player.isPlaying }
        fixture.player.pause()
    }

    func testLateActivationForPreviousSourceCannotStartNewSource() async throws {
        let activation = DelayedAudioSessionActivator()
        addTeardownBlock { await activation.cancelAll() }
        let fixture = try Fixture(audioSessionActivator: activation)
        defer { fixture.dispose() }
        try await fixture.load()

        fixture.player.play()
        try await waitForActivationRequests(activation, count: 1)
        fixture.player.load(week: fixture.week(sourceID: "replacement-source"),
                            track: fixture.track, url: fixture.audioURL)
        try await eventually("replacement source preparation") { fixture.player.isReady }
        fixture.player.play()
        try await waitForActivationRequests(activation, count: 2)

        try await activation.succeed(0)
        try await settleCallbacks()
        XCTAssertFalse(fixture.player.isPlaying)
        XCTAssertTrue(fixture.player.isWaiting)
        XCTAssertEqual(fixture.player.position, 0, accuracy: 0.1)

        try await activation.succeed(1)
        try await eventually("replacement source activation") { fixture.player.isPlaying }
        fixture.player.pause()
    }

    func testRepeatedPlayAndSeekSharePendingSessionActivation() async throws {
        let activation = DelayedAudioSessionActivator()
        addTeardownBlock { await activation.cancelAll() }
        let fixture = try Fixture(audioSessionActivator: activation)
        defer { fixture.dispose() }
        try await fixture.load()
        fixture.player.jump(to: 4)
        try await eventually("shared activation start position") { abs(fixture.player.position - 4) < 0.1 }

        fixture.player.play()
        try await waitForActivationRequests(activation, count: 1)
        fixture.player.play()
        fixture.player.nudge(1)
        try await eventually("position changes while session is pending") { abs(fixture.player.position - 5) < 0.1 }
        let requests = await activation.requestCount
        XCTAssertEqual(requests, 1)

        try await activation.succeed(0)
        try await eventually("shared activation completes") { fixture.player.isPlaying }
        fixture.player.pause()
        XCTAssertEqual(fixture.player.position, 5, accuracy: 0.5)
    }

    func testInterruptionWithoutResumeReleasesPendingActivationForNextPlay() async throws {
        let activation = DelayedAudioSessionActivator()
        addTeardownBlock { await activation.cancelAll() }
        let fixture = try Fixture(audioSessionActivator: activation)
        defer { fixture.dispose() }
        try await fixture.load()
        fixture.player.play()
        try await waitForActivationRequests(activation, count: 1)

        NotificationCenter.default.post(name: AVAudioSession.interruptionNotification, object: nil,
            userInfo: [AVAudioSessionInterruptionTypeKey: AVAudioSession.InterruptionType.began.rawValue])
        try await eventually("activation interrupted") { fixture.player.message.contains("系统中断") }
        fixture.player.play()
        try await waitForActivationRequests(activation, count: 2)
        NotificationCenter.default.post(name: AVAudioSession.interruptionNotification, object: nil,
            userInfo: [AVAudioSessionInterruptionTypeKey: AVAudioSession.InterruptionType.ended.rawValue])
        try await settleCallbacks()
        try await activation.fail(0)
        try await activation.fail(1)
        try await settleCallbacks()
        XCTAssertFalse(fixture.player.isPlaying)
        XCTAssertFalse(fixture.player.isWaiting)

        fixture.player.play()
        try await waitForActivationRequests(activation, count: 3)
        try await activation.succeed(2)
        try await eventually("new play after interruption") { fixture.player.isPlaying }
        fixture.player.pause()
    }

    private func waitForActivationRequests(_ activation: DelayedAudioSessionActivator, count: Int) async throws {
        let deadline = Date().addingTimeInterval(10)
        while await activation.requestCount < count {
            guard Date() < deadline else { throw TestFailure.timeout("expected audio-session activation request") }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
    }

    private func eventually(_ description: String, timeout: TimeInterval = 10,
                            _ predicate: @MainActor () -> Bool) async throws {
        let deadline = Date().addingTimeInterval(timeout)
        while !predicate() {
            guard Date() < deadline else { throw TestFailure.timeout(description) }
            try await Task.sleep(nanoseconds: 20_000_000)
        }
    }

    private func settleCallbacks() async throws {
        try await Task.sleep(nanoseconds: 250_000_000)
    }

    private enum TestFailure: Error { case timeout(String) }

    @MainActor
    private final class Fixture {
        let directory: URL
        let audioURL: URL
        let historyURL: URL
        let sha256: String
        let player: PlaybackController
        let duration = 12.0
        var track: SermonTrack { makeTrack(id: "synthetic-track") }

        init(bookmark: (position: Double, offset: Double)? = nil, bookmarkTrackID: String = "synthetic-track",
             audioSessionActivator: any AudioSessionActivating = SystemAudioSessionActivator.shared) throws {
            directory = FileManager.default.temporaryDirectory.appendingPathComponent("TongxingPlaybackTests-\(UUID().uuidString)")
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            audioURL = directory.appendingPathComponent("silence.wav")
            historyURL = directory.appendingPathComponent("history.json")
            let wave = Self.makeSilence(duration: 12, sampleRate: 8_000)
            sha256 = SHA256.hash(data: wave).map { String(format: "%02x", $0) }.joined()
            try wave.write(to: audioURL, options: .atomic)
            if let bookmark {
                var history = PlaybackHistory()
                history.record(identity: TrackIdentity(weekID: "2026-09-05", trackID: bookmarkTrackID, audioSHA256: sha256),
                               sourceID: "synthetic-source", position: bookmark.position, offset: bookmark.offset, duration: 12)
                try history.encoded().write(to: historyURL, options: .atomic)
            }
            player = PlaybackController(historyURL: historyURL, audioSessionActivator: audioSessionActivator)
        }

        func load() async throws {
            player.load(week: week(), track: track, url: audioURL)
            let deadline = Date().addingTimeInterval(10)
            while !player.isReady {
                guard Date() < deadline else { throw TestFailure.timeout("synthetic local WAV preparation: \(player.message)") }
                try await Task.sleep(nanoseconds: 20_000_000)
            }
        }

        func week(sourceID: String = "synthetic-source", title: String = "Synthetic sermon", track: SermonTrack? = nil) -> SermonWeek {
            SermonWeek(id: "2026-09-05", date: "2026-09-05", sourceId: sourceID,
                       sourceUrl: "https://example.org/\(sourceID)", title: title, speaker: "Synthetic speaker",
                       scripture: "Synthetic reference", tracks: [track ?? self.track])
        }

        func makeTrack(id: String) -> SermonTrack {
            SermonTrack(id: id, label: "Synthetic silence", voiceLabel: "No real voice",
                        audioUrl: "/media/silence.wav", file: "silence.wav", sha256: sha256,
                        durationSeconds: duration, cues: [SubtitleCue(start: 0, end: duration, text: "合成测试字幕。")],
                        subtitleTiming: "synthetic_fixture", scope: "synthetic_fixture")
        }

        func savedPosition() throws -> ResumePosition {
            player.saveProgress()
            var history = PlaybackHistory(data: try Data(contentsOf: historyURL))
            return try XCTUnwrap(history.resume(identity: track.identity(weekID: "2026-09-05"),
                                               sourceID: "synthetic-source", duration: duration))
        }

        func dispose() {
            player.clear()
            try? FileManager.default.removeItem(at: directory)
        }

        private static func makeSilence(duration: Int, sampleRate: Int) -> Data {
            let byteCount = UInt32(duration * sampleRate * 2)
            var data = Data()
            func append<T: FixedWidthInteger>(_ value: T) {
                var littleEndian = value.littleEndian
                withUnsafeBytes(of: &littleEndian) { data.append(contentsOf: $0) }
            }
            data.append(contentsOf: "RIFF".utf8)
            append(UInt32(36) + byteCount)
            data.append(contentsOf: "WAVEfmt ".utf8)
            append(UInt32(16)); append(UInt16(1)); append(UInt16(1))
            append(UInt32(sampleRate)); append(UInt32(sampleRate * 2))
            append(UInt16(2)); append(UInt16(16))
            data.append(contentsOf: "data".utf8)
            append(byteCount)
            data.append(Data(count: Int(byteCount)))
            return data
        }
    }

    /// Explicit completion order exercises late callbacks without a timing-based
    /// sleep in the activation implementation. Successful requests still activate
    /// the real iOS session before allowing AVPlayer to play the silent fixture.
    private actor DelayedAudioSessionActivator: AudioSessionActivating {
        private var requests: [CheckedContinuation<Void, Error>?] = []
        var requestCount: Int { requests.count }

        func activate() async throws {
            try await withCheckedThrowingContinuation { requests.append($0) }
        }

        func succeed(_ index: Int) async throws {
            try await SystemAudioSessionActivator.shared.activate()
            try resolve(index, with: .success(()))
        }

        func fail(_ index: Int) throws {
            try resolve(index, with: .failure(NSError(domain: "TongxingSyntheticActivation", code: 1)))
        }

        func cancelAll() {
            for index in requests.indices {
                requests[index]?.resume(throwing: CancellationError())
                requests[index] = nil
            }
        }

        private func resolve(_ index: Int, with result: Result<Void, Error>) throws {
            guard requests.indices.contains(index), let continuation = requests[index] else {
                throw TestFailure.timeout("missing synthetic activation request")
            }
            requests[index] = nil
            continuation.resume(with: result)
        }
    }
}
