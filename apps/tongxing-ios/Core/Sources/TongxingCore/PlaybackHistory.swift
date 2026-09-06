import Foundation

public struct ResumePosition: Sendable, Equatable {
    public let position: Double
    public let offset: Double
    public let savedAt: Date
}

public struct PlaybackEntry: Codable, Sendable, Equatable {
    public let identity: TrackIdentity
    public let sourceID: String
    public let position: Double
    public let offset: Double
    public let duration: Double
    public let savedAt: Date

    init(identity: TrackIdentity, sourceID: String, position: Double, offset: Double, duration: Double, savedAt: Date) {
        self.identity = identity; self.sourceID = sourceID; self.position = position
        self.offset = offset; self.duration = duration; self.savedAt = savedAt
    }

    private enum CodingKeys: String, CodingKey { case identity, sourceID, position, offset, duration, savedAt }
    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        identity = try container.decode(TrackIdentity.self, forKey: .identity)
        sourceID = try container.decode(String.self, forKey: .sourceID)
        position = try container.decode(Double.self, forKey: .position)
        offset = try container.decode(Double.self, forKey: .offset)
        duration = try container.decode(Double.self, forKey: .duration)
        savedAt = Date(timeIntervalSince1970: try container.decode(Double.self, forKey: .savedAt))
    }
    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(identity, forKey: .identity)
        try container.encode(sourceID, forKey: .sourceID)
        try container.encode(position, forKey: .position)
        try container.encode(offset, forKey: .offset)
        try container.encode(duration, forKey: .duration)
        try container.encode(savedAt.timeIntervalSince1970, forKey: .savedAt)
    }

    var isValid: Bool {
        identity.isValid && Validation.identifier(sourceID)
            && PlaybackHistory.valid(position: position, offset: offset, duration: duration)
            && PlaybackHistory.useful(position: position, duration: duration)
            && savedAt.timeIntervalSince1970.isFinite && savedAt.timeIntervalSince1970 >= 0
    }
}

/// Bookmarks never imply autoplay, current live-clock position, or acceptance of the audio.
public struct PlaybackHistory: Codable, Sendable, Equatable {
    public static let maximumEntries = 12
    public static let maximumAge: TimeInterval = 30 * 86_400
    public static let schemaVersion = 1
    public private(set) var entries: [PlaybackEntry] = []

    public init() {}

    /// Local corruption must not prevent the listener opening a sermon.
    public init(data: Data, now: Date = Date()) {
        let decoder = JSONDecoder()
        decoder.userInfo[Self.decodeClockKey] = now
        self = (try? decoder.decode(Self.self, from: data)) ?? Self()
    }

    private static let decodeClockKey = CodingUserInfoKey(rawValue: "TongxingCore.playbackHistoryClock")!
    private enum CodingKeys: String, CodingKey { case schemaVersion, entries }
    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        guard try container.decode(Int.self, forKey: .schemaVersion) == Self.schemaVersion else {
            throw CatalogError.invalid("播放历史版本不支持")
        }
        let rows = try container.decode([JSONValue].self, forKey: .entries)
        // Decode each row independently so one damaged entry cannot erase valid bookmarks.
        entries = rows.compactMap { row in
            guard let data = try? JSONEncoder().encode(row),
                  let entry = try? JSONDecoder().decode(PlaybackEntry.self, from: data), entry.isValid
            else { return nil }
            return entry
        }
        // Discard future/expired rows before deduplication so they cannot shadow a valid bookmark.
        prune(at: decoder.userInfo[Self.decodeClockKey] as? Date ?? Date())
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(Self.schemaVersion, forKey: .schemaVersion)
        try container.encode(entries, forKey: .entries)
    }

    public func encoded() throws -> Data { try JSONEncoder().encode(self) }

    /// Returns false for invalid values or a position within the opening/final two seconds.
    /// An intentional return to either boundary clears that track's previous bookmark.
    @discardableResult
    public mutating func record(identity: TrackIdentity, sourceID: String, position: Double,
                                offset: Double, duration: Double, at: Date = Date()) -> Bool {
        guard identity.isValid, Validation.identifier(sourceID), Self.validClock(at),
              Self.valid(position: position, offset: offset, duration: duration) else { return false }
        prune(at: at)
        remove(identity: identity)
        guard Self.useful(position: position, duration: duration) else { return false }
        entries.insert(PlaybackEntry(identity: identity, sourceID: sourceID, position: position,
                                     offset: offset, duration: duration, savedAt: at), at: 0)
        deduplicateAndLimit()
        return true
    }

    public mutating func resume(identity: TrackIdentity, sourceID: String, duration: Double,
                                at: Date = Date()) -> ResumePosition? {
        guard identity.isValid, Validation.identifier(sourceID), duration.isFinite, duration > 0,
              Self.validClock(at) else { return nil }
        prune(at: at)
        guard let entry = entries.first(where: { $0.identity == identity && $0.sourceID == sourceID }) else { return nil }
        guard Self.valid(position: entry.position, offset: entry.offset, duration: duration),
              Self.useful(position: entry.position, duration: duration) else {
            remove(identity: identity)
            return nil
        }
        return ResumePosition(position: entry.position, offset: entry.offset, savedAt: entry.savedAt)
    }

    public mutating func remove(identity: TrackIdentity) { entries.removeAll { $0.identity == identity } }

    public mutating func prune(at now: Date = Date()) {
        guard Self.validClock(now) else { entries = []; return }
        entries.removeAll {
            !$0.isValid || $0.savedAt > now || now.timeIntervalSince($0.savedAt) >= Self.maximumAge
        }
        deduplicateAndLimit()
    }

    static func valid(position: Double, offset: Double, duration: Double) -> Bool {
        duration.isFinite && duration > 0 && position.isFinite && position >= 0 && position <= duration
            && offset.isFinite && abs(offset) <= duration
    }
    static func useful(position: Double, duration: Double) -> Bool { position >= 2 && position < duration - 2 }
    private static func validClock(_ date: Date) -> Bool {
        date.timeIntervalSince1970.isFinite && date.timeIntervalSince1970 >= 0
    }
    private mutating func deduplicateAndLimit() {
        // Stable tie handling preserves the most recently recorded entry (inserted first).
        let sorted = entries.enumerated().sorted {
            $0.element.savedAt == $1.element.savedAt ? $0.offset < $1.offset : $0.element.savedAt > $1.element.savedAt
        }
        var seen: Set<TrackIdentity> = []
        entries = sorted.compactMap { seen.insert($0.element.identity).inserted ? $0.element : nil }
        entries = Array(entries.prefix(Self.maximumEntries))
    }
}
