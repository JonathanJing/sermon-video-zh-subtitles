import Testing
@testable import TongxingCore

struct SermonHeadingTests {
    @Test func identifiersNeverBecomeDisplayTitles() {
        for title in [nil, "", "resi-20261004-69ba7a66", "audio.mp3", "6B564139-08A5-4FF2-A218-29C247DD7B87"] {
            #expect(SermonHeading.displayTitle(title, pageID: "resi-20261004-69ba7a66", date: "2026-10-04", fallback: "证道") == "2026-10-04 · 证道")
        }
        #expect(SermonHeading.displayTitle("耶稣保守我们", pageID: "page", date: "2026-10-04", fallback: "证道") == "耶稣保守我们")
        #expect(SermonHeading.displayTitle(nil, pageID: "page", date: "2026-10-04", fallback: "Sermon") == "2026-10-04 · Sermon")
    }
    @Test func removesOnlyDeclaredSeriesAndRecognizedEdition() {
        let series = "启示录：耶稣带来的安慰与盼望"
        let formal = SermonHeading(title: "耶稣的应许 · \(series)｜正式播放版", series: series, speaker: "Eric Geiger")
        #expect(formal.title == "耶稣的应许")
        #expect(formal.series == series)
        #expect(formal.edition == "正式播放版")
        #expect(formal.details(date: "2026-09-20") == "2026-09-20 · Eric Geiger")
        let published = SermonHeading(title: "耶稣配得", series: series)
        #expect(published.title == "耶稣配得")
        let youtube = SermonHeading(title: "耶稣与你同在 · \(series)｜YouTube 版", series: series)
        #expect(youtube.title == "耶稣与你同在")
        #expect(youtube.edition == "YouTube 版")
    }

    @Test func preservesMeaningfulPunctuationAndNeverInventsMetadata() {
        let title = "信心 · 希望｜生命的新方向"
        let unknown = SermonHeading(title: title)
        #expect(unknown.title == title)
        #expect(unknown.series == nil && unknown.speaker == nil && unknown.edition == nil)
        #expect(unknown.details(date: "2026-09-27") == "2026-09-27")
        #expect(SermonHeading(title: title, series: "另一个系列", speaker: "  ").title == title)
        #expect(SermonHeading(title: "希望 · 盼望", series: "希望").title == "希望 · 盼望")
    }
}
