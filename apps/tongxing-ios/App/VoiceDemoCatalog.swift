import CryptoKit
import Foundation

struct VoiceDemoCatalog: Decodable {
    struct Asset: Decodable {
        let path: String
        let sha256: String
        let bytes: Int?
        let text: String
        let transcriptStatus: String?
        let humanListeningStatus: String?
        let sourceUrl: String?
        let locale: String?
        let sourceClipId: String?
        let englishTextSha256: String?
        let durationSeconds: Double?

        init(path: String, sha256: String, bytes: Int?, text: String,
             transcriptStatus: String?, humanListeningStatus: String?,
             sourceUrl: String?, locale: String?, sourceClipId: String? = nil,
             englishTextSha256: String? = nil, durationSeconds: Double? = nil) {
            self.path = path; self.sha256 = sha256; self.bytes = bytes; self.text = text
            self.transcriptStatus = transcriptStatus; self.humanListeningStatus = humanListeningStatus
            self.sourceUrl = sourceUrl; self.locale = locale; self.sourceClipId = sourceClipId
            self.englishTextSha256 = englishTextSha256; self.durationSeconds = durationSeconds
        }

        private enum CodingKeys: String, CodingKey {
            case path, sha256, bytes, text, transcriptStatus, humanListeningStatus, sourceUrl, locale
            case sourceClipId, englishTextSha256, durationSeconds
        }

        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            path = try values.decode(String.self, forKey: .path)
            sha256 = try values.decode(String.self, forKey: .sha256)
            bytes = try values.decodeIfPresent(Int.self, forKey: .bytes)
            text = try values.decodeIfPresent(String.self, forKey: .text) ?? ""
            transcriptStatus = try values.decodeIfPresent(String.self, forKey: .transcriptStatus)
            humanListeningStatus = try values.decodeIfPresent(String.self, forKey: .humanListeningStatus)
            sourceUrl = try values.decodeIfPresent(String.self, forKey: .sourceUrl)
            locale = try values.decodeIfPresent(String.self, forKey: .locale)
            sourceClipId = try values.decodeIfPresent(String.self, forKey: .sourceClipId)
            englishTextSha256 = try values.decodeIfPresent(String.self, forKey: .englishTextSha256)
            durationSeconds = try values.decodeIfPresent(Double.self, forKey: .durationSeconds)
        }

        private var isVideo: Bool { path.hasSuffix(".mp4") }
        private var byteLimit: Int { isVideo ? 20_000_000 : 5_000_000 }

        func url(relativeTo origin: URL) -> URL {
            URL(string: path, relativeTo: origin)!.absoluteURL
        }

        func verify(_ data: Data) throws {
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard !data.isEmpty, data.count <= byteLimit,
                  bytes.map({ data.count == $0 }) ?? true,
                  digest == sha256 else { throw CocoaError(.fileReadCorruptFile) }
        }

        func verifiedLocalURL(origin: URL, session: URLSession, directory: URL) async throws -> URL {
            let source = url(relativeTo: origin)
            guard origin.scheme == "https", source.scheme == "https", source.host == origin.host,
                  source.port == origin.port, source.user == nil, source.password == nil,
                  source.query == nil, source.fragment == nil else { throw CocoaError(.fileReadNoPermission) }
            let file = directory.appendingPathComponent("\(sha256).\(isVideo ? "mp4" : "mp3")")
            if let cached = try? Data(contentsOf: file) {
                if (try? verify(cached)) != nil { return file }
                try? FileManager.default.removeItem(at: file)
            }
            var request = URLRequest(url: source)
            request.cachePolicy = .reloadIgnoringLocalCacheData
            request.timeoutInterval = 30
            let (data, response) = try await session.data(for: request)
            try Task.checkCancellation()
            guard (response as? HTTPURLResponse)?.statusCode == 200,
                  response.url?.scheme == "https", response.url?.host == origin.host,
                  response.url?.port == origin.port,
                  response.url?.user == nil, response.url?.password == nil,
                  response.url?.query == nil, response.url?.fragment == nil else { throw CocoaError(.fileReadUnknown) }
            if isVideo, let mime = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Type") {
                let mediaType = mime.split(separator: ";", maxSplits: 1).first?.trimmingCharacters(in: .whitespaces).lowercased()
                guard mediaType == "video/mp4" || mediaType == "application/octet-stream" else {
                    throw CocoaError(.fileReadCorruptFile)
                }
            }
            try verify(data)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try data.write(to: file, options: .atomic)
            do { try verify(Data(contentsOf: file)) }
            catch {
                try? FileManager.default.removeItem(at: file)
                throw error
            }
            return file
        }
    }

    struct Source: Decodable {
        let url: String
        let startSeconds: Double
        let endSeconds: Double
        let englishTextSha256: String
    }

    struct Speaker: Decodable, Identifiable {
        let speakerId: String
        let displayName: String
        let original: Asset
        let samples: [Asset]
        let clipId: String?
        let source: Source?
        let video: Asset?
        var id: String { speakerId }

        init(speakerId: String, displayName: String, original: Asset, samples: [Asset],
             clipId: String? = nil, source: Source? = nil, video: Asset? = nil) {
            self.speakerId = speakerId; self.displayName = displayName
            self.original = original; self.samples = samples
            self.clipId = clipId; self.source = source; self.video = video
        }
    }

    let schemaVersion: String
    let status: String
    let sourceScope: String
    let humanListeningStatus: String
    let speakerCount: Int
    let sampleCount: Int
    let speakers: [Speaker]

    var isProductionMerged: Bool { schemaVersion == "sermon-production-voice-auditions-v1" }

    var isSourceMatched: Bool { schemaVersion == "sermon-speaker-clip-demo-catalog-v2" }
    static let clipsRelativePath = "voice-demos/speaker-clips-v2/catalog.json"
    private static let clipsPrefix = "/voice-demos/speaker-clips-v2/"

    static let relativePath = "voice-demos/2026-09-21-v2/catalog.json"
    static let productionPath = "voice-demos/2026-09-21-v2/production-ko-es.json"
    private static let prefix = "/voice-demos/2026-09-21-v2/"
    private static let locales: Set<String> = ["zh-Hans", "ko", "es", "vi"]

    private struct PublishedWeekly: Decodable {
        let schemaVersion: String
        let voiceBank: VoiceBank
    }
    private struct VoiceBank: Decodable { let speakers: [BankSpeaker] }
    private struct BankSpeaker: Decodable {
        let id: String
        let name: String
        let humanListeningStatus: String
        let referenceSourceUrl: String
        let reference: BankTrack
        let chinese: BankTrack
    }
    private struct BankTrack: Decodable {
        struct Cue: Decodable { let text: String }
        let audioUrl: String
        let sha256: String
        let cues: [Cue]
        var text: String { cues.map(\.text).joined(separator: " ") }
    }
    private struct ProductionAuditions: Decodable {
        struct Speaker: Decodable {
            let speakerId: String
            let displayName: String
            let samples: [Asset]
        }
        let schemaVersion: String
        let status: String
        let sourceScope: String
        let humanListeningStatus: String
        let speakerCount: Int
        let sampleCount: Int
        let speakers: [Speaker]
    }

    private static func safePath(_ path: String, prefix: String) -> Bool {
        let allowed = CharacterSet(charactersIn:
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/")
        return path.hasPrefix(prefix) && path.hasSuffix(".mp3")
            && !path.contains("..") && !path.contains("//")
            && path.unicodeScalars.allSatisfy { allowed.contains($0) }
    }

    /// The Production web reader combines weekly voiceBank (English/Chinese)
    /// with the separately published Korean/Spanish auditions. Keep the same
    /// provenance split while returning one native display model.
    static func productionMerged(weeklyData: Data, auditionData: Data) throws -> VoiceDemoCatalog {
        let weekly = try JSONDecoder().decode(PublishedWeekly.self, from: weeklyData)
        let auditions = try JSONDecoder().decode(ProductionAuditions.self, from: auditionData)
        guard weekly.schemaVersion == "sermon-weekly-catalog-v1",
              auditions.schemaVersion == "sermon-production-voice-auditions-v1",
              auditions.status == "audition_demo",
              auditions.sourceScope == "voice_capability_audition_not_sermon_translation",
              auditions.humanListeningStatus == "pending",
              weekly.voiceBank.speakers.count == 6,
              auditions.speakerCount == 6, auditions.sampleCount == 12,
              auditions.speakers.count == 6,
              Set(weekly.voiceBank.speakers.map(\.id)).count == 6,
              Set(auditions.speakers.map(\.speakerId)).count == 6 else {
            throw CocoaError(.fileReadCorruptFile)
        }
        let byID = Dictionary(uniqueKeysWithValues: auditions.speakers.map { ($0.speakerId, $0) })
        let hex = CharacterSet(charactersIn: "0123456789abcdef")
        func validHash(_ value: String) -> Bool {
            value.count == 64 && value.unicodeScalars.allSatisfy { hex.contains($0) }
        }
        let speakers = try weekly.voiceBank.speakers.map { bank -> Speaker in
            guard let audition = byID[bank.id], audition.displayName == bank.name,
                  bank.humanListeningStatus == "accepted",
                  URL(string: bank.referenceSourceUrl)?.scheme == "https",
                  audition.samples.count == 2,
                  Set(audition.samples.compactMap(\.locale)) == Set(["ko", "es"]),
                  safePath(bank.reference.audioUrl, prefix: "/media/"),
                  safePath(bank.chinese.audioUrl, prefix: "/media/"),
                  validHash(bank.reference.sha256), validHash(bank.chinese.sha256),
                  !bank.reference.text.isEmpty, !bank.chinese.text.isEmpty else {
                throw CocoaError(.fileReadCorruptFile)
            }
            for sample in audition.samples {
                guard let locale = sample.locale,
                      sample.path == "\(prefix)\(bank.id)/\(locale).mp3",
                      safePath(sample.path, prefix: prefix),
                      validHash(sample.sha256),
                      sample.bytes.map({ $0 > 0 && $0 <= 5_000_000 }) == true,
                      sample.humanListeningStatus == "pending",
                      !sample.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                    throw CocoaError(.fileReadCorruptFile)
                }
            }
            let original = Asset(path: bank.reference.audioUrl, sha256: bank.reference.sha256,
                                 bytes: nil, text: bank.reference.text,
                                 transcriptStatus: "machine_screening_only", humanListeningStatus: nil,
                                 sourceUrl: bank.referenceSourceUrl, locale: nil)
            let chinese = Asset(path: bank.chinese.audioUrl, sha256: bank.chinese.sha256,
                                bytes: nil, text: bank.chinese.text,
                                transcriptStatus: nil, humanListeningStatus: "accepted",
                                sourceUrl: nil, locale: "zh-Hans")
            return Speaker(speakerId: bank.id, displayName: bank.name,
                           original: original, samples: [chinese] + audition.samples.sorted { $0.locale! < $1.locale! })
        }
        return VoiceDemoCatalog(schemaVersion: auditions.schemaVersion, status: auditions.status,
                                sourceScope: auditions.sourceScope,
                                humanListeningStatus: auditions.humanListeningStatus,
                                speakerCount: 6, sampleCount: 18, speakers: speakers)
    }

    static func validated(_ data: Data) throws -> VoiceDemoCatalog {
        let catalog = try JSONDecoder().decode(VoiceDemoCatalog.self, from: data)
        guard catalog.schemaVersion == "sermon-multilingual-voice-demo-public-v1",
              catalog.status == "audition_demo",
              catalog.sourceScope == "voice_capability_audition_not_sermon_translation",
              catalog.humanListeningStatus == "pending",
              catalog.speakerCount == 6, catalog.sampleCount == 24,
              catalog.speakers.count == 6,
              Set(catalog.speakers.map(\.speakerId)).count == 6 else {
            throw CocoaError(.fileReadCorruptFile)
        }
        var paths = Set<String>()
        for speaker in catalog.speakers {
            guard !speaker.speakerId.isEmpty, !speaker.displayName.isEmpty,
                  speaker.original.transcriptStatus == "machine_screening_only",
                  !speaker.original.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  speaker.original.sourceUrl.flatMap(URL.init(string:))?.scheme == "https",
                  speaker.samples.count == 4,
                  Set(speaker.samples.compactMap(\.locale)) == locales else {
                throw CocoaError(.fileReadCorruptFile)
            }
            for asset in [speaker.original] + speaker.samples {
                let allowed = CharacterSet(charactersIn:
                    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/")
                guard asset.path.hasPrefix(prefix), !asset.path.contains(".."),
                      !asset.path.contains("//"),
                      asset.path.unicodeScalars.allSatisfy({ allowed.contains($0) }),
                      asset.sha256.count == 64,
                      asset.sha256.unicodeScalars.allSatisfy({ CharacterSet(charactersIn: "0123456789abcdef").contains($0) }),
                      asset.bytes.map({ $0 > 0 && $0 <= 5_000_000 }) == true,
                      paths.insert(asset.path).inserted else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                if asset.locale != nil && (asset.humanListeningStatus != "pending"
                    || asset.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) {
                    throw CocoaError(.fileReadCorruptFile)
                }
            }
        }
        guard paths.count == 30 else { throw CocoaError(.fileReadCorruptFile) }
        return catalog
    }

    /// A matching excerpt is an explicit source/text/asset binding, never inferred
    /// from a speaker name or the existence of a translated audition.
    static func validatedClips(_ data: Data) throws -> VoiceDemoCatalog {
        let catalog = try JSONDecoder().decode(VoiceDemoCatalog.self, from: data)
        guard catalog.schemaVersion == "sermon-speaker-clip-demo-catalog-v2",
              catalog.status == "audition_demo",
              catalog.sourceScope == "source_clip_translation_audition_not_sermon_release",
              catalog.humanListeningStatus == "pending",
              catalog.speakerCount == 6, catalog.sampleCount == 18,
              catalog.speakers.count == 6,
              Set(catalog.speakers.map(\.speakerId)).count == 6 else {
            throw CocoaError(.fileReadCorruptFile)
        }
        let alphabet = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/")
        let hex = CharacterSet(charactersIn: "0123456789abcdef")
        func validHash(_ value: String) -> Bool {
            value.count == 64 && value.unicodeScalars.allSatisfy { hex.contains($0) }
        }
        func present(_ value: String) -> Bool {
            !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        var paths = Set<String>()
        var clips = Set<String>()
        for speaker in catalog.speakers {
            guard speaker.speakerId.range(of: "^[a-z0-9_]+$", options: .regularExpression) != nil, present(speaker.displayName),
                  let clipID = speaker.clipId, present(clipID), clips.insert(clipID).inserted,
                  let source = speaker.source, let video = speaker.video,
                  let sourceURL = URL(string: source.url), sourceURL.scheme == "https",
                  sourceURL.host?.isEmpty == false,
                  sourceURL.user == nil, sourceURL.password == nil,
                  source.startSeconds.isFinite, source.endSeconds.isFinite,
                  source.startSeconds > 0, source.endSeconds > source.startSeconds,
                  source.endSeconds - source.startSeconds <= 60,
                  validHash(source.englishTextSha256),
                  speaker.original.locale == "en",
                  speaker.original.transcriptStatus == "machine_screening_only",
                  present(speaker.original.text),
                  speaker.original.englishTextSha256 == source.englishTextSha256,
                  SHA256.hash(data: Data(speaker.original.text.utf8)).map({ String(format: "%02x", $0) }).joined() == source.englishTextSha256,
                  speaker.samples.count == 3,
                  Set(speaker.samples.compactMap(\.locale)) == Set(["zh-Hans", "ko", "es"]) else {
                throw CocoaError(.fileReadCorruptFile)
            }
            let window = source.endSeconds - source.startSeconds
            for asset in [speaker.original, video] + speaker.samples {
                let isVideo = asset.path.hasSuffix(".mp4")
                guard asset.path.hasPrefix(clipsPrefix), asset.path != clipsPrefix,
                      !asset.path.contains(".."), !asset.path.contains("//"),
                      asset.path.unicodeScalars.allSatisfy({ alphabet.contains($0) }),
                      asset.path.hasSuffix(asset.path == video.path ? ".mp4" : ".mp3"),
                      paths.insert(asset.path).inserted,
                      validHash(asset.sha256),
                      asset.bytes.map({ $0 > 0 && $0 <= (isVideo ? 20_000_000 : 5_000_000) }) == true,
                      asset.sourceClipId == clipID,
                      let duration = asset.durationSeconds, duration.isFinite,
                      duration > 0, duration <= 180 else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                if asset.path == video.path || asset.path == speaker.original.path {
                    guard abs(duration - window) <= 0.5 else { throw CocoaError(.fileReadCorruptFile) }
                } else {
                    guard asset.englishTextSha256 == source.englishTextSha256,
                          asset.humanListeningStatus == "pending", present(asset.text) else {
                        throw CocoaError(.fileReadCorruptFile)
                    }
                }
            }
        }
        guard clips.count == 6, paths.count == 30 else { throw CocoaError(.fileReadCorruptFile) }
        return catalog
    }

}
