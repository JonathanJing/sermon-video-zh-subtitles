import Foundation

public enum FingerprintError: Error, LocalizedError, Equatable, Sendable {
    case invalidAudio(String)
    case invalidIndex(String)
    public var errorDescription: String? {
        switch self {
        case .invalidAudio(let detail): return "声音采样无效：\(detail)"
        case .invalidIndex(let detail): return "声音定位数据无效：\(detail)"
        }
    }
}

public struct FingerprintAlgorithm: Codable, Sendable, Equatable {
    public let name: String
    public let version: Int
    public let sampleRate: Int
    public let fftSize: Int
    public let hopSize: Int
    public let minBin: Int
    public let maxBin: Int
    public let frequencyRadius: Int
    public let timeRadius: Int
    public let tileFrames: Int
    public let peaksPerTile: Int
    public let minProminenceDb: Double
    public let pairMinFrames: Int
    public let pairMaxFrames: Int
    public let fanout: Int
    public let frequencyQuantization: Int
    public let deltaQuantization: Int

    public static let supported = FingerprintAlgorithm(name: "spectral-landmark-pairs", version: 1,
        sampleRate: 8000, fftSize: 1024, hopSize: 256, minBin: 25, maxBin: 410,
        frequencyRadius: 5, timeRadius: 3, tileFrames: 8, peaksPerTile: 6,
        minProminenceDb: 6, pairMinFrames: 5, pairMaxFrames: 63, fanout: 10,
        frequencyQuantization: 3, deltaQuantization: 2)
}

public struct FingerprintReferenceSource: Codable, Sendable, Equatable {
    public let sourceId: String
    public let referenceAudioSha256: String
    public let sourceVideoOffsetSeconds: Double
    public let timeOrigin: String
    public let timeline: String
    public let reviewState: String
}

/// Decodes the exact browser-generated v1 index. Prepared postings are immutable
/// values that can move to a detached matching task without shared mutable state.
public struct FingerprintIndex: Codable, Sendable {
    public static let supportedSchemaVersion = "sermon-audio-fingerprint-v1"
    public let schemaVersion: String
    public let durationSeconds: Double
    public let algorithm: FingerprintAlgorithm
    public let landmarkCount: Int
    public let pairCount: Int
    public let encoding: String
    public let postings: String
    public let method: String
    public let source: FingerprintReferenceSource
    let lookup: [UInt32: [Int]]

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, durationSeconds, algorithm, landmarkCount, pairCount, encoding, postings, method, source
    }

    public static func decode(_ data: Data) throws -> FingerprintIndex {
        guard !data.isEmpty, data.count <= 8 * 1024 * 1024 else { throw FingerprintError.invalidIndex("文件大小超出范围") }
        try Task.checkCancellation()
        return try JSONDecoder().decode(FingerprintIndex.self, from: data)
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try values.decode(String.self, forKey: .schemaVersion)
        durationSeconds = try values.decode(Double.self, forKey: .durationSeconds)
        algorithm = try values.decode(FingerprintAlgorithm.self, forKey: .algorithm)
        landmarkCount = try values.decode(Int.self, forKey: .landmarkCount)
        pairCount = try values.decode(Int.self, forKey: .pairCount)
        encoding = try values.decode(String.self, forKey: .encoding)
        postings = try values.decode(String.self, forKey: .postings)
        method = try values.decode(String.self, forKey: .method)
        source = try values.decode(FingerprintReferenceSource.self, forKey: .source)
        guard schemaVersion == Self.supportedSchemaVersion, algorithm == .supported,
              encoding == "u32le-pairs-base64", method == SermonAudioAlignment.supportedMethod,
              durationSeconds.isFinite, (5...14_400).contains(durationSeconds),
              Validation.identifier(source.sourceId), source.sourceId.utf8.count <= 128,
              Validation.sha256(source.referenceAudioSha256), source.sourceVideoOffsetSeconds.isFinite,
              source.sourceVideoOffsetSeconds >= 0, source.timeOrigin == "approved_sermon_clip_start",
              source.timeline == "source_clip", source.reviewState == "candidate"
        else { throw FingerprintError.invalidIndex("版本、算法或来源不符") }
        let maximumLandmarks = Int(ceil(durationSeconds / 0.032 / 8 + 1)) * 6
        guard landmarkCount >= 0, landmarkCount <= maximumLandmarks,
              pairCount >= 0, pairCount <= landmarkCount * 10,
              postings.utf8.count == 4 * ((pairCount * 8 + 2) / 3),
              let bytes = Data(base64Encoded: postings), bytes.count == pairCount * 8
        else { throw FingerprintError.invalidIndex("索引长度不符") }
        var prepared: [UInt32: [Int]] = [:]
        prepared.reserveCapacity(min(pairCount, 150_000))
        let decodedPairCount = pairCount, decodedDuration = durationSeconds
        try bytes.withUnsafeBytes { buffer in
            var previousHash: UInt32 = 0, previousTime = -1
            for i in 0..<decodedPairCount {
                if i % 4096 == 0 { try Task.checkCancellation() }
                let hash = UInt32(littleEndian: buffer.loadUnaligned(fromByteOffset: i * 8, as: UInt32.self))
                let time = Int(UInt32(littleEndian: buffer.loadUnaligned(fromByteOffset: i * 8 + 4, as: UInt32.self)))
                guard hash >= previousHash, hash != previousHash || time >= previousTime,
                      hash < (1 << 22), Double(time) * 0.032 < decodedDuration
                else { throw FingerprintError.invalidIndex("索引顺序或时间无效") }
                prepared[hash, default: []].append(time)
                previousHash = hash; previousTime = time
            }
        }
        lookup = prepared
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(schemaVersion, forKey: .schemaVersion)
        try values.encode(durationSeconds, forKey: .durationSeconds)
        try values.encode(algorithm, forKey: .algorithm)
        try values.encode(landmarkCount, forKey: .landmarkCount)
        try values.encode(pairCount, forKey: .pairCount)
        try values.encode(encoding, forKey: .encoding)
        try values.encode(postings, forKey: .postings)
        try values.encode(method, forKey: .method)
        try values.encode(source, forKey: .source)
    }

    public func validate(alignment: SermonAudioAlignment) throws {
        try alignment.validate()
        guard method == alignment.method, source.sourceId == alignment.sourceId,
              source.referenceAudioSha256 == alignment.referenceAudioSha256,
              source.sourceVideoOffsetSeconds == alignment.sourceVideoOffsetSeconds,
              source.timeOrigin == alignment.timeOrigin, source.timeline == alignment.timeline,
              source.reviewState == alignment.reviewState,
              abs(durationSeconds - alignment.referenceDurationSeconds) <= 0.2
        else { throw FingerprintError.invalidIndex("参考音频、周次或时间来源不符") }
    }
}
