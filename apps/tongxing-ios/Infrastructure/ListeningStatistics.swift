import Foundation

/// No install identifier, advertising identifier, account, or feedback identity.
public struct ListeningSource: Sendable, Equatable, Hashable {
    public let week: String
    public let trackId: String
    public let audioSha256: String
    public init(week: String, trackId: String, audioSha256: String) {
        self.week = week; self.trackId = trackId; self.audioSha256 = audioSha256
    }
    public static func published(pageID: String, locale: String, sha256: String) -> Self {
        .init(week: String(pageID.prefix(10)), trackId: "\(pageID)-\(locale)-\(sha256.prefix(12))", audioSha256: sha256)
    }
}

/// Counts only observed continuous playback. Seeks, stalls, pauses and long sample
/// gaps reset the baseline; timeline coverage never invents the gap between seeks.
public struct ListeningAccumulator: Sendable {
    public private(set) var listenedSeconds = 0.0
    public private(set) var ranges: [[Double]] = []
    private var previous: (position: Double, uptime: Double)?
    public init() {}
    public mutating func resetBaseline() { previous = nil }
    public mutating func sample(position: Double, uptime: Double, playing: Bool, duration: Double) {
        guard playing, position.isFinite, uptime.isFinite, duration > 0,
              position >= 0, position <= duration else { resetBaseline(); return }
        if let old = previous, uptime <= old.uptime { return }
        defer { previous = (position, uptime) }
        guard let old = previous else { return }
        let elapsed = uptime - old.uptime, delta = position - old.position
        guard elapsed > 0, elapsed <= 120, delta > 0, delta <= elapsed + 0.5 else { return }
        listenedSeconds += min(delta, elapsed)
        var result: [[Double]] = []
        for range in (ranges + [[old.position, position]]).sorted(by: { $0[0] < $1[0] }) {
            if let last = result.last, range[0] <= last[1] {
                result[result.count - 1][1] = max(last[1], range[1])
            } else { result.append(range) }
        }
        // Preserve previously reported coverage monotonically. At the cap,
        // omit a new isolated fragment instead of inventing an unheard gap.
        if result.count <= 256 { ranges = result }
    }
    public static func reportingDay(_ date: Date) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Los_Angeles")!
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }
}

/// One anonymous count record per "听声定位" press, matching the Web
/// `/api/alignment-usage` whitelist: no audio, landmarks, route, error text or
/// playback position. Inconsistent combinations are normalized, never invented.
public struct AlignmentAttemptRecord: Sendable, Equatable {
    public enum Outcome: String, Sendable {
        case applied, matched, expired, timeout, cancelled, error, unavailable, unsupported
        case playFailed = "play_failed", playBlocked = "play_blocked", noMatch = "no_match"
        case permissionDenied = "permission_denied"
    }
    public enum Stage: String, Sendable {
        case opened, recording
        case indexReady = "index_ready", matchedAudio = "matched_audio"
    }
    static let reasons: Set<String> = ["matched", "silence", "insufficient_audio", "no_consensus", "ambiguous",
                                       "low_confidence", "incompatible_index", "incompatible_query", "unknown"]
    static let errorCodes: Set<String> = ["MIC_PERMISSION", "INPUT_INTERRUPTED", "INVALID_CAPTURE",
                                          "INDEX_UNAVAILABLE", "AUDIO_UNSUPPORTED", "UNKNOWN"]

    public let atMilliseconds: Int
    public let outcome: Outcome
    public let stage: Stage
    public let reason: String?
    public let errorCode: String?
    public let level: String?
    public let fractionBand: String?
    public let captureSeconds: Int?
    public let totalMilliseconds: Int?

    public init(at: Date, outcome: Outcome, stage: Stage, reason: String? = nil, errorCode: String? = nil,
                rms: Double? = nil, matchFraction: Double? = nil, captureSeconds: Double? = nil, totalSeconds: Double? = nil) {
        let heard = stage == .matchedAudio
        let safeReason = heard ? (reason.map { Self.reasons.contains($0) ? $0 : "unknown" } ?? "unknown") : nil
        var outcome = outcome
        if [.applied, .matched, .playFailed, .playBlocked].contains(outcome), safeReason != "matched" { outcome = .cancelled }
        if outcome == .noMatch, !heard || safeReason == "matched" { outcome = .error }
        atMilliseconds = Int((at.timeIntervalSince1970).rounded(.down)) * 1000
        self.outcome = outcome
        self.stage = stage
        self.reason = safeReason
        self.errorCode = errorCode.flatMap { Self.errorCodes.contains($0) ? $0 : nil }
        if heard, let rms, rms.isFinite, rms >= 0 {
            level = rms < 0.0001 ? "silent" : rms < 0.001 ? "very_low" : rms < 0.01 ? "low" : rms < 0.1 ? "moderate" : "high"
        } else { level = nil }
        // Bands around the frozen 0.055 accept gate; 0.045-0.055 is a near miss.
        if heard, let value = matchFraction, value.isFinite, value >= 0, value <= 1 {
            fractionBand = value < 0.03 ? "below_0_03" : value < 0.045 ? "0_03_to_0_045" : value < 0.055 ? "0_045_to_0_055" : "at_least_0_055"
        } else { fractionBand = nil }
        let rounded = captureSeconds.map { Int($0.rounded()) }
        self.captureSeconds = [Stage.recording, .matchedAudio].contains(stage) && [7, 10, 12, 15].contains(rounded ?? 0) ? rounded : nil
        if let totalSeconds, totalSeconds.isFinite, totalSeconds >= 0 {
            totalMilliseconds = min(600_000, Int((totalSeconds * 10).rounded()) * 100)
        } else { totalMilliseconds = nil }
    }

    var json: [String: Any] {
        let null = NSNull()
        return ["at": atMilliseconds, "outcome": outcome.rawValue, "stage": stage.rawValue,
                "reason": reason ?? null, "errorCode": errorCode ?? null, "level": level ?? null,
                "fractionBand": fractionBand ?? null, "captureSeconds": captureSeconds ?? null,
                "totalMs": totalMilliseconds ?? null, "shadow": null]
    }
}

/// Best-effort online reporting. Pending requests/credentials exist only in this
/// process; this is deliberately not an offline upload queue.
public actor ListeningStatistics {
    public static let preferenceKey = "tongxing-anonymous-listening-enabled-v1"
    private struct Key: Hashable { let source: ListeningSource; let day: String; let interfaceLocale: String; let contentLocale: String; let visit: UUID }
    private struct InterfaceRecord { let key: Key; let token: String; var seq: Int }
    private struct Record {
        var token: String
        var expiresAt: Date
        var clientID: String
        var seq = 0
        var accumulator = ListeningAccumulator()
        var lastFlush = Date.distantPast
        var mayExist = false
        var lastSentSeconds = 0.0
    }
    private let origin: URL
    private let session: URLSession
    private let defaults: UserDefaults
    private let appVersion: String
    private var enabled: Bool
    private var revision = 0
    private var active: Key?
    private var interfaceRecords: [UUID: InterfaceRecord] = [:]
    private var bootstrapSource: ListeningSource?
    private var interfaceLocale = "en"
    private var interfaceDay: String?
    private var interfaceRevision = 0
    private var records: [Key: Record] = [:]
    private var minting = Set<Key>()
    private var sending = Set<Key>()
    private var retryAfter: [Key: Date] = [:]
    /// Alignment presses use their own credentials and cumulative, append-only
    /// lists of at most 40 attempts; a full list continues in a new credential.
    private struct AlignmentKey: Hashable { let source: ListeningSource; let day: String; let interfaceLocale: String; let contentLocale: String; let chunk: Int }
    private struct AlignmentRecord {
        var token: String?
        var expiresAt = Date.distantFuture
        var clientID: String
        var seq = 0
        var attempts: [AlignmentAttemptRecord] = []
        var sentCount = 0
        var mayExist = false
    }
    static let alignmentAttemptsPerCredential = 40
    private var alignmentRecords: [AlignmentKey: AlignmentRecord] = [:]
    private var alignmentBusy = Set<AlignmentKey>()

    public init(origin: URL, appVersion: String, defaults: UserDefaults = .standard, session: URLSession? = nil) {
        self.origin = origin; self.appVersion = appVersion; self.defaults = defaults
        enabled = defaults.bool(forKey: Self.preferenceKey)
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil; config.urlCache = nil
        config.timeoutIntervalForRequest = 12
        self.session = session ?? URLSession(configuration: config)
    }

    public func setEnabled(_ value: Bool) async {
        enabled = value; revision += 1
        defaults.set(value, forKey: Self.preferenceKey)
        active = nil
        for key in records.keys { records[key]?.accumulator.resetBaseline() }
        guard !value else {
            if let bootstrapSource { await interfaceVisit(source: bootstrapSource, locale: interfaceLocale) }
            return
        }
        // Higher sequences protect against a late in-flight upsert. Include all
        // languages visited this run, including uncertain timed-out submissions.
        for key in Array(records.keys) where records[key]?.mayExist == true { await retract(key) }
        for key in Array(alignmentRecords.keys) { await retractAlignment(key) }
        interfaceRevision += 1; interfaceDay = nil
        for (id, var record) in interfaceRecords {
            record.seq += 1; interfaceRecords[id] = record
            var body = common(record.key.source)
            body.merge(["action": "delete", "seq": record.seq]) { _, new in new }
            if (try? await post("/api/interface-usage", body: body, token: record.token)) != nil { interfaceRecords[id] = nil }
        }
        defaults.removeObject(forKey: "tongxing-listening-day")
        defaults.removeObject(forKey: "tongxing-listening-day-id")
    }

    public func sample(source: ListeningSource?, position: Double, duration: Double,
                       playing: Bool, uptime: Double, interfaceLocale: String, contentLocale: String, date: Date = Date()) async {
        guard enabled else { return }
        let day = ListeningAccumulator.reportingDay(date)
        let key: Key? = source.map { source in
            if let active, active.source == source, active.day == day, active.interfaceLocale == interfaceLocale, active.contentLocale == contentLocale { return active }
            return Key(source: source, day: day, interfaceLocale: interfaceLocale, contentLocale: contentLocale, visit: UUID())
        }
        if active != key {
            let previous = active
            active = key
            if let previous { records[previous]?.accumulator.resetBaseline(); await flush(previous, date: date) }
        }
        guard enabled, active == key, let key else { return }
        if records[key] == nil {
            guard playing, !minting.contains(key), (retryAfter[key] ?? .distantPast) <= date else { return }
            minting.insert(key)
            let expected = revision
            do {
                let response = try await post("/api/session", body: common(key.source))
                guard let token = response["token"] as? String, let expiry = Self.expiry(response),
                      expiry > date else { throw URLError(.badServerResponse) }
                if enabled && expected == revision {
                    records[key] = Record(token: token, expiresAt: expiry, clientID: dailyID(key.day))
                }
            } catch { retryAfter[key] = date.addingTimeInterval(30) }
            minting.remove(key)
            // Never count elapsed playback before the token was actually minted.
            return
        }
        guard var record = records[key], record.expiresAt > date else { return }
        record.accumulator.sample(position: position, uptime: uptime, playing: playing, duration: duration)
        records[key] = record
        if !playing || date.timeIntervalSince(record.lastFlush) >= 30 { await flush(key, date: date) }
    }

    public func interfaceVisit(source: ListeningSource, locale: String, date: Date = Date()) async {
        bootstrapSource = source
        let changed = locale != interfaceLocale
        interfaceLocale = locale
        let day = ListeningAccumulator.reportingDay(date)
        guard enabled, changed || interfaceDay != day else { return }
        interfaceDay = day; interfaceRevision += 1
        let expected = interfaceRevision, consentRevision = revision
        let key = Key(source: source, day: day, interfaceLocale: locale, contentLocale: locale, visit: UUID())
        do {
            let response = try await post("/api/session", body: common(source))
            guard enabled, revision == consentRevision, interfaceRevision == expected,
                  let token = response["token"] as? String else { return }
            interfaceRecords[key.visit] = InterfaceRecord(key: key, token: token, seq: 1)
            var body = common(source)
            body.merge(["action": "upsert", "seq": 1, "day": day, "clientId": dailyID(day),
                        "platform": "ios", "interfaceLocale": locale]) { _, new in new }
            _ = try await post("/api/interface-usage", body: body, token: token)
        } catch { if interfaceRevision == expected { interfaceDay = nil } }
    }

    private static func expiry(_ response: [String: Any]) -> Date? {
        if let value = response["expiresAt"] as? Double { return Date(timeIntervalSince1970: value / 1000) }
        if let value = response["expiresAt"] as? String {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            return formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
        }
        return nil
    }

    public func flush() async {
        if let active { await flush(active, date: Date()) }
        for key in Array(alignmentRecords.keys) { await sendAlignment(key) }
    }

    public func recordAlignment(_ attempt: AlignmentAttemptRecord, source: ListeningSource,
                                interfaceLocale: String, contentLocale: String, date: Date = Date()) async {
        guard enabled else { return }
        let day = ListeningAccumulator.reportingDay(date)
        var chunk = 0
        func key(_ chunk: Int) -> AlignmentKey { .init(source: source, day: day, interfaceLocale: interfaceLocale, contentLocale: contentLocale, chunk: chunk) }
        while (alignmentRecords[key(chunk)]?.attempts.count ?? 0) >= Self.alignmentAttemptsPerCredential { chunk += 1 }
        let target = key(chunk)
        if alignmentRecords[target] == nil { alignmentRecords[target] = AlignmentRecord(clientID: dailyID(day)) }
        alignmentRecords[target]?.attempts.append(attempt)
        await sendAlignment(target)
    }

    /// Mints lazily, then upserts the whole list with a higher sequence. A failed
    /// send keeps the attempts for the next press or flush; nothing is persisted.
    private func sendAlignment(_ key: AlignmentKey) async {
        guard enabled, !alignmentBusy.contains(key), let initial = alignmentRecords[key],
              initial.attempts.count > initial.sentCount, initial.expiresAt > Date() else { return }
        alignmentBusy.insert(key)
        defer { alignmentBusy.remove(key) }
        let consent = revision
        if initial.token == nil {
            guard let response = try? await post("/api/session", body: common(key.source)),
                  let token = response["token"] as? String, let expiry = Self.expiry(response), expiry > Date(),
                  enabled, revision == consent else { return }
            alignmentRecords[key]?.token = token; alignmentRecords[key]?.expiresAt = expiry
        }
        while enabled, revision == consent, var record = alignmentRecords[key], let token = record.token,
              record.attempts.count > record.sentCount {
            record.seq += 1; record.mayExist = true
            alignmentRecords[key] = record
            let attempts = record.attempts
            var body = common(key.source)
            body.merge(["action": "upsert", "seq": record.seq, "day": key.day, "clientId": record.clientID,
                        "platform": "ios", "interfaceLocale": key.interfaceLocale, "contentLocale": key.contentLocale,
                        "attempts": attempts.map(\.json)]) { _, new in new }
            guard (try? await post("/api/alignment-usage", body: body, token: token)) != nil else { return }
            alignmentRecords[key]?.sentCount = attempts.count
        }
    }

    private func retractAlignment(_ key: AlignmentKey) async {
        guard var record = alignmentRecords[key] else { return }
        guard record.mayExist, let token = record.token, record.expiresAt > Date() else { alignmentRecords[key] = nil; return }
        record.seq += 1; alignmentRecords[key] = record
        var body = common(key.source)
        body.merge(["action": "delete", "seq": record.seq]) { _, new in new }
        if (try? await post("/api/alignment-usage", body: body, token: token)) != nil { alignmentRecords[key] = nil }
    }

    private func flush(_ key: Key, date: Date) async {
        guard enabled, !sending.contains(key), var record = records[key], record.expiresAt > date,
              record.accumulator.listenedSeconds > record.lastSentSeconds,
              (retryAfter[key] ?? .distantPast) <= date else { return }
        sending.insert(key)
        record.seq += 1; record.lastFlush = date; record.mayExist = true
        records[key] = record
        var body = common(key.source)
        body.merge(["action": "upsert", "seq": record.seq, "day": key.day,
                    "clientId": record.clientID, "platform": "ios",
                    "interfaceLocale": key.interfaceLocale, "contentLocale": key.contentLocale,
                    "listenedSeconds": record.accumulator.listenedSeconds,
                    "ranges": record.accumulator.ranges]) { _, new in new }
        do {
            _ = try await post("/api/listening", body: body, token: record.token)
            records[key]?.lastSentSeconds = record.accumulator.listenedSeconds
        }
        catch { retryAfter[key] = date.addingTimeInterval(30) }
        sending.remove(key)
    }

    private func retract(_ key: Key) async {
        guard var record = records[key], record.expiresAt > Date() else { return }
        record.seq += 1; records[key] = record
        var body = common(key.source)
        body.merge(["action": "delete", "seq": record.seq]) { _, new in new }
        do {
            _ = try await post("/api/listening", body: body, token: record.token)
            records[key] = nil
        } catch { /* Best effort only; notice does not promise deletion offline. */ }
    }

    private func dailyID(_ day: String) -> String {
        if defaults.string(forKey: "tongxing-listening-day") == day,
           let saved = defaults.string(forKey: "tongxing-listening-day-id"), UUID(uuidString: saved) != nil { return saved }
        let value = UUID().uuidString.lowercased()
        defaults.set(day, forKey: "tongxing-listening-day")
        defaults.set(value, forKey: "tongxing-listening-day-id")
        return value
    }
    private func common(_ source: ListeningSource) -> [String: Any] {
        ["schemaVersion": 1, "week": source.week, "trackId": source.trackId,
         "audioSha256": source.audioSha256, "appVersion": appVersion]
    }
    private func post(_ path: String, body: [String: Any], token: String? = nil) async throws -> [String: Any] {
        var request = URLRequest(url: origin.appendingPathComponent(String(path.dropFirst())))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(origin.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/")), forHTTPHeaderField: "Origin")
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode),
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              value["accepted"] as? Bool != false else { throw URLError(.badServerResponse) }
        return value
    }
}
