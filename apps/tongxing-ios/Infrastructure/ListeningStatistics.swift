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

    public func flush() async { if let active { await flush(active, date: Date()) } }

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
