import CryptoKit
import Foundation
import Testing
@testable import TongxingCore

struct DevCandidateCatalogTests {
    private func readback() throws -> [String: Any] {
        let url = try #require(Bundle.module.url(forResource: "dev-candidate-catalog-readback", withExtension: "json", subdirectory: "Fixtures"))
        return try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    }
    private func data(_ value: Any) throws -> Data { try JSONSerialization.data(withJSONObject: value) }

    @Test func frozenRealDevCatalogKeepsHumanLocalesIndependentAndMachineStateIntact() throws {
        let fixture = try readback(), catalog = try #require(fixture["catalog"] as? [String: Any])
        let production = try MultilingualCatalog.decode(data(catalog))
        let dev = try MultilingualCatalog.decode(data(catalog), allowDevCandidates: true)
        #expect(production.pages.count == 2)
        #expect(production.pages[1].targets.keys.sorted() == ["zh-Hans"])
        #expect(dev.pages[1].targets.keys.sorted() == ["es", "ko", "zh-Hans"])
        #expect(dev.pages[1].targets["ko"]?.contentStatus == "machine_reviewed")
        #expect(dev.pages[1].publishedTargets.map(\.locale) == ["zh-Hans"])
        #expect(dev.defaultPageId == production.defaultPageId)
    }

    @Test func hiddenDefaultsFallBackByPageAndLocaleWithoutUsingTitle() throws {
        var catalog = try #require(try readback()["catalog"] as? [String: Any])
        var pages = catalog["pages"] as! [[String: Any]]
        pages[0]["diagnosticOnly"] = true
        pages[1]["defaultTargetLocale"] = "ko"
        pages[1]["title"] = "[DEV] does not control admission"
        catalog["pages"] = pages
        let production = try MultilingualCatalog.decode(data(catalog))
        #expect(production.pages.count == 1)
        #expect(production.defaultPageId == pages[1]["id"] as? String)
        #expect(production.defaultPage.defaultTargetLocale == "zh-Hans")
        #expect(try MultilingualCatalog.decode(data(catalog), allowDevCandidates: true).pages.count == 2)
        pages[1]["simulationOnly"] = true
        catalog["pages"] = pages
        #expect(throws: (any Error).self) { try MultilingualCatalog.decode(data(catalog)) }
    }

    @Test func filteredMachineTargetsStillRequireValidIdentityAndKnownStatus() throws {
        for mutation in ["bad-path", "unknown-status", "duplicate-id"] {
            var catalog = try #require(try readback()["catalog"] as? [String: Any])
            var pages = catalog["pages"] as! [[String: Any]]
            var targets = pages[1]["targets"] as! [String: [String: Any]]
            if mutation == "bad-path" { targets["ko"]!["releasePackageUrl"] = "/releases-v2/wrong/ko.json" }
            if mutation == "unknown-status" { targets["ko"]!["contentStatus"] = "approved_by_machine" }
            if mutation == "duplicate-id" { pages[1]["id"] = pages[0]["id"] }
            pages[1]["targets"] = targets
            catalog["pages"] = pages
            #expect(throws: (any Error).self) { try MultilingualCatalog.decode(data(catalog)) }
        }
    }

    @Test func realCandidatesRequireDevOptInAndNeverBecomePublishedOrHumanReviewed() throws {
        let releases = try #require(try readback()["releases"] as? [String: [String: Any]])
        for locale in ["zh-Hans", "ko", "es"] {
            let value = try #require(releases[locale]), bytes = try data(value)
            #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(bytes) }
            let package = try TargetLanguageReleasePackage.decode(bytes, allowDevCandidate: true)
            #expect(package.status == "candidate")
            #expect(package.contentStatus == (locale == "zh-Hans" ? "human_reviewed" : "machine_reviewed"))
            #expect(package.httpVerification.status == "not_run")
            #expect(package.deviceAcceptance.status == "not_run")
            #expect(package.venueAcceptance.status == "not_run")
            var acceptedDevice = value
            acceptedDevice["deviceAcceptance"] = ["status": "pass", "evidenceSha256": String(repeating: "a", count: 64)]
            #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data(acceptedDevice), allowDevCandidate: true) }
            var wrongAudio = value
            wrongAudio["assets"] = (value["assets"] as! [[String: Any]]).map { asset in
                var changed = asset
                if changed["role"] as? String == "audio" { changed["path"] = "/media/wrong/\(locale).wav" }
                return changed
            }
            #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data(wrongAudio), allowDevCandidate: true) }
        }
        var machine = try #require(releases["ko"])
        machine.removeValue(forKey: "audioHumanReviewReceiptJsonSha256")
        #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data(machine), allowDevCandidate: true) }
        machine = try #require(releases["ko"])
        machine["status"] = "published_http_verified"
        machine["httpVerification"] = ["status": "pass", "evidenceSha256": String(repeating: "a", count: 64)]
        #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data(machine), allowDevCandidate: true) }
    }

    @Test func pr232DualScriptCandidateExtensionIsCompatibleWithoutWideningProduction() throws {
        let releases = try #require(try readback()["releases"] as? [String: [String: Any]])
        for ext in ["wav", "m4a", "mp3"] {
            var value = try #require(releases["zh-Hans"])
            value["assets"] = (value["assets"] as! [[String: Any]]).map { asset in
                var changed = asset
                if changed["role"] as? String == "audio" { changed["path"] = "/media/if-i-had-more-time-jesus-is-worthy/zh-Hans.\(ext)" }
                return changed
            }
            #expect(try TargetLanguageReleasePackage.decode(data(value), allowDevCandidate: true).status == "candidate")
            value["status"] = "published_http_verified"
            value["httpVerification"] = ["status": "pass", "evidenceSha256": String(repeating: "a", count: 64)]
            if ext == "mp3" { #expect(try TargetLanguageReleasePackage.decode(data(value)).contentStatus == "human_reviewed") }
            else { #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data(value), allowDevCandidate: true) } }
        }
    }

    @Test func syntheticCandidateTranscriptRequiresExplicitContextAndExactAudioClockBinding() throws {
        let fixture = try readback()
        let catalog = try MultilingualCatalog.decode(data(fixture["catalog"]!), allowDevCandidates: true)
        let page = catalog.pages[1]
        let releases = try #require(fixture["releases"] as? [String: [String: Any]])
        for locale in ["zh-Hans", "ko", "es"] {
            let package = try TargetLanguageReleasePackage.decode(data(releases[locale]!), allowDevCandidate: true)
            let cue: [String: Any] = ["textGroupId": "synthetic-1", "sourceUnitIds": ["source-1"],
                                      "start": 0.0, "end": 9.0, "text": "Synthetic text"]
            let content: [String: Any] = [
                "schemaVersion": locale == "zh-Hans" ? "sermon-formal-dev-content-v1" : "sermon-dev-podcast-candidate-content-v2",
                "pageId": page.id, "sourceLocale": "en", "locale": locale, "contentStatus": package.contentStatus,
                "audioStatus": package.audioStatus, "date": page.date,
                "englishSourcePackageJsonSha256": page.sourceIdentitySha256,
                "targetLanguageCandidateJsonSha256": package.targetLanguageCandidateJsonSha256,
                "targetLanguageAudioPackageJsonSha256": package.targetLanguageAudioPackageJsonSha256!,
                "durationSeconds": 10.0, "title": "Synthetic candidate", "cues": [cue],
            ]
            var captions: [String: Any] = ["schemaVersion": "sermon-target-language-captions-v1", "pageId": page.id,
                "locale": locale, "audioPackageJsonSha256": package.targetLanguageAudioPackageJsonSha256!,
                "timingBasis": "concatenated target audio; natural unit durations; no source-video synchronization", "cues": [cue]]
            #expect(throws: (any Error).self) {
                try VerifiedPublishedTranscript.decode(content: data(content), captions: data(captions), package: package, page: page)
            }
            let result = try VerifiedPublishedTranscript.decode(content: data(content), captions: data(captions), package: package, page: page, allowDevCandidate: true)
            #expect(result.contentStatus == package.contentStatus)
            #expect(result.releaseStatus == "candidate")
            captions["timingBasis"] = "source_video_aligned"
            #expect(throws: (any Error).self) {
                try VerifiedPublishedTranscript.decode(content: data(content), captions: data(captions), package: package, page: page, allowDevCandidate: true)
            }
        }
    }

    // Full public manuscripts remain outside Git. This opt-in replay uses the
    // frozen byte evidence, never network requests, devices, or user caches.
    @Test(.enabled(if: ProcessInfo.processInfo.environment["TONGXING_DEV_CATALOG_FIXTURE_ROOT"] != nil))
    func frozenRealThreeLocaleContentAndCaptionsReadThroughCurrentCore() throws {
        let path = try #require(ProcessInfo.processInfo.environment["TONGXING_DEV_CATALOG_FIXTURE_ROOT"])
        let root = URL(fileURLWithPath: path)
        let catalog = try MultilingualCatalog.decode(Data(contentsOf: root.appendingPathComponent("multilingual-v3.json")), allowDevCandidates: true)
        let page = try #require(catalog.pages.first { $0.id == "if-i-had-more-time-jesus-is-worthy" })
        func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
        for locale in ["zh-Hans", "ko", "es"] {
            let target = try #require(page.targets[locale])
            let releaseData = try Data(contentsOf: root.appendingPathComponent(String(target.releasePackageUrl.dropFirst())))
            #expect(hash(releaseData) == target.releasePackageJsonSha256)
            let package = try TargetLanguageReleasePackage.decode(releaseData, allowDevCandidate: true)
            func asset(_ role: ReleaseAsset.Role) throws -> Data {
                let asset = try #require(package.assets.first { $0.role == role })
                let bytes = try Data(contentsOf: root.appendingPathComponent(String(asset.path.dropFirst())))
                #expect(hash(bytes) == asset.sha256)
                return bytes
            }
            let content = try asset(.content), captions = try asset(.captions)
            #expect(throws: (any Error).self) {
                try VerifiedPublishedTranscript.decode(content: content, captions: captions, package: package, page: page)
            }
            let decoded = try VerifiedPublishedTranscript.decode(content: content, captions: captions, package: package, page: page, allowDevCandidate: true)
            #expect(decoded.fullText.count == 839)
            #expect(decoded.captions.count == 839)
            #expect(decoded.contentStatus == package.contentStatus)
            #expect(decoded.releaseStatus == "candidate")
            #expect(decoded.captions.allSatisfy { $0.english == nil })
            var wrong = try #require(JSONSerialization.jsonObject(with: captions) as? [String: Any])
            wrong["audioPackageJsonSha256"] = String(repeating: "a", count: 64)
            #expect(throws: (any Error).self) {
                try VerifiedPublishedTranscript.decode(content: content, captions: data(wrong), package: package, page: page, allowDevCandidate: true)
            }
        }
    }
}
