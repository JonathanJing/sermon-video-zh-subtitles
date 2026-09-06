import Foundation
import Testing
@testable import TongxingCore

struct PlaybackTests {
    let now = Date(timeIntervalSince1970: 1_788_566_400)
    func identity(_ id: String = "candidate", hash: String = String(repeating: "a", count: 64)) -> TrackIdentity {
        TrackIdentity(weekID: "2026-09-05", trackID: id, audioSHA256: hash)
    }
    func savedHistory() -> PlaybackHistory {
        var history = PlaybackHistory()
        history.record(identity: identity(), sourceID: "source", position: 35.5, offset: -1.2, duration: 120, at: now)
        return history
    }

    @Test func testBookmarkRoundTripRestoresExactPositionAndOffset() throws {
        var history = PlaybackHistory(data: try savedHistory().encoded(), now: now)
        let resumed = history.resume(identity: identity(), sourceID: "source", duration: 120, at: now)
        #expect(resumed?.position == 35.5)
        #expect(resumed?.offset == -1.2)
        #expect(resumed?.savedAt == now)
    }

    @Test func testBookmarkBoundToWeekTrackHashAndSource() {
        var history = savedHistory()
        for other in [identity("other"), identity(hash: String(repeating: "b", count: 64)),
                      TrackIdentity(weekID: "2026-09-04", trackID: "candidate", audioSHA256: String(repeating: "a", count: 64))] {
            #expect(history.resume(identity: other, sourceID: "source", duration: 120, at: now) == nil)
            #expect(other.key != identity().key)
        }
        #expect(history.resume(identity: identity(), sourceID: "changed-source", duration: 120, at: now) == nil)
        #expect(history.resume(identity: identity(), sourceID: "source", duration: 120, at: now) != nil)
    }

    @Test func testTwoSecondBoundariesClearPreviousBookmark() {
        for boundary in [0.0, 1.999, 118, 120] {
            var history = savedHistory()
            let recorded = history.record(identity: identity(), sourceID: "source", position: boundary,
                                          offset: 0, duration: 120, at: now)
            #expect(!recorded)
            #expect(history.entries.isEmpty)
        }
        var history = PlaybackHistory()
        for position in [2.0, 117.999] {
            let recorded = history.record(identity: identity(), sourceID: "source", position: position,
                                          offset: 0, duration: 120, at: now)
            #expect(recorded)
        }
    }

    @Test func testBadValuesDoNotErasePreviousBookmark() {
        var history = savedHistory()
        for badPosition in [-1, 121, .nan, .infinity] {
            let recorded = history.record(identity: identity(), sourceID: "source", position: badPosition,
                                          offset: 0, duration: 120, at: now)
            #expect(!recorded)
        }
        for badOffset in [-121, 121, .nan, .infinity] {
            let recorded = history.record(identity: identity(), sourceID: "source", position: 50,
                                          offset: badOffset, duration: 120, at: now)
            #expect(!recorded)
        }
        let invalidHashRecorded = history.record(identity: identity(hash: "bad"), sourceID: "source", position: 50,
                                                 offset: 0, duration: 120, at: now)
        let invalidClockRecorded = history.record(identity: identity(), sourceID: "source", position: 50,
                                                  offset: 0, duration: 120, at: Date(timeIntervalSince1970: .infinity))
        #expect(!invalidHashRecorded)
        #expect(!invalidClockRecorded)
        #expect(history.entries.count == 1)
        #expect(history.entries.first?.position == 35.5)
    }

    @Test func testChangedDurationCannotRestoreOutsideCurrentTrack() {
        var history = savedHistory()
        #expect(history.resume(identity: identity(), sourceID: "source", duration: 36, at: now) == nil)
        #expect(history.entries.isEmpty)
    }

    @Test func testThirtyDayExpiryAndFutureTimestamp() throws {
        let data = try savedHistory().encoded()
        var beforeExpiry = PlaybackHistory(data: data, now: now.addingTimeInterval(PlaybackHistory.maximumAge - 1))
        #expect(beforeExpiry.resume(identity: identity(), sourceID: "source", duration: 120,
                                           at: now.addingTimeInterval(PlaybackHistory.maximumAge - 1)) != nil)
        #expect(PlaybackHistory(data: data, now: now.addingTimeInterval(PlaybackHistory.maximumAge)).entries.isEmpty)
        #expect(PlaybackHistory(data: data, now: now.addingTimeInterval(-1)).entries.isEmpty)
    }

    @Test func testOnlyTwelveRecentEntriesAndStableTiesRetained() {
        var history = PlaybackHistory()
        for index in 0..<15 {
            history.record(identity: identity("track-\(index)"), sourceID: "source", position: 10,
                           offset: 0, duration: 120, at: now)
        }
        #expect(history.entries.count == 12)
        #expect(history.entries.first?.identity.trackID == "track-14")
        #expect(history.entries.last?.identity.trackID == "track-3")
        history.record(identity: identity("track-3"), sourceID: "source", position: 25, offset: 1, duration: 120, at: now)
        #expect(history.entries.count == 12)
        #expect(history.entries.first?.identity.trackID == "track-3")
    }

    @Test func testMalformedRowsAreIgnoredWithoutLosingValidEntries() throws {
        var object = try #require(JSONSerialization.jsonObject(with: savedHistory().encoded()) as? [String: Any])
        var rows = object["entries"] as! [[String: Any]]
        var damaged = rows[0]
        damaged["position"] = "not-a-number"
        var future = rows[0]
        future["savedAt"] = now.timeIntervalSince1970 + 10
        rows += [damaged, future, ["unrelated": true]]
        object["entries"] = rows
        let history = PlaybackHistory(data: try JSONSerialization.data(withJSONObject: object), now: now)
        #expect(history.entries.count == 1)
        #expect(history.entries.first?.position == 35.5)
        object["schemaVersion"] = 9
        #expect(PlaybackHistory(data: try JSONSerialization.data(withJSONObject: object), now: now).entries.isEmpty)
        #expect(PlaybackHistory(data: Data("bad json".utf8), now: now).entries.isEmpty)
    }

    @Test func testTimeFormattingAndStrictParsing() {
        #expect(PlaybackTime.format(65.9) == "01:05")
        #expect(PlaybackTime.format(3_661) == "1:01:01")
        #expect(PlaybackTime.format(.nan) == "00:00")
        for (value, expected) in [("65", 65.0), (" 01:05 ", 65), ("1:01:05", 3665), ("00:01.5", 1.5)] {
            #expect(PlaybackTime.parse(value) == expected)
        }
        for value in ["", "-1", "+1", "1:60", "1:00:60", "1::02", "1:2:3:4", "NaN", "infinity", "1e3", "1.5:20"] {
            #expect(PlaybackTime.parse(value) == nil)
        }
    }

    @Test func testSeekClampsAndUndoIsConsumedOnce() {
        var seeks = SeekHistory()
        #expect(!(seeks.canUndo))
        #expect(seeks.seek(from: 35, to: 500, duration: 120) == 120)
        #expect(seeks.canUndo)
        #expect(seeks.undo(duration: 120) == 35)
        #expect(seeks.undo(duration: 120) == nil)
        #expect(seeks.seek(from: 35, to: -1, duration: 120) == 0)
        #expect(seeks.seek(from: 20, to: .nan, duration: 120) == nil)
        #expect(seeks.undo(duration: 120) == 35)
        _ = seeks.seek(from: 35, to: 45, duration: 120)
        seeks.reset()
        #expect(!(seeks.canUndo))
    }
}
