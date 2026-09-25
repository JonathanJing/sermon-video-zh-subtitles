import Foundation
import TongxingCore

/// Dev Hosting publishes immutable, hash-bound content JSON rather than a
/// standalone page asset. Render those reviewed bytes without enabling scripts.
struct FormalDevContentPage: Decodable {
    struct Cue: Decodable {
        let start: Double
        let end: Double
        let text: String
    }
    struct OutlineItem: Decodable {
        let title: String
        let body: String
    }

    let schemaVersion: String
    let pageId: String
    let sourceLocale: String
    let locale: String
    let targetLanguageCandidateJsonSha256: String
    let targetLanguageAudioPackageJsonSha256: String?
    let contentStatus: String
    let audioStatus: String
    let series: String
    let title: String
    let speaker: String
    let scripture: String
    let summary: String
    let date: String
    let durationSeconds: Double
    let outline: [OutlineItem]
    let cues: [Cue]

    static func decode(_ data: Data, package: TargetLanguageReleasePackage) throws -> Self {
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.schemaVersion == "sermon-formal-dev-content-v1",
              value.pageId == package.pageId, value.sourceLocale == "en",
              value.locale == package.targetLocale,
              value.targetLanguageCandidateJsonSha256 == package.targetLanguageCandidateJsonSha256,
              value.targetLanguageAudioPackageJsonSha256 == package.targetLanguageAudioPackageJsonSha256,
              value.contentStatus == "human_reviewed", value.audioStatus == package.audioStatus,
              !value.title.isEmpty, !value.series.isEmpty, !value.date.isEmpty,
              value.durationSeconds.isFinite, (7...14_400).contains(value.durationSeconds),
              !value.cues.isEmpty, value.cues.count <= 1_000,
              value.cues.allSatisfy({ $0.start.isFinite && $0.end.isFinite &&
                  $0.start >= 0 && $0.end > $0.start && $0.end <= value.durationSeconds + 0.1 &&
                  !$0.text.isEmpty && $0.text.count <= 8_000 }),
              zip(value.cues, value.cues.dropFirst()).allSatisfy({ $0.end <= $1.start }),
              value.outline.count <= 100
        else { throw ContentStorageError.invalidResponse }
        return value
    }

    var html: String {
        let outlineHTML = outline.map { item in
            "<li><strong>\(Self.escape(item.title))</strong> \(Self.escape(item.body))</li>"
        }.joined()
        let cueHTML = cues.map { cue in
            let seconds = Int(cue.start)
            let time = String(format: "%02d:%02d", seconds / 60, seconds % 60)
            return "<li><time>\(time)</time><p>\(Self.escape(cue.text))</p></li>"
        }.joined()
        return """
        <!doctype html><html lang="\(Self.escape(locale))"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{font:17px/1.65 -apple-system,BlinkMacSystemFont,sans-serif;max-width:760px;margin:auto;padding:22px;color:#172333;background:#fff}h1{font-size:1.6em;line-height:1.25}header p{color:#536171}section{margin-top:30px}ol{padding-left:1.4em}li{margin:12px 0}time{color:#52637b;font-size:.85em}li p{margin:2px 0 18px}footer{font-size:.8em;color:#667}</style>
        </head><body><header><p>\(Self.escape(series)) · \(Self.escape(date))</p>
        <h1>\(Self.escape(title))</h1><p>\(Self.escape(speaker)) · \(Self.escape(scripture))</p></header>
        <section><p>\(Self.escape(summary))</p><ol>\(outlineHTML)</ol></section>
        <section><h2>\(locale == "zh-Hans" ? "逐句内容" : locale == "ko" ? "자막" : "Subtítulos")</h2><ol>\(cueHTML)</ol></section>
        <footer>AI generated audio · Human reviewed content · Dev POC</footer></body></html>
        """
    }

    private static func escape(_ value: String) -> String {
        value.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&#39;")
    }
}
