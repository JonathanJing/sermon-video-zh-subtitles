import Foundation

/// Preserve review metadata without upgrading an unfamiliar representation to approval.
public enum JSONValue: Codable, Sendable, Equatable {
    case null, bool(Bool), number(Double), string(String), array([JSONValue]), object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
        else { self = .object(try container.decode([String: JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }
}

public enum CatalogError: Error, LocalizedError, Equatable, Sendable {
    case invalid(String)
    public var errorDescription: String? {
        switch self { case .invalid(let reason): return "内容目录无效：\(reason)" }
    }
}

public struct WeeklyCatalog: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-weekly-catalog-v1"
    public let schemaVersion: String
    public let defaultWeekId: String
    public let weeks: [SermonWeek]

    /// Available only after decoding or construction has validated the default reference.
    public var defaultWeek: SermonWeek { weeks.first { $0.id == defaultWeekId }! }

    public init(schemaVersion: String = supportedSchemaVersion, defaultWeekId: String, weeks: [SermonWeek]) throws {
        self.schemaVersion = schemaVersion
        self.defaultWeekId = defaultWeekId
        self.weeks = weeks
        try validate()
    }

    private enum CodingKeys: String, CodingKey { case schemaVersion, defaultWeekId, weeks }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(schemaVersion: values.decode(String.self, forKey: .schemaVersion),
                      defaultWeekId: values.decode(String.self, forKey: .defaultWeekId),
                      weeks: values.decode([SermonWeek].self, forKey: .weeks))
    }

    public static func decode(_ data: Data) throws -> WeeklyCatalog {
        try JSONDecoder().decode(WeeklyCatalog.self, from: data)
    }

    public func validate() throws {
        guard schemaVersion == Self.supportedSchemaVersion else { throw CatalogError.invalid("不支持的版本") }
        guard !weeks.isEmpty else { throw CatalogError.invalid("缺少周次") }
        guard Set(weeks.map(\.id)).count == weeks.count else { throw CatalogError.invalid("周次 ID 重复") }
        guard weeks.contains(where: { $0.id == defaultWeekId }) else { throw CatalogError.invalid("默认周次不存在") }
        for week in weeks { try week.validate() }
    }
}

public struct SermonWeek: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let date: String
    public let sourceId: String
    public let sourceUrl: String
    public let title: String
    public let speaker: String
    public let scripture: String
    public let number: String?
    public let series: String?
    public let centralMessage: String?
    public let summary: String?
    public let outline: [OutlineSection]?
    public let scriptureRefs: [String]?
    public let questions: [String]?
    public let contentReview: String?
    public let tracks: [SermonTrack]
    public let audioStatus: String?
    public let audioNotice: String?
    public let videoSynchronization: String?
    public let humanApproval: JSONValue?
    public let productionStages: [ProductionStage]?
    public let candidateEvidence: JSONValue?
    public let outlineSourceSha256: String?
    public let speakerSource: String?
    public let titleEvidence: String?

    public init(id: String, date: String, sourceId: String, sourceUrl: String, title: String,
                speaker: String, scripture: String, tracks: [SermonTrack], number: String? = nil,
                series: String? = nil, centralMessage: String? = nil, summary: String? = nil,
                outline: [OutlineSection]? = nil, scriptureRefs: [String]? = nil, questions: [String]? = nil,
                contentReview: String? = nil, audioStatus: String? = nil, audioNotice: String? = nil,
                videoSynchronization: String? = nil, humanApproval: JSONValue? = nil,
                productionStages: [ProductionStage]? = nil, candidateEvidence: JSONValue? = nil,
                outlineSourceSha256: String? = nil, speakerSource: String? = nil, titleEvidence: String? = nil) {
        self.id = id; self.date = date; self.sourceId = sourceId; self.sourceUrl = sourceUrl
        self.title = title; self.speaker = speaker; self.scripture = scripture; self.tracks = tracks
        self.number = number; self.series = series; self.centralMessage = centralMessage; self.summary = summary
        self.outline = outline; self.scriptureRefs = scriptureRefs; self.questions = questions
        self.contentReview = contentReview; self.audioStatus = audioStatus; self.audioNotice = audioNotice
        self.videoSynchronization = videoSynchronization; self.humanApproval = humanApproval
        self.productionStages = productionStages; self.candidateEvidence = candidateEvidence
        self.outlineSourceSha256 = outlineSourceSha256; self.speakerSource = speakerSource; self.titleEvidence = titleEvidence
    }

    public func validate() throws {
        guard Validation.identifier(id), Validation.isoDate(date), Validation.identifier(sourceId),
              Validation.httpsURL(sourceUrl), !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { throw CatalogError.invalid("周次来源或日期缺失") }
        guard Set(tracks.map(\.id)).count == tracks.count else { throw CatalogError.invalid("音轨 ID 重复") }
        for track in tracks { try track.validate() }
    }
}

public struct OutlineSection: Codable, Sendable, Equatable {
    public let title: String
    public let points: [String]
    public let sourceSliceIndexes: [Int]?
    public init(title: String, points: [String], sourceSliceIndexes: [Int]? = nil) {
        self.title = title; self.points = points; self.sourceSliceIndexes = sourceSliceIndexes
    }
}

public struct ProductionStage: Codable, Sendable, Equatable {
    public let label: String
    public let status: String
    public let detail: String?
}

public struct SermonTrack: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let label: String
    public let voiceLabel: String
    public let audioUrl: String
    public let file: String
    public let sha256: String
    public let durationSeconds: Double
    public let cues: [SubtitleCue]
    /// Candidate timing is retained as published; native playback does not confer acceptance.
    public let subtitleTiming: String
    public let scope: String
    public let voiceSampleReview: String?

    public init(id: String, label: String, voiceLabel: String, audioUrl: String, file: String,
                sha256: String, durationSeconds: Double, cues: [SubtitleCue],
                subtitleTiming: String, scope: String, voiceSampleReview: String? = nil) {
        self.id = id; self.label = label; self.voiceLabel = voiceLabel; self.audioUrl = audioUrl
        self.file = file; self.sha256 = sha256; self.durationSeconds = durationSeconds
        self.cues = cues; self.subtitleTiming = subtitleTiming; self.scope = scope; self.voiceSampleReview = voiceSampleReview
    }

    public func identity(weekID: String) -> TrackIdentity {
        TrackIdentity(weekID: weekID, trackID: id, audioSHA256: sha256)
    }

    public func validate() throws {
        guard Validation.identifier(id), Validation.sha256(sha256),
              durationSeconds.isFinite, durationSeconds > 0 else { throw CatalogError.invalid("音轨标识、哈希或时长无效") }
        guard Validation.mediaPath(audioUrl, filename: file) else { throw CatalogError.invalid("媒体路径无效") }
        var previousEnd: Double = 0
        var unitIDs: Set<Int> = []
        for cue in cues {
            guard cue.start.isFinite, cue.end.isFinite, cue.start >= previousEnd,
                  cue.end > cue.start, cue.end <= durationSeconds,
                  !cue.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  cue.unitId.map({ $0 >= 0 && unitIDs.insert($0).inserted }) ?? true,
                  cue.blockId.map({ $0 >= 0 }) ?? true
            else { throw CatalogError.invalid("字幕顺序、范围或标识无效") }
            previousEnd = cue.end
        }
    }

    /// Relative URLs are confined to the published media directory on the selected HTTPS host.
    public func mediaURL(relativeTo baseURL: URL) throws -> URL {
        guard Validation.httpsURL(baseURL.absoluteString), Validation.mediaPath(audioUrl, filename: file),
              var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        else { throw CatalogError.invalid("媒体地址无效") }
        components.path = "/media/" + file
        components.query = nil
        components.fragment = nil
        guard let url = components.url else { throw CatalogError.invalid("媒体地址无效") }
        return url
    }

    /// Half-open intervals prevent the previous cue from remaining visible at the next cue's start.
    public func cue(at time: Double) -> SubtitleCue? {
        guard time.isFinite, time >= 0, time < durationSeconds else { return nil }
        var low = 0, high = cues.count
        while low < high {
            let middle = low + (high - low) / 2
            if cues[middle].start <= time { low = middle + 1 } else { high = middle }
        }
        guard low > 0, time < cues[low - 1].end else { return nil }
        return cues[low - 1]
    }
}

public struct SubtitleCue: Codable, Sendable, Equatable {
    public let unitId: Int?
    public let blockId: Int?
    public let start: Double
    public let end: Double
    public let text: String
    public init(start: Double, end: Double, text: String, unitId: Int? = nil, blockId: Int? = nil) {
        self.start = start; self.end = end; self.text = text; self.unitId = unitId; self.blockId = blockId
    }
}

public struct TrackIdentity: Codable, Sendable, Equatable, Hashable {
    public let weekID: String
    public let trackID: String
    public let audioSHA256: String
    public init(weekID: String, trackID: String, audioSHA256: String) {
        self.weekID = weekID; self.trackID = trackID; self.audioSHA256 = audioSHA256
    }
    /// Length prefixes make the key unambiguous even for an identity not yet validated.
    public var key: String { [weekID, trackID, audioSHA256].map { "\($0.utf8.count):\($0)" }.joined() }
    public var isValid: Bool { Validation.identifier(weekID) && Validation.identifier(trackID) && Validation.sha256(audioSHA256) }
}

enum Validation {
    static func identifier(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 160 && value.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil
    }
    static func sha256(_ value: String) -> Bool {
        value.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil
    }
    static func isoDate(_ value: String) -> Bool {
        guard value.range(of: "^\\d{4}-\\d{2}-\\d{2}$", options: .regularExpression) != nil else { return false }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        guard let date = formatter.date(from: value) else { return false }
        return formatter.string(from: date) == value
    }
    static func httpsURL(_ value: String) -> Bool {
        guard let components = URLComponents(string: value) else { return false }
        return components.scheme == "https" && !(components.host?.isEmpty ?? true)
            && components.user == nil && components.password == nil
    }
    static func mediaPath(_ value: String, filename: String) -> Bool {
        guard filename.utf8.count <= 240,
              filename.range(of: "^[A-Za-z0-9][A-Za-z0-9._-]*$", options: .regularExpression) != nil,
              !filename.contains("..") else { return false }
        return value == "/media/" + filename || value == "media/" + filename
    }
}
