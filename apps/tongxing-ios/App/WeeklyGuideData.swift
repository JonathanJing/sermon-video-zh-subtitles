import Foundation
import CryptoKit
import CoreFoundation
import TongxingCore

struct WeeklyGuide: Decodable, Equatable, Identifiable {
    let id: String
    let week: Int
    let title: String
    let scripture: String
    let sections: [WeeklyGuideSection]
}

struct WeeklyGuideSection: Decodable, Equatable, Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let symbol: String
    let body: String
    /// The plain-text body remains complete for old clients and as a safe
    /// fallback when any structured block cannot be understood.
    let blocks: [WeeklyGuideBlock]?

    init(id: String, title: String, subtitle: String, symbol: String, body: String,
         blocks: [WeeklyGuideBlock]? = nil) {
        self.id = id
        self.title = title
        self.subtitle = subtitle
        self.symbol = symbol
        self.body = body
        self.blocks = blocks
    }

    private enum CodingKeys: String, CodingKey { case id, title, subtitle, symbol, body, blocks }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        title = try values.decode(String.self, forKey: .title)
        subtitle = try values.decode(String.self, forKey: .subtitle)
        symbol = try values.decode(String.self, forKey: .symbol)
        body = try values.decode(String.self, forKey: .body)
        // A partial render would silently omit unknown or malformed content.
        // In that case show the complete plain-text body instead.
        let decoded = try? values.decode([WeeklyGuideBlock].self, forKey: .blocks)
        blocks = decoded.flatMap { $0.isEmpty ? nil : $0 }
        if blocks == nil && body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw DecodingError.dataCorruptedError(forKey: .body, in: values,
                                                   debugDescription: "No readable guide content")
        }
    }
}

enum WeeklyGuideBlock: Decodable, Equatable {
    case paragraph(text: String)
    case table(title: String, columns: [String], rows: [[String]], footnote: String?)
    case list(title: String, items: [String])
    case flow(title: String, items: [String])
    case image(assetID: String, alt: String, caption: String)
    case map(title: String, points: [WeeklyGuideMapPoint], caption: String, attribution: String)

    private enum CodingKeys: String, CodingKey { case type, text, title, columns, rows, footnote, items, assetID, alt, caption, points, attribution }
    private struct AnyKey: CodingKey {
        let stringValue: String
        let intValue: Int? = nil
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let type = try values.decode(String.self, forKey: .type)
        let allKeys = try Set(decoder.container(keyedBy: AnyKey.self).allKeys.map(\.stringValue))
        let allowed: Set<String>
        switch type {
        case "paragraph": allowed = ["type", "text"]
        case "table": allowed = ["type", "title", "columns", "rows", "footnote"]
        case "list", "flow": allowed = ["type", "title", "items"]
        case "image": allowed = ["type", "assetID", "alt", "caption"]
        case "map": allowed = ["type", "title", "points", "caption", "attribution"]
        default:
            throw DecodingError.dataCorruptedError(forKey: .type, in: values, debugDescription: "Unsupported guide block")
        }
        guard allKeys.isSubset(of: allowed) else {
            throw DecodingError.dataCorruptedError(forKey: .type, in: values, debugDescription: "Unsupported guide block fields")
        }
        func requiredText(_ key: CodingKeys) throws -> String {
            let value = try values.decode(String.self, forKey: key)
            guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw DecodingError.dataCorruptedError(forKey: key, in: values, debugDescription: "Empty content")
            }
            return value
        }
        switch type {
        case "paragraph":
            self = .paragraph(text: try requiredText(.text))
        case "table":
            let title = try values.decode(String.self, forKey: .title)
            let columns = try values.decode([String].self, forKey: .columns)
            let rows = try values.decode([[String]].self, forKey: .rows)
            let footnote = try values.decodeIfPresent(String.self, forKey: .footnote)
            guard !columns.isEmpty, columns.contains(where: { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }),
                  !rows.isEmpty, rows.allSatisfy({ $0.count == columns.count }) else {
                throw DecodingError.dataCorruptedError(forKey: .rows, in: values, debugDescription: "Invalid table dimensions")
            }
            self = .table(title: title, columns: columns, rows: rows, footnote: footnote)
        case "list", "flow":
            let title = try values.decode(String.self, forKey: .title)
            let items = try values.decode([String].self, forKey: .items)
            guard !items.isEmpty, items.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else {
                throw DecodingError.dataCorruptedError(forKey: .items, in: values, debugDescription: "Empty list")
            }
            self = type == "list" ? .list(title: title, items: items) : .flow(title: title, items: items)
        case "image":
            let assetID = try requiredText(.assetID)
            let alt = try requiredText(.alt)
            let caption = try requiredText(.caption)
            guard WeeklyGuideImageAssets.isAllowed(assetID) else {
                throw DecodingError.dataCorruptedError(forKey: .assetID, in: values, debugDescription: "Unknown bundled guide image")
            }
            self = .image(assetID: assetID, alt: alt, caption: caption)
        case "map":
            let title = try requiredText(.title)
            let caption = try requiredText(.caption)
            let attribution = try requiredText(.attribution)
            let points = try values.decode([WeeklyGuideMapPoint].self, forKey: .points)
            guard (2...32).contains(points.count), Set(points.map(\.name)).count == points.count,
                  let minLat = points.map(\.latitude).min(), let maxLat = points.map(\.latitude).max(),
                  let minLon = points.map(\.longitude).min(), let maxLon = points.map(\.longitude).max(),
                  maxLat > minLat, maxLon > minLon else {
                throw DecodingError.dataCorruptedError(forKey: .points, in: values, debugDescription: "Invalid map points")
            }
            self = .map(title: title, points: points, caption: caption, attribution: attribution)
        default:
            throw DecodingError.dataCorruptedError(forKey: .type, in: values, debugDescription: "Unsupported guide block")
        }
    }
}

struct WeeklyGuideMapPoint: Decodable, Equatable {
    let name: String
    let latitude: Double
    let longitude: Double
    /// Metadata only; rendering never fetches this URL.
    let sourceURL: String
    let credit: String

    private enum CodingKeys: String, CodingKey { case name, latitude, longitude, sourceURL, credit }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        name = try values.decode(String.self, forKey: .name)
        latitude = try values.decode(Double.self, forKey: .latitude)
        longitude = try values.decode(Double.self, forKey: .longitude)
        sourceURL = try values.decode(String.self, forKey: .sourceURL)
        credit = try values.decode(String.self, forKey: .credit)
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !credit.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              latitude.isFinite, (-90...90).contains(latitude), longitude.isFinite, (-180...180).contains(longitude),
              let url = URLComponents(string: sourceURL), url.scheme == "https", url.host == "pleiades.stoa.org",
              url.user == nil, url.password == nil, url.port == nil, url.query == nil, url.fragment == nil,
              url.path.range(of: "^/places/[0-9]+/?$", options: .regularExpression) != nil else {
            throw DecodingError.dataCorruptedError(forKey: .sourceURL, in: values, debugDescription: "Invalid source-backed map point")
        }
    }
}

/// Only these licensed image bytes may be used in guide content. No URL or
/// caller-supplied path is interpreted as an image location.
enum WeeklyGuideImageAssets {
    private static let expected: [String: String] = [
        "weekly-guide-statue.jpg": "f1d2f517120099a38614c7c560c1fbe054ec3ea4d741284fbcef496a7dab73b5",
        "weekly-guide-son-of-man.jpg": "30c3e5b82c024bad3e40122f330f6606d022c91d8c77a82f06d6f1d5fc987f1f"
    ]

    static func isAllowed(_ assetID: String) -> Bool { expected[assetID] != nil }

    static func verifies(_ data: Data, assetID: String) -> Bool {
        guard let digest = expected[assetID], data.count <= 4 * 1024 * 1024 else { return false }
        return WeeklyGuideRepository.sha256(data) == digest
    }

    static func data(for assetID: String, bundle: Bundle = .main) -> Data? {
        guard isAllowed(assetID), let url = bundle.url(forResource: assetID, withExtension: nil),
              let data = try? Data(contentsOf: url), verifies(data, assetID: assetID) else { return nil }
        return data
    }
}

struct WeeklyGuideLegacyIdentity: Hashable {
    let sourceIdSHA256: String
    let sourceUrlSHA256: String
    let sourceMediaSHA256: String
    let sourceStartSeconds: Double
    let sourceEndSeconds: Double
}

struct WeeklyGuideSelection: Hashable {
    let pageID: String?
    let locale: String
    var editionId: String? = nil
    var sourceIdentitySha256: String? = nil
    var releasePackageJsonSha256: String? = nil
    var legacy: WeeklyGuideLegacyIdentity? = nil

    var hasV5Identity: Bool {
        pageID != nil && editionId != nil && sourceIdentitySha256 != nil && releasePackageJsonSha256 != nil && legacy == nil
    }
    var hasStrongLegacyIdentity: Bool {
        guard pageID != nil, let legacy else { return false }
        let hashes = [legacy.sourceIdSHA256, legacy.sourceUrlSHA256, legacy.sourceMediaSHA256]
        return hashes.allSatisfy { $0.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil } &&
            legacy.sourceStartSeconds.isFinite && legacy.sourceEndSeconds.isFinite &&
            legacy.sourceStartSeconds >= 0 && legacy.sourceEndSeconds > legacy.sourceStartSeconds
    }
}

struct WeeklyGuideResponse {
    let data: Data
    let url: URL
    let statusCode: Int
}

enum WeeklyGuideRemoteResult: Equatable {
    case manifestUnavailable
    case notDeclared
    case available(WeeklyGuide)
    case outdatedRevision(Int)
    case revoked
    case invalidDeclared
}

/// Persist only deny decisions, scoped to the exact origin and sermon identity.
/// A verified current resource clears the deny; a missing manifest never does.
struct WeeklyGuideDenyLedger {
    let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    private func key(_ selection: WeeklyGuideSelection, origin: URL) -> String {
        let host = URLComponents(url: origin, resolvingAgainstBaseURL: false)?.host?.lowercased()
        let canonicalOrigin = host.map { "https://" + $0 } ?? origin.absoluteString
        let raw = [canonicalOrigin, selection.pageID ?? "", selection.locale,
                   selection.editionId ?? "", selection.sourceIdentitySha256 ?? "",
                   selection.releasePackageJsonSha256 ?? "", selection.legacy?.sourceIdSHA256 ?? "",
                   selection.legacy?.sourceUrlSHA256 ?? "", selection.legacy?.sourceMediaSHA256 ?? "",
                   selection.legacy.map { String($0.sourceStartSeconds) } ?? "",
                   selection.legacy.map { String($0.sourceEndSeconds) } ?? ""].joined(separator: "\u{0}")
        return "tongxing.guide.deny.v1." + WeeklyGuideRepository.sha256(Data(raw.utf8))
    }
    func isDenied(_ selection: WeeklyGuideSelection, origin: URL) -> Bool {
        defaults.bool(forKey: key(selection, origin: origin))
    }
    func apply(_ result: WeeklyGuideRemoteResult, selection: WeeklyGuideSelection, origin: URL) {
        switch result {
        case .revoked, .invalidDeclared:
            defaults.set(true, forKey: key(selection, origin: origin))
        case .available:
            defaults.removeObject(forKey: key(selection, origin: origin))
        case .manifestUnavailable, .notDeclared, .outdatedRevision:
            break
        }
    }
}

enum WeeklyGuideRepository {
    static let manifestLimit = 512 * 1024
    static let guideLimit = 2 * 1024 * 1024
    static let acceptedBundleSHA = "a527e23fbd693177b9589fc89cd3533b653f64918abb97213cf34172c36711f9"
    typealias Fetch = (URL, URL, Int) async throws -> WeeklyGuideResponse

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// A legacy catalog can omit the top-level source hash while carrying a
    /// fingerprint binding. Accept it only when its page, window and track agree
    /// with the selected week; a present top-level hash must never conflict.
    /// The resulting source ID, URL, media hash and window are additionally
    /// checked against the per-origin Bundle identity evidence before display.
    static func legacyIdentity(week: SermonWeek) -> WeeklyGuideLegacyIdentity? {
        guard let start = week.sourceStartSeconds, let end = week.sourceEndSeconds,
              start.isFinite, end.isFinite, start >= 0, end > start else { return nil }
        let sourceSHA: String
        if let fingerprint = week.audioFingerprint {
            guard (try? fingerprint.validate()) != nil, fingerprint.pageId == week.id,
                  fingerprint.sourceStartSeconds == start, fingerprint.sourceEndSeconds == end,
                  week.sourceSha256 == nil || week.sourceSha256 == fingerprint.sourceSha256,
                  week.tracks.contains(where: { $0.sha256 == fingerprint.trackSha256 }) else { return nil }
            sourceSHA = fingerprint.sourceSha256
        } else {
            guard let topLevelSHA = week.sourceSha256 else { return nil }
            sourceSHA = topLevelSHA
        }
        return WeeklyGuideLegacyIdentity(sourceIdSHA256: sha256(Data(week.sourceId.utf8)),
            sourceUrlSHA256: sha256(Data(week.sourceUrl.utf8)), sourceMediaSHA256: sourceSHA,
            sourceStartSeconds: start, sourceEndSeconds: end)
    }

    static func load(pageID: String?, locale: String, data: Data) -> WeeklyGuide? {
        guard locale == "zh-Hans", let pageID, !pageID.isEmpty,
              let collection = try? JSONDecoder().decode(Collection.self, from: data) else { return nil }
        let matches = collection.guides.filter { $0.id == pageID }
        guard matches.count == 1, let guide = matches.first, valid(guide) else { return nil }
        return guide
    }

    static func loadBundled(selection: WeeklyGuideSelection, origin: URL) -> WeeklyGuide? {
        guard let url = Bundle.main.url(forResource: "weekly-guides", withExtension: "json"),
              let data = try? Data(contentsOf: url) else { return nil }
        return loadBundled(selection: selection, origin: origin, data: data,
                           bindingData: Data(bundledBindings.utf8), expectedSHA: acceptedBundleSHA)
    }

    static func loadBundled(selection: WeeklyGuideSelection, origin: URL, data: Data,
                            bindingData: Data, expectedSHA: String) -> WeeklyGuide? {
        guard sha256(data) == expectedSHA,
              let guide = load(pageID: selection.pageID, locale: selection.locale, data: data),
              matchesBundledIdentity(selection: selection, origin: origin, week: guide.week,
                                     bindingData: bindingData) else { return nil }
        return guide
    }

    static func hasApprovedBundleIdentity(selection: WeeklyGuideSelection, origin: URL, week: Int) -> Bool {
        matchesBundledIdentity(selection: selection, origin: origin, week: week,
                               bindingData: Data(bundledBindings.utf8))
    }

    private static func matchesBundledIdentity(selection: WeeklyGuideSelection, origin: URL, week: Int,
                                               bindingData: Data) -> Bool {
        guard validOrigin(origin),
              let all = try? JSONDecoder().decode([String: [BundleBinding]].self, from: bindingData),
              let originKey = URLComponents(url: origin, resolvingAgainstBaseURL: false)?.host?.lowercased(),
              let bindings = all["https://" + originKey] else { return false }
        let matches = bindings.filter { $0.pageID == selection.pageID && $0.locale == selection.locale }
        guard matches.count == 1, let b = matches.first, b.week == week else { return false }
        if let legacy = selection.legacy {
            return b.sourceIdSHA256 == legacy.sourceIdSHA256 && b.sourceUrlSHA256 == legacy.sourceUrlSHA256 &&
                b.sourceMediaSHA256 == legacy.sourceMediaSHA256 &&
                b.sourceStartSeconds == legacy.sourceStartSeconds && b.sourceEndSeconds == legacy.sourceEndSeconds
        }
        return selection.hasV5Identity && b.editionId == selection.editionId &&
            b.sourceIdentitySha256 == selection.sourceIdentitySha256 &&
            b.releasePackageJsonSha256 == selection.releasePackageJsonSha256
    }

    static func matchingRemote(_ guide: WeeklyGuide?, resultFor: WeeklyGuideSelection?,
                               current: WeeklyGuideSelection) -> WeeklyGuide? {
        guard resultFor == current, guide?.id == current.pageID else { return nil }
        return guide
    }

    static func resolvedGuide(_ result: WeeklyGuideRemoteResult, selection: WeeklyGuideSelection,
                              origin: URL, ledger: WeeklyGuideDenyLedger,
                              bundled: () -> WeeklyGuide?) -> WeeklyGuide? {
        ledger.apply(result, selection: selection, origin: origin)
        switch result {
        case .available(let guide):
            return guide
        case .manifestUnavailable, .notDeclared:
            return ledger.isDenied(selection, origin: origin) ? nil : bundled()
        case .outdatedRevision(let week):
            guard !ledger.isDenied(selection, origin: origin),
                  let guide = bundled(), guide.id == selection.pageID, guide.week == week,
                  hasApprovedBundleIdentity(selection: selection, origin: origin, week: week) else { return nil }
            return guide
        case .revoked, .invalidDeclared:
            return nil
        }
    }

    /// The configured same-origin service is the trust root. Hashes bind manifest
    /// entries to downloaded bytes; they do not authenticate a compromised server.
    static func loadRemote(selection: WeeklyGuideSelection, origin: URL,
                           fetch: @escaping Fetch = fetchBounded) async -> WeeklyGuideRemoteResult {
        switch selection.locale {
        case "zh-Hans": return await loadRemoteV1(selection: selection, origin: origin, fetch: fetch)
        case "ko", "es": return await loadRemoteV2(selection: selection, origin: origin, fetch: fetch)
        default: return .manifestUnavailable
        }
    }

    private static func loadRemoteV1(selection: WeeklyGuideSelection, origin: URL,
                                     fetch: @escaping Fetch) async -> WeeklyGuideRemoteResult {
        guard selection.locale == "zh-Hans", (selection.hasV5Identity || selection.hasStrongLegacyIdentity),
              let pageID = selection.pageID,
              validOrigin(origin), let manifestURL = URL(string: "/weekly-guides/manifest-v1.json", relativeTo: origin)?.absoluteURL else { return .manifestUnavailable }
        let response: WeeklyGuideResponse
        do { response = try await fetch(manifestURL, origin, manifestLimit) }
        catch { return .manifestUnavailable }
        guard !Task.isCancelled, response.statusCode == 200, response.data.count <= manifestLimit,
              response.url == manifestURL,
              let json = try? JSONSerialization.jsonObject(with: response.data) as? [String: Any],
              let schema = json["schemaVersion"] as? String,
              schema == "tongxing-weekly-guide-manifest-v1" else { return .manifestUnavailable }
        // Provenance is an explicit claim from the trusted service, not a signature.
        guard json["seriesID"] as? String == "revelation-comfort-and-hope",
              json["translationSHA256"] as? String == "d6c6064e8fab11ab012edd9535372a9f99b83cd5240b6014f5451795a9198f86",
              json["cuvSHA256"] as? String == "363afb38148f150b30fee727f4818faa821a0d17b4888c16be3e05bd462503bb",
              json["review"] as? String == "machine_translation_not_human_reviewed",
              let human = json["humanApproval"] as? NSNumber,
              CFGetTypeID(human) == CFBooleanGetTypeID(), human.boolValue == false,
              let rawEntries = json["entries"] as? [[String: Any]] else { return .invalidDeclared }
        var entries: [Entry] = []
        for raw in rawEntries {
            guard let data = try? JSONSerialization.data(withJSONObject: raw),
                  let item = try? JSONDecoder().decode(Entry.self, from: data) else { return .invalidDeclared }
            entries.append(item)
        }
        let keys = entries.map { "\($0.pageID)\u{0}\($0.locale)" }
        guard Set(keys).count == keys.count else { return .invalidDeclared }
        guard let entry = entries.first(where: { $0.pageID == pageID && $0.locale == selection.locale }) else { return .notDeclared }
        guard entry.week > 0 else { return .invalidDeclared }
        if let legacy = selection.legacy {
            // Legacy catalogs lack a v5 release identity. They may carry only an
            // exact-source tombstone; they never acquire remote guide content.
            guard entry.status == "revoked", let declared = entry.legacy,
                  declared.sourceIdSHA256 == legacy.sourceIdSHA256,
                  declared.sourceUrlSHA256 == legacy.sourceUrlSHA256,
                  declared.sourceMediaSHA256 == legacy.sourceMediaSHA256,
                  declared.sourceStartSeconds == legacy.sourceStartSeconds,
                  declared.sourceEndSeconds == legacy.sourceEndSeconds,
                  entry.editionId == nil, entry.sourceIdentitySha256 == nil,
                  entry.releasePackageJsonSha256 == nil,
                  hasApprovedBundleIdentity(selection: selection, origin: origin, week: entry.week)
            else { return .invalidDeclared }
            return .revoked
        }
        guard entry.legacy == nil, entry.editionId == selection.editionId,
              entry.sourceIdentitySha256 == selection.sourceIdentitySha256,
              entry.releasePackageJsonSha256 == selection.releasePackageJsonSha256 else { return .invalidDeclared }
        // A verified shipped week-five identity cannot bypass its content pin by
        // claiming a different week in the manifest.
        if hasApprovedBundleIdentity(selection: selection, origin: origin, week: 5), entry.week != 5 {
            return .invalidDeclared
        }
        if entry.status == "revoked" { return .revoked }
        guard entry.status == "available", let bytes = entry.bytes, bytes > 0, bytes <= guideLimit,
              let hash = entry.sha256, hash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              let path = entry.path, let resourceURL = publishedURL(path, origin: origin) else { return .invalidDeclared }
        let content: WeeklyGuideResponse
        do { content = try await fetch(resourceURL, origin, guideLimit) }
        catch { return .invalidDeclared }
        guard !Task.isCancelled, content.statusCode == 200, content.url == resourceURL,
              content.data.count == bytes, content.data.count <= guideLimit,
              sha256(content.data) == hash,
              let guide = try? JSONDecoder().decode(WeeklyGuide.self, from: content.data),
              guide.id == pageID, guide.week == entry.week, valid(guide) else { return .invalidDeclared }
        if let protection = protectedRevision(for: guide.week) {
            guard let payload = try? JSONSerialization.jsonObject(with: content.data) as? [String: Any] else {
                return .invalidDeclared
            }
            guard trustedProtectedRevision(revision: entry.richRevisionSHA256, payload: payload, protection: protection) else {
                return .outdatedRevision(guide.week)
            }
        }
        return .available(guide)
    }

    // These pages had incorrect table relationships in an earlier remote release.
    // Bind both the complete fallback text and the displayed blocks to reviewed
    // revisions; a server-supplied revision label by itself proves nothing.
    private struct ProtectedRevision {
        let sectionID: String
        let bodySHA: String
        let blocksSHA: String
    }
    private static func protectedRevision(for week: Int) -> ProtectedRevision? {
        switch week {
        case 5: return ProtectedRevision(sectionID: "page-83", bodySHA: "3fde88f36266fcf1224a93d3b6dfa0f6b87bf67aef93a974a093c522b75584d3", blocksSHA: "ec8728953968f528ccf562df53f354de35c4d578ce9c841563b71b0523d4322c")
        case 9: return ProtectedRevision(sectionID: "page-123", bodySHA: "3d10f079ec524da002721e170dba640ec0b4a2557b2ca36036f594d50e528d97", blocksSHA: "c75c35151a77ce52be0ba7cde8131f6a7042999b081fb488a8e44350a8180012")
        default: return nil
        }
    }
    private static func trustedProtectedRevision(revision: String?, payload: [String: Any],
                                                 protection: ProtectedRevision) -> Bool {
        let approved = ["0c327354029e9a92f22f03d07a11d153c825550c77f7cbf092edaa8c0b18d86a",
                        "df50f608d7a802052bdbf949aa3fb0988432c331a57a10c128160e9eb77c62de"]
        guard let revision, approved.contains(revision),
              payload["richRevisionSHA256"] as? String == revision,
              let sections = payload["sections"] as? [[String: Any]],
              let section = sections.first(where: { $0["id"] as? String == protection.sectionID }),
              let body = section["body"] as? String, sha256(Data(body.utf8)) == protection.bodySHA,
              let blocks = section["blocks"] as? [[String: Any]],
              let canonical = try? JSONSerialization.data(withJSONObject: blocks, options: [.sortedKeys, .withoutEscapingSlashes]),
              sha256(canonical) == protection.blocksSHA else { return false }
        return true
    }

    /// V2 languages are kept separate from the shipped Chinese v1 Bundle. The
    /// pinned hash identifies the extracted English source, not the original PDF.
    private static let extractedEnglishSHA = "3eb6cca50c898c8fcb82be73bcdce67deaad64267ad7041581e363aa39757708"

    private static func validSHA(_ value: String?) -> Bool {
        guard let value else { return false }
        return value.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil
    }

    private static func loadRemoteV2(selection: WeeklyGuideSelection, origin: URL,
                                     fetch: @escaping Fetch) async -> WeeklyGuideRemoteResult {
        guard ["ko", "es"].contains(selection.locale), selection.hasV5Identity,
              validSHA(selection.sourceIdentitySha256), validSHA(selection.releasePackageJsonSha256),
              let pageID = selection.pageID, validOrigin(origin),
              let manifestURL = URL(string: "/weekly-guides/manifest-v2.json", relativeTo: origin)?.absoluteURL else {
            return .manifestUnavailable
        }
        let response: WeeklyGuideResponse
        do { response = try await fetch(manifestURL, origin, manifestLimit) }
        catch { return .manifestUnavailable }
        guard !Task.isCancelled, response.statusCode == 200, response.data.count <= manifestLimit,
              response.url == manifestURL,
              let json = try? JSONSerialization.jsonObject(with: response.data) as? [String: Any],
              json["schemaVersion"] as? String == "tongxing-weekly-guide-manifest-v2" else { return .manifestUnavailable }
        guard json["seriesID"] as? String == "revelation-comfort-and-hope",
              let rawEntries = json["entries"] as? [[String: Any]] else { return .invalidDeclared }
        var entries: [Entry] = []
        for raw in rawEntries {
            guard let data = try? JSONSerialization.data(withJSONObject: raw),
                  let entry = try? JSONDecoder().decode(Entry.self, from: data) else { return .invalidDeclared }
            entries.append(entry)
        }
        let keys = entries.map { "\($0.pageID)\u{0}\($0.locale)" }
        guard Set(keys).count == keys.count else { return .invalidDeclared }
        guard let index = entries.firstIndex(where: { $0.pageID == pageID && $0.locale == selection.locale }) else { return .notDeclared }
        let entry = entries[index]
        guard entry.week > 0, entry.legacy == nil, entry.editionId == selection.editionId,
              entry.sourceIdentitySha256 == selection.sourceIdentitySha256,
              entry.releasePackageJsonSha256 == selection.releasePackageJsonSha256 else { return .invalidDeclared }
        if entry.status == "revoked" { return .revoked }
        let raw = rawEntries[index]
        guard entry.status == "available", let bytes = entry.bytes, bytes > 0, bytes <= guideLimit,
              let hash = entry.sha256, validSHA(hash),
              let path = entry.path, path == "/weekly-guides/published/\(hash).json",
              let resourceURL = publishedURL(path, origin: origin),
              raw["review"] as? String == "machine_translation_not_human_reviewed",
              isFalse(raw["humanApproval"]),
              raw["sourceSHA256"] as? String == extractedEnglishSHA,
              let translationSHA = raw["translationSHA256"] as? String, validSHA(translationSHA) else { return .invalidDeclared }
        let content: WeeklyGuideResponse
        do { content = try await fetch(resourceURL, origin, guideLimit) }
        catch { return .invalidDeclared }
        guard !Task.isCancelled, content.statusCode == 200, content.url == resourceURL,
              content.data.count == bytes, content.data.count <= guideLimit, sha256(content.data) == hash,
              let payload = try? JSONSerialization.jsonObject(with: content.data) as? [String: Any],
              payload["locale"] as? String == selection.locale,
              payload["review"] as? String == "machine_translation_not_human_reviewed",
              isFalse(payload["humanApproval"]), payload["sourceSHA256"] as? String == extractedEnglishSHA,
              payload["translationSHA256"] as? String == translationSHA,
              let guide = try? JSONDecoder().decode(WeeklyGuide.self, from: content.data),
              guide.id == pageID, guide.week == entry.week, valid(guide) else { return .invalidDeclared }
        return .available(guide)
    }

    private static func isFalse(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber else { return false }
        return CFGetTypeID(number) == CFBooleanGetTypeID() && !number.boolValue
    }

    private static func valid(_ guide: WeeklyGuide) -> Bool {
        guide.week > 0 && !guide.sections.isEmpty && Set(guide.sections.map(\.id)).count == guide.sections.count &&
        guide.sections.allSatisfy { !$0.id.isEmpty }
    }

    static func validOrigin(_ url: URL) -> Bool {
        guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return false }
        return c.scheme?.lowercased() == "https" && !(c.host ?? "").isEmpty &&
            c.user == nil && c.password == nil && c.query == nil && c.fragment == nil &&
            (c.port == nil || c.port == 443) && (c.path.isEmpty || c.path == "/")
    }

    static func sameOrigin(_ url: URL, _ origin: URL) -> Bool {
        guard validOrigin(origin), let a = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let b = URLComponents(url: origin, resolvingAgainstBaseURL: false) else { return false }
        return a.scheme?.lowercased() == "https" && a.host?.lowercased() == b.host?.lowercased() &&
            (a.port ?? 443) == (b.port ?? 443) && a.user == nil && a.password == nil
    }

    static func publishedURL(_ path: String, origin: URL) -> URL? {
        guard path.count <= 512,
              let match = path.range(of: "^/weekly-guides/published/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\\.json$", options: .regularExpression),
              match == (path.startIndex..<path.endIndex),
              let url = URL(string: path, relativeTo: origin)?.absoluteURL, sameOrigin(url, origin) else { return nil }
        return url
    }

    private static func fetchBounded(_ url: URL, origin: URL, limit: Int) async throws -> WeeklyGuideResponse {
        try await fetchBounded(url, origin: origin, limit: limit, configuration: .ephemeral)
    }

    static func fetchBounded(_ url: URL, origin: URL, limit: Int,
                             configuration: URLSessionConfiguration) async throws -> WeeklyGuideResponse {
        let session = URLSession(configuration: configuration, delegate: GuideRedirectGuard(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        // Keep verified-bundle offline fallback usable without a long blank wait.
        let timeout: TimeInterval = limit == manifestLimit ? 6 : 20
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (bytes, raw) = try await session.bytes(for: request)
        guard let response = raw as? HTTPURLResponse, let finalURL = response.url,
              finalURL == url, sameOrigin(finalURL, origin), response.statusCode == 200,
              response.expectedContentLength < 0 || response.expectedContentLength <= Int64(limit) else { throw URLError(.badServerResponse) }
        var data = Data()
        for try await byte in bytes {
            guard !Task.isCancelled, data.count < limit else { throw URLError(.dataLengthExceedsMaximum) }
            data.append(byte)
        }
        return WeeklyGuideResponse(data: data, url: finalURL, statusCode: response.statusCode)
    }

    private struct Collection: Decodable { let guides: [WeeklyGuide] }
    private struct Entry: Decodable {
        let pageID: String; let locale: String; let week: Int; let editionId: String?
        let sourceIdentitySha256: String?; let releasePackageJsonSha256: String?; let status: String
        let richRevisionSHA256: String?
        let path: String?; let sha256: String?; let bytes: Int?; let legacy: LegacyEntry?
    }
    private struct LegacyEntry: Decodable {
        let sourceIdSHA256: String; let sourceUrlSHA256: String; let sourceMediaSHA256: String
        let sourceStartSeconds: Double; let sourceEndSeconds: Double
    }
    private struct BundleBinding: Decodable {
        let week: Int; let pageID: String; let locale: String
        let editionId: String?; let sourceIdentitySha256: String?; let releasePackageJsonSha256: String?
        let sourceIdSHA256: String?; let sourceUrlSHA256: String?; let sourceMediaSHA256: String?
        let sourceStartSeconds: Double?; let sourceEndSeconds: Double?
    }

    // Identity metadata only: generated from HTTPS/hash-verified evidence
    // weekly-guide-identity-evidence-20261028/binding-evidence.json SHA-256
    // 33300aab94e4c57ec66f39ba1efcd311478db0e1348b5690f68b36ba108f9e15.
    // It binds only the exact shipped 99b494... Bundle to each origin's catalog;
    // v3/v4 alias evidence SHA-256: ba582a43435ee7565a61210e041b7af7ab06d0d1024ad8aeba89d41b23a1a030.
    // It is not a claim of human review or a signature on the cloud manifest.
    private static let bundledBindings = #"""
    {
      "https://ai-for-god-sermon-audio.web.app": [
        {
          "week": 3,
          "pageID": "2026-09-27-weekend-sermon-drive-530",
          "locale": "zh-Hans",
          "editionId": "2026-09-27-weekend-sermon-drive-530",
          "sourceIdentitySha256": "a0cf67203bae17bff080b2d1af41f88bdef786345a435021c2739d14f15394ac",
          "releasePackageJsonSha256": "32755dff59bd449c3199e760d6e280407d56bbd286fafd235ccf4adc94f8b675"
        },
        {
          "week": 4,
          "pageID": "resi-20261004-69ba7a66",
          "locale": "zh-Hans",
          "editionId": "resi-20261004-69ba7a66",
          "sourceIdentitySha256": "dc9104063404d44866f762c76af7449e4f8d25ca6dd03f2312b256fb32f88502",
          "releasePackageJsonSha256": "6d85d1c27c7cfcf676c9a77bdae55153389265e0056efe2e25ba2eec30e51063"
        },
        {
          "week": 5,
          "pageID": "resi-20261011-54475d42",
          "locale": "zh-Hans",
          "editionId": "resi-20261011-54475d42",
          "sourceIdentitySha256": "d1734702cf39394a3f283392043d0d33ed127302df393dc16b16d737ef320ec4",
          "releasePackageJsonSha256": "2503ca70abb2372d513bd9a14603d42b5aac6401d5cc0e635dbc988ec8c84e51"
        },
        {
          "week": 6,
          "pageID": "resi-20261018-15030286",
          "locale": "zh-Hans",
          "editionId": "resi-20261018-broadcast",
          "sourceIdentitySha256": "5dc7deb518491cef0d0c98c8c21b5c7f8aebc3730c13042afc6427b640f75e2c",
          "releasePackageJsonSha256": "3b0fbbfcd668b5379f837155080e6125e1ae3fb07d6b5bf4e3c46bee7861a4b5"
        },
        {
          "week": 7,
          "pageID": "revelation-jesus-wins-20261025",
          "locale": "zh-Hans",
          "editionId": "revelation-jesus-wins-20261025",
          "sourceIdentitySha256": "199e4b86e58c6456c462b41e359e72f3ccc61ad59bd78e296e8e8a8717504d35",
          "releasePackageJsonSha256": "4a40a4477447b6492232e36d350c8bcc34afd3e6da1b26875603b80a49cda8ce"
        },
        {
          "week": 1,
          "pageID": "2026-09-13-same_video-weekendlive-a9e91f52eb4c2484",
          "locale": "zh-Hans",
          "sourceIdSHA256": "40982af8843db9416e7162e1e6a78138b1e6880dec2dad65a5ec85cba950bce2",
          "sourceUrlSHA256": "a681ffe1ecd1c7dd1d8f18f15bf835d3663400aba7f828a3ec4755e02e986624",
          "sourceMediaSHA256": "a9e91f52eb4c24845d0e31f5300a352e8d4b84b59231b1c4ae5112aceb907567",
          "sourceStartSeconds": 1793,
          "sourceEndSeconds": 4033
        },
        {
          "week": 2,
          "pageID": "2026-09-20-same_video-7c193fd4-bc90-4f3b-aa00-37dfe8423aa0",
          "locale": "zh-Hans",
          "sourceIdSHA256": "1f7a8dceae03715cde50fd59e6f634b9b2fbd5d9ec20966d7418260a1b010a62",
          "sourceUrlSHA256": "a681ffe1ecd1c7dd1d8f18f15bf835d3663400aba7f828a3ec4755e02e986624",
          "sourceMediaSHA256": "728f864e92ea08dbce249249369016e0fee47950ec4e6dcb60cd6d83185e8caf",
          "sourceStartSeconds": 1789,
          "sourceEndSeconds": 3729
        },
        {
          "week": 6,
          "pageID": "resi-20261018-broadcast",
          "locale": "zh-Hans",
          "editionId": "resi-20261018-broadcast",
          "sourceIdentitySha256": "5dc7deb518491cef0d0c98c8c21b5c7f8aebc3730c13042afc6427b640f75e2c",
          "releasePackageJsonSha256": "3b0fbbfcd668b5379f837155080e6125e1ae3fb07d6b5bf4e3c46bee7861a4b5"
        }
      ],
      "https://ai-for-god-sermon-audio-dev.web.app": [
        {
          "week": 3,
          "pageID": "2026-09-27-weekend-sermon-drive-530",
          "locale": "zh-Hans",
          "editionId": "2026-09-27-weekend-sermon-drive-530",
          "sourceIdentitySha256": "a0cf67203bae17bff080b2d1af41f88bdef786345a435021c2739d14f15394ac",
          "releasePackageJsonSha256": "32755dff59bd449c3199e760d6e280407d56bbd286fafd235ccf4adc94f8b675"
        },
        {
          "week": 4,
          "pageID": "resi-20261004-69ba7a66",
          "locale": "zh-Hans",
          "editionId": "resi-20261004-69ba7a66",
          "sourceIdentitySha256": "dc9104063404d44866f762c76af7449e4f8d25ca6dd03f2312b256fb32f88502",
          "releasePackageJsonSha256": "0e886efc3a83ba9a58d4c808930b6b9955deedf02fc787eaa773c450d2e83df7"
        },
        {
          "week": 5,
          "pageID": "resi-20261011-54475d42",
          "locale": "zh-Hans",
          "editionId": "resi-20261011-54475d42",
          "sourceIdentitySha256": "d1734702cf39394a3f283392043d0d33ed127302df393dc16b16d737ef320ec4",
          "releasePackageJsonSha256": "2503ca70abb2372d513bd9a14603d42b5aac6401d5cc0e635dbc988ec8c84e51"
        },
        {
          "week": 6,
          "pageID": "resi-20261018-15030286",
          "locale": "zh-Hans",
          "editionId": "resi-20261018-broadcast",
          "sourceIdentitySha256": "5dc7deb518491cef0d0c98c8c21b5c7f8aebc3730c13042afc6427b640f75e2c",
          "releasePackageJsonSha256": "3b0fbbfcd668b5379f837155080e6125e1ae3fb07d6b5bf4e3c46bee7861a4b5"
        },
        {
          "week": 7,
          "pageID": "revelation-jesus-wins-20261025",
          "locale": "zh-Hans",
          "editionId": "revelation-jesus-wins-20261025",
          "sourceIdentitySha256": "199e4b86e58c6456c462b41e359e72f3ccc61ad59bd78e296e8e8a8717504d35",
          "releasePackageJsonSha256": "4a40a4477447b6492232e36d350c8bcc34afd3e6da1b26875603b80a49cda8ce"
        },
        {
          "week": 1,
          "pageID": "2026-09-13-same_video-weekendlive-a9e91f52eb4c2484",
          "locale": "zh-Hans",
          "sourceIdSHA256": "40982af8843db9416e7162e1e6a78138b1e6880dec2dad65a5ec85cba950bce2",
          "sourceUrlSHA256": "a681ffe1ecd1c7dd1d8f18f15bf835d3663400aba7f828a3ec4755e02e986624",
          "sourceMediaSHA256": "a9e91f52eb4c24845d0e31f5300a352e8d4b84b59231b1c4ae5112aceb907567",
          "sourceStartSeconds": 1793,
          "sourceEndSeconds": 4033
        },
        {
          "week": 2,
          "pageID": "2026-09-20-same_video-7c193fd4-bc90-4f3b-aa00-37dfe8423aa0",
          "locale": "zh-Hans",
          "sourceIdSHA256": "1f7a8dceae03715cde50fd59e6f634b9b2fbd5d9ec20966d7418260a1b010a62",
          "sourceUrlSHA256": "a681ffe1ecd1c7dd1d8f18f15bf835d3663400aba7f828a3ec4755e02e986624",
          "sourceMediaSHA256": "728f864e92ea08dbce249249369016e0fee47950ec4e6dcb60cd6d83185e8caf",
          "sourceStartSeconds": 1789,
          "sourceEndSeconds": 3729
        },
        {
          "week": 6,
          "pageID": "resi-20261018-broadcast",
          "locale": "zh-Hans",
          "editionId": "resi-20261018-broadcast",
          "sourceIdentitySha256": "5dc7deb518491cef0d0c98c8c21b5c7f8aebc3730c13042afc6427b640f75e2c",
          "releasePackageJsonSha256": "3b0fbbfcd668b5379f837155080e6125e1ae3fb07d6b5bf4e3c46bee7861a4b5"
        }
      ]
    }
    """#
}

final class GuideRedirectGuard: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
