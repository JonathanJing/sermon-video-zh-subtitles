import AVFoundation
import CoreVideo
import CryptoKit
import Foundation
import XCTest
@testable import Tongxing

final class VoiceDemoCatalogV2Tests: XCTestCase {
    private func digest(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func fixture() -> [String: Any] {
        let speakers: [[String: Any]] = (0..<6).map { index in
            let id = "speaker_\(index)"
            let clip = "\(id)_clip"
            let text = "Frozen English source \(index)."
            let textHash = digest(text)
            func asset(_ filename: String) -> [String: Any] {
                ["path": "/voice-demos/speaker-clips-v2/\(id)/\(filename)",
                 "sha256": String(repeating: "a", count: 64), "bytes": 100,
                 "sourceClipId": clip, "durationSeconds": 12.0]
            }
            var original = asset("en-original.mp3")
            original["text"] = text
            original["locale"] = "en"
            original["englishTextSha256"] = textHash
            original["transcriptStatus"] = "machine_screening_only"
            let samples = ["zh-Hans", "ko", "es"].map { locale in
                var sample = asset("\(locale).mp3")
                sample["text"] = "Synthetic translation \(locale)."
                sample["locale"] = locale
                sample["englishTextSha256"] = textHash
                sample["humanListeningStatus"] = "pending"
                return sample
            }
            return ["speakerId": id, "displayName": "Synthetic speaker \(index)", "clipId": clip,
                    "source": ["url": "https://example.test/watch?v=\(index)",
                               "startSeconds": 10.0, "endSeconds": 22.0,
                               "englishTextSha256": textHash],
                    "original": original, "video": asset("source.mp4"), "samples": samples]
        }
        return ["schemaVersion": "sermon-speaker-clip-demo-catalog-v2",
                "status": "audition_demo",
                "sourceScope": "source_clip_translation_audition_not_sermon_release",
                "humanListeningStatus": "pending", "speakerCount": 6, "sampleCount": 18,
                "speakers": speakers]
    }

    private func encode(_ object: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: object)
    }

    private func changingFirstSpeaker(_ body: (inout [String: Any]) -> Void) -> [String: Any] {
        var value = fixture()
        var speakers = value["speakers"] as! [[String: Any]]
        body(&speakers[0])
        value["speakers"] = speakers
        return value
    }

    func testMatchedClipCatalogHasThreeLanguagesAndVideoWithoutText() throws {
        let catalog = try VoiceDemoCatalog.validatedClips(encode(fixture()))
        XCTAssertTrue(catalog.isSourceMatched)
        XCTAssertFalse(catalog.isProductionMerged)
        XCTAssertEqual(catalog.sampleCount, 18)
        XCTAssertEqual(catalog.speakers[0].samples.map(\.locale), ["zh-Hans", "ko", "es"])
        XCTAssertEqual(catalog.speakers[0].video?.text, "")
        XCTAssertEqual(catalog.speakers[0].source?.startSeconds, 10)
        XCTAssertThrowsError(try VoiceDemoCatalog.validated(encode(fixture())))
    }

    func testRejectsCrossClipAssetAndChangedEnglishManuscript() throws {
        let crossClip = changingFirstSpeaker { speaker in
            var samples = speaker["samples"] as! [[String: Any]]
            samples[0]["sourceClipId"] = "speaker_1_clip"
            speaker["samples"] = samples
        }
        XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(crossClip)))
        let changedEnglish = changingFirstSpeaker { speaker in
            var original = speaker["original"] as! [String: Any]
            original["text"] = "Different source sentence."
            speaker["original"] = original
        }
        XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(changedEnglish)))
        let crossText = changingFirstSpeaker { speaker in
            var samples = speaker["samples"] as! [[String: Any]]
            samples[0]["englishTextSha256"] = String(repeating: "b", count: 64)
            speaker["samples"] = samples
        }
        XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(crossText)))
    }

    func testRejectsVideoMismatchUnsafePathsAndOversizedAssets() throws {
        for field in ["path", "durationSeconds", "bytes", "sourceClipId"] {
            let invalid = changingFirstSpeaker { speaker in
                var video = speaker["video"] as! [String: Any]
                switch field {
                case "path": video[field] = "/voice-demos/speaker-clips-v2/../secret.mp4"
                case "durationSeconds": video[field] = 13.0
                case "bytes": video[field] = 20_000_001
                default: video[field] = "another_clip"
                }
                speaker["video"] = video
            }
            XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(invalid)), field)
        }
        let invalidAudio = changingFirstSpeaker { speaker in
            var original = speaker["original"] as! [String: Any]
            original["bytes"] = 5_000_001
            speaker["original"] = original
        }
        XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(invalidAudio)))
        let percentEscape = changingFirstSpeaker { speaker in
            var video = speaker["video"] as! [String: Any]
            video["path"] = "/voice-demos/speaker-clips-v2/%2e%2e/source.mp4"
            speaker["video"] = video
        }
        XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(percentEscape)))
    }

    func testRejectsDuplicateLocalesPromotedReviewAndInvalidWindow() throws {
        let duplicate = changingFirstSpeaker { speaker in
            var samples = speaker["samples"] as! [[String: Any]]
            samples[1]["locale"] = "zh-Hans"
            speaker["samples"] = samples
        }
        XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(duplicate)))
        var promoted = fixture()
        promoted["humanListeningStatus"] = "accepted"
        XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(promoted)))
        let window = changingFirstSpeaker { speaker in
            var source = speaker["source"] as! [String: Any]
            source["endSeconds"] = 100.0
            speaker["source"] = source
        }
        XCTAssertThrowsError(try VoiceDemoCatalog.validatedClips(encode(window)))
    }

    func testVideoByteVerificationRetainsHashAndExactSizeCheck() throws {
        let data = Data("synthetic MP4 bytes; not a playable media fixture".utf8)
        let asset = VoiceDemoCatalog.Asset(path: "/voice-demos/speaker-clips-v2/source.mp4",
            sha256: digest(String(decoding: data, as: UTF8.self)), bytes: data.count, text: "",
            transcriptStatus: nil, humanListeningStatus: nil, sourceUrl: nil, locale: nil)
        XCTAssertNoThrow(try asset.verify(data))
        XCTAssertThrowsError(try asset.verify(data + Data([0])))
    }

    func testVideoUsesTwentyMegabyteLimitWhileAudioRetainsFiveMegabyteLimit() throws {
        let data = Data(repeating: 0, count: 5_000_001)
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let video = VoiceDemoCatalog.Asset(path: "/voice-demos/speaker-clips-v2/source.mp4",
            sha256: hash, bytes: data.count, text: "", transcriptStatus: nil,
            humanListeningStatus: nil, sourceUrl: nil, locale: nil)
        let audio = VoiceDemoCatalog.Asset(path: "/voice-demos/speaker-clips-v2/source.mp3",
            sha256: hash, bytes: data.count, text: "", transcriptStatus: nil,
            humanListeningStatus: nil, sourceUrl: nil, locale: nil)
        XCTAssertNoThrow(try video.verify(data))
        XCTAssertThrowsError(try audio.verify(data))
    }

    /// Explicit network/video evidence for the same frozen Dev clip used by the live UI smoke.
    /// This verifies a decoded frame and transport progress, not human listening or venue QA.
    @MainActor
    func testLiveDevEricVideoHashDecodePlayAndPause() async throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TONGXING_LIVE_DEMO"] == "1",
                          "Opt in with TONGXING_LIVE_DEMO=1 to verify the real Firebase Dev video.")
        let origin = URL(string: "https://ai-for-god-sermon-audio-dev.web.app")!
        let frozenCatalogSHA = "ea3723eb3f10003db06d09fa81eed473fac17aaa3b8ec32bea29cfee04de25a2"
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 15
        configuration.timeoutIntervalForResource = 20
        let session = URLSession(configuration: configuration)
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("Tongxing-Live-Demo-\(UUID().uuidString)", isDirectory: true)
        var player: AVPlayer?
        defer {
            player?.pause()
            player?.replaceCurrentItem(with: nil)
            session.invalidateAndCancel()
            try? FileManager.default.removeItem(at: directory)
        }

        let catalogURL = origin.appendingPathComponent(VoiceDemoCatalog.clipsRelativePath)
        var request = URLRequest(url: catalogURL)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 15
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200,
              response.url == catalogURL, !data.isEmpty, data.count < 2_000_000 else {
            throw LiveVideoFailure.invalidCatalogResponse
        }
        let catalogSHA = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard catalogSHA == frozenCatalogSHA else {
            XCTFail("Firebase Dev catalog differs from the explicitly frozen demo revision.")
            throw LiveVideoFailure.catalogChanged
        }
        let catalog = try VoiceDemoCatalog.validatedClips(data)
        let speaker = try XCTUnwrap(catalog.speakers.first { $0.speakerId == "eric_geiger" })
        let video = try XCTUnwrap(speaker.video)
        let source = try XCTUnwrap(speaker.source)
        let file = try await video.verifiedLocalURL(origin: origin, session: session, directory: directory)
        // Reverify the downloaded cache file before constructing AVPlayer, just as the app does.
        try video.verify(Data(contentsOf: file))
        let asset = AVURLAsset(url: file)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        let track = try XCTUnwrap(tracks.first, "The published MP4 must contain an actual video track.")
        let size = try await track.load(.naturalSize)
        XCTAssertGreaterThan(size.width, 0)
        XCTAssertGreaterThan(size.height, 0)
        let measuredDuration = try await asset.load(.duration).seconds
        XCTAssertTrue(measuredDuration.isFinite)
        XCTAssertGreaterThan(measuredDuration, 1)
        XCTAssertEqual(measuredDuration, try XCTUnwrap(video.durationSeconds), accuracy: 0.5)
        XCTAssertEqual(measuredDuration, source.endSeconds - source.startSeconds, accuracy: 0.5)

        let output = AVPlayerItemVideoOutput(pixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        ])
        let item = AVPlayerItem(asset: asset)
        item.add(output)
        let livePlayer = AVPlayer(playerItem: item)
        player = livePlayer
        try await waitForLiveVideo("AVPlayer item ready") {
            guard item.status != .failed else { throw LiveVideoFailure.playerFailed }
            return item.status == .readyToPlay
        }
        try await SystemAudioSessionActivator.shared.activate()
        livePlayer.play()
        try await waitForLiveVideo("video advanced beyond one second") {
            guard item.status != .failed else { throw LiveVideoFailure.playerFailed }
            let time = livePlayer.currentTime().seconds
            return time.isFinite && time > 1
        }
        var frame: CVPixelBuffer?
        try await waitForLiveVideo("actual decoded video frame") {
            frame = output.copyPixelBuffer(forItemTime: livePlayer.currentTime(), itemTimeForDisplay: nil)
            return frame != nil
        }
        let decoded = try XCTUnwrap(frame)
        XCTAssertGreaterThan(CVPixelBufferGetWidth(decoded), 0)
        XCTAssertGreaterThan(CVPixelBufferGetHeight(decoded), 0)
        let playedTo = livePlayer.currentTime().seconds
        livePlayer.pause()
        try await Task.sleep(nanoseconds: 250_000_000)
        let pausedAt = livePlayer.currentTime().seconds
        try await Task.sleep(nanoseconds: 1_000_000_000)
        let pausedLater = livePlayer.currentTime().seconds
        XCTAssertEqual(livePlayer.rate, 0)
        XCTAssertEqual(pausedLater, pausedAt, accuracy: 0.15,
                       "The real video timeline must remain stopped after pause.")

        let receipt: [String: Any] = [
            "origin": origin.absoluteString, "catalogSha256": catalogSHA,
            "speakerId": speaker.speakerId, "clipId": try XCTUnwrap(speaker.clipId),
            "videoSha256": video.sha256, "videoBytes": try XCTUnwrap(video.bytes),
            "measuredDurationSeconds": measuredDuration, "playedToSeconds": playedTo,
            "decodedFrameWidth": CVPixelBufferGetWidth(decoded),
            "decodedFrameHeight": CVPixelBufferGetHeight(decoded),
            "pausedTimelineDeltaSeconds": abs(pausedLater - pausedAt),
        ]
        let attachment = XCTAttachment(string: String(decoding:
            try JSONSerialization.data(withJSONObject: receipt, options: [.sortedKeys]), as: UTF8.self))
        attachment.name = "live-dev-eric-video-hash-decode-play-pause"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    private func waitForLiveVideo(_ description: String,
                                  _ condition: @MainActor () throws -> Bool) async throws {
        let deadline = Date().addingTimeInterval(20)
        while try !condition() {
            guard Date() < deadline else { throw LiveVideoFailure.timeout(description) }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
    }

    private enum LiveVideoFailure: Error {
        case invalidCatalogResponse, catalogChanged, playerFailed, timeout(String)
    }

}
