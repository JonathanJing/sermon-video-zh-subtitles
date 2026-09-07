import Foundation

enum BlockIdentifier {
    static func isValid(_ value: String) -> Bool {
        !value.isEmpty && value.utf16.count <= 128 && value == value.trimmingCharacters(in: .whitespacesAndNewlines)
            && !value.unicodeScalars.contains { $0.value < 32 || $0.value == 127 }
    }
}

public struct BilingualTranscriptBlock: Codable, Sendable, Equatable {
    public let blockId: String
    public let english: String?
    public let chinese: String?
    public let sourceTextOrigin: String
    public let reviewState: String

    public init(blockId: String, english: String? = nil, chinese: String? = nil,
                sourceTextOrigin: String, reviewState: String) {
        self.blockId = blockId; self.english = english; self.chinese = chinese
        self.sourceTextOrigin = sourceTextOrigin; self.reviewState = reviewState
    }
}

public struct BilingualTranscript: Codable, Sendable, Equatable {
    public static let supportedSchemaVersion = "sermon-bilingual-transcript-v1"
    public let schemaVersion: String
    public let blocks: [BilingualTranscriptBlock]

    public init(schemaVersion: String = supportedSchemaVersion, blocks: [BilingualTranscriptBlock]) {
        self.schemaVersion = schemaVersion; self.blocks = blocks
    }

    public func validate(tracks: [SermonTrack]) throws {
        guard schemaVersion == Self.supportedSchemaVersion else { throw CatalogError.invalid("不支持的双语原文版本") }
        var ids = Set<String>()
        for block in blocks {
            let strings = [block.sourceTextOrigin, block.reviewState] + [block.english, block.chinese].compactMap { $0 }
            guard BlockIdentifier.isValid(block.blockId), ids.insert(block.blockId).inserted,
                  strings.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
            else { throw CatalogError.invalid("双语原文块标识或来源无效") }
        }
        if !ids.isEmpty {
            for cue in tracks.flatMap(\.cues) {
                if let id = cue.blockId, !ids.contains(id) { throw CatalogError.invalid("字幕块缺少对应原文来源") }
            }
        }
    }
}

public struct BilingualCueRow: Sendable, Equatable, Identifiable {
    public var id: Int { index }
    public let index: Int
    public let cue: SubtitleCue
    public let english: String?
    public let sourceTextOrigin: String?
    public let reviewState: String?
}

public struct BilingualTranscriptRows: Sendable, Equatable {
    public let rows: [BilingualCueRow]
    public let hasEnglish: Bool
    public let missingEnglish: Bool
}

extension SermonWeek {
    /// The full source block appears only after its last Chinese cue. Never
    /// align original English by array position, translation text, or duration.
    public func bilingualCueRows(for track: SermonTrack) -> BilingualTranscriptRows {
        var originals: [String: BilingualTranscriptBlock] = [:], ambiguous = Set<String>()
        if transcript?.schemaVersion == BilingualTranscript.supportedSchemaVersion {
            for block in transcript?.blocks ?? [] {
                if originals[block.blockId] != nil { ambiguous.insert(block.blockId) }
                originals[block.blockId] = block
            }
        }
        var lastCue: [String: Int] = [:]
        for (index, cue) in track.cues.enumerated() { if let id = cue.blockId { lastCue[id] = index } }
        var missingEnglish = false
        let rows = track.cues.enumerated().map { index, cue in
            let block = cue.blockId.flatMap { ambiguous.contains($0) ? nil : originals[$0] }
            let hasEnglish = !(block?.english?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true)
            if !hasEnglish { missingEnglish = true }
            return BilingualCueRow(index: index, cue: cue,
                english: hasEnglish && cue.blockId.flatMap({ lastCue[$0] }) == index ? block?.english : nil,
                sourceTextOrigin: hasEnglish ? block?.sourceTextOrigin : nil,
                reviewState: hasEnglish ? block?.reviewState : nil)
        }
        return BilingualTranscriptRows(rows: rows, hasEnglish: rows.contains { $0.english != nil }, missingEnglish: missingEnglish)
    }
}
