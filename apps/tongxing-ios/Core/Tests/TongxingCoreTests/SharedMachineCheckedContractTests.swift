import Foundation
import Testing
@testable import TongxingCore

/// The web reader and the native client must reproduce every `expected` value of
/// the shared machine-checked matrices. machine_checked means a bound machine
/// quality waiver passed; it is never a human approval.
struct SharedMachineCheckedContractTests {
    private let hashA = String(repeating: "a", count: 64)

    private func matrix() throws -> [String: Any] {
        let url = try #require(Bundle.module.url(forResource: "shared-machine-checked-contracts", withExtension: "json", subdirectory: "Fixtures"))
        let matrix = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        #expect(matrix["schemaVersion"] as? String == "sermon-shared-machine-checked-contract-fixtures-v1")
        #expect(matrix["scope"] as? String == "synthetic_decoder_tests_not_production_approval")
        return matrix
    }

    private func data(_ value: Any) throws -> Data { try JSONSerialization.data(withJSONObject: value, options: .sortedKeys) }

    private func releaseCase(_ id: String) throws -> [String: Any] {
        let cases = try #require(try matrix()["releases"] as? [[String: Any]])
        let row = try #require(cases.first { $0["id"] as? String == id })
        return try #require(row["release"] as? [String: Any])
    }

    @Test func identicalWebAndNativeMachineCheckedReleases() throws {
        let cases = try #require(try matrix()["releases"] as? [[String: Any]])
        #expect(cases.count == 19)
        for row in cases {
            let id = try #require(row["id"] as? String)
            let expected = try #require(row["expected"] as? String)
            let release = try #require(row["release"] as? [String: Any])
            let bytes = try data(release)
            #expect(["accept", "reject"].contains(expected), "fixture: \(id)")
            var package: TargetLanguageReleasePackage?
            var failure = "none"
            do { package = try TargetLanguageReleasePackage.decode(bytes) }
            catch { failure = String(describing: error) }
            #expect((package != nil) == (expected == "accept"), "fixture: \(id); decode error: \(failure)")
            // The Beta dev opt-in admits no additional v4 release: v4 is published only.
            var devAccepted = false
            do { _ = try TargetLanguageReleasePackage.decode(bytes, allowDevCandidate: true); devAccepted = true } catch { }
            #expect(devAccepted == (expected == "accept"), "fixture: \(id) with dev opt-in")
            if let package {
                #expect(package.schemaVersion == TargetLanguageReleasePackage.machineCheckedSchemaVersion, "fixture: \(id)")
                #expect(package.isMachineChecked, "fixture: \(id)")
                #expect(package.hasPublishedAudio, "fixture: \(id)")
                #expect(package.disclosure?.locale == package.targetLocale, "fixture: \(id)")
                #expect(package.reviewBasis != nil, "fixture: \(id)")
                #expect(package.deviceAcceptance.status == "not_run", "fixture: \(id)")
                #expect(package.venueAcceptance.status == "not_run", "fixture: \(id)")
            }
        }
    }

    @Test func identicalWebAndNativeMachineCheckedCatalogTargets() throws {
        let cases = try #require(try matrix()["catalogTargets"] as? [[String: Any]])
        #expect(cases.count == 12)
        for row in cases {
            let id = try #require(row["id"] as? String)
            let expected = try #require(row["expected"] as? String)
            let target = try #require(row["target"] as? [String: Any])
            let pageID = try #require(row["pageId"] as? String)
            let locale = try #require(row["locale"] as? String)
            #expect(["accept", "reject"].contains(expected), "fixture: \(id)")
            var decoded: PageTarget?
            var failure = "none"
            do {
                let value = try JSONDecoder().decode(PageTarget.self, from: data(target))
                try value.validate(pageID: pageID, locale: locale,
                                   catalogSchemaVersion: MultilingualCatalog.machineCheckedSchemaVersion)
                decoded = value
            } catch { failure = String(describing: error) }
            #expect((decoded != nil) == (expected == "accept"), "fixture: \(id); target error: \(failure)")

            // The same target inside a whole v4 catalog. Production keeps an
            // accepted machine-checked target visible and machine-checked.
            let binding = target["audioFingerprint"] as? [String: Any]
            let page: [String: Any] = [
                "id": pageID, "title": "Synthetic fixture", "date": "2026-09-30", "sourceLocale": "en",
                "sourceIdentitySha256": hashA,
                "sourceMediaSha256": (binding?["sourceSha256"] as? String) ?? String(repeating: "b", count: 64),
                "defaultTargetLocale": locale, "targets": [locale: target],
            ]
            let catalog: [String: Any] = [
                "schemaVersion": MultilingualCatalog.machineCheckedSchemaVersion,
                "generatedAt": "2026-09-30T00:00:00Z", "defaultPageId": pageID, "pages": [page],
            ]
            var production: MultilingualCatalog?
            failure = "none"
            do { production = try MultilingualCatalog.decode(data(catalog)) }
            catch { failure = String(describing: error) }
            #expect((production != nil) == (expected == "accept"), "fixture: \(id) in a v4 catalog; error: \(failure)")
            if let production, let decoded {
                #expect(production.isDualScript, "fixture: \(id)")
                #expect(production.defaultPage.targets[locale] == decoded, "fixture: \(id)")
                #expect(production.defaultPage.publishedTargets.map(\.locale) == [locale], "fixture: \(id)")
            }
            // A v3 catalog never routes a machine-checked target, on any path.
            if let decoded, decoded.isMachineChecked {
                #expect(throws: (any Error).self) {
                    try decoded.validate(pageID: pageID, locale: locale,
                                         catalogSchemaVersion: MultilingualCatalog.dualScriptSchemaVersion)
                }
            }
        }
    }

    @Test func identicalWebAndNativeMachineCheckedContent() throws {
        let cases = try #require(try matrix()["contents"] as? [[String: Any]])
        #expect(cases.count == 6)
        for row in cases {
            let id = try #require(row["id"] as? String)
            let expected = try #require(row["expected"] as? String)
            let content = try #require(row["content"] as? [String: Any])
            #expect(["accept", "reject"].contains(expected), "fixture: \(id)")
            var review: PublishedContentReview?
            var failure = "none"
            do { review = try PublishedContentReview.decode(data(content)) }
            catch { failure = String(describing: error) }
            #expect((review != nil) == (expected == "accept"), "fixture: \(id); decode error: \(failure)")
            if let review {
                #expect(review.status == content["status"] as? String, "fixture: \(id)")
                #expect((review.disclosure != nil) == (review.status == "machine_checked"), "fixture: \(id)")
                #expect(review.disclosure.map { $0.locale == review.targetLocale } ?? true, "fixture: \(id)")
            }
        }
    }

    // MARK: Production projection

    private func catalogTarget(_ locale: String, directory: String, content: String, audio: String,
                               capabilities: [String]) -> [String: Any] {
        ["releasePackageUrl": "/\(directory)/page-1/\(locale).json", "releasePackageJsonSha256": hashA,
         "contentStatus": content, "audioStatus": audio, "capabilities": capabilities]
    }

    private func mixedCatalog(schemaVersion: String = MultilingualCatalog.machineCheckedSchemaVersion) -> [String: Any] {
        [
            "schemaVersion": schemaVersion, "generatedAt": "2026-10-07T00:00:00Z", "defaultPageId": "page-1",
            "pages": [[
                "id": "page-1", "title": "Synthetic mixed page", "date": "2026-10-04", "sourceLocale": "en",
                "sourceIdentitySha256": hashA, "defaultTargetLocale": "es",
                "targets": [
                    "zh-Hans": catalogTarget("zh-Hans", directory: "releases-v2", content: "human_reviewed",
                                             audio: "human_reviewed", capabilities: ["text", "captions", "audio"]),
                    "ko": catalogTarget("ko", directory: "releases-v4", content: "machine_checked",
                                        audio: "machine_checked", capabilities: ["text", "captions", "audio"]),
                    "es": catalogTarget("es", directory: "releases-v2", content: "machine_reviewed",
                                        audio: "unavailable", capabilities: ["text"]),
                ],
            ]],
        ]
    }

    @Test func productionKeepsMachineCheckedButDropsDevMachineReviewed() throws {
        let bytes = try data(mixedCatalog())
        let production = try MultilingualCatalog.decode(bytes)
        let page = production.defaultPage
        #expect(production.schemaVersion == MultilingualCatalog.machineCheckedSchemaVersion)
        #expect(production.isDualScript)
        #expect(page.targets.keys.sorted() == ["ko", "zh-Hans"])
        #expect(page.publishedTargets.map(\.locale) == ["ko", "zh-Hans"])
        #expect(page.targets["ko"]?.isMachineChecked == true)
        #expect(page.targets["ko"]?.contentStatus == "machine_checked")
        #expect(page.targets["zh-Hans"]?.isMachineChecked == false)
        // The removed dev default falls back to a published locale.
        #expect(page.defaultTargetLocale == "ko")

        let dev = try MultilingualCatalog.decode(bytes, allowDevCandidates: true)
        #expect(dev.defaultPage.targets.keys.sorted() == ["es", "ko", "zh-Hans"])
        #expect(dev.defaultPage.publishedTargets.map(\.locale) == ["ko", "zh-Hans"])

        let all: [String: Set<String>] = ["page-1": ["es", "ko", "zh-Hans"]]
        let published = try dev.retainingPublishedLocales(all)
        #expect(published.defaultPage.targets.keys.sorted() == ["ko", "zh-Hans"])
        #expect(published.defaultPage.targets["ko"]?.contentStatus == "machine_checked")
        let verifiedOnlyKorean = try dev.retainingPublishedLocales(["page-1": ["ko"]])
        #expect(verifiedOnlyKorean.defaultPage.targets.keys.sorted() == ["ko"])
        #expect(try dev.retainingHumanLocales(all).defaultPage.targets.keys.sorted() == ["zh-Hans"])
    }

    @Test func machineCheckedTargetsNeedACatalogV4AndItsOwnReleaseDirectory() throws {
        // v3 cannot carry machine-checked targets at all.
        #expect(throws: (any Error).self) {
            try MultilingualCatalog.decode(data(mixedCatalog(schemaVersion: MultilingualCatalog.dualScriptSchemaVersion)))
        }
        var catalog = mixedCatalog()
        var pages = catalog["pages"] as! [[String: Any]]
        var targets = pages[0]["targets"] as! [String: [String: Any]]
        targets["ko"]!["releasePackageUrl"] = "/releases-v2/page-1/ko.json"
        pages[0]["targets"] = targets
        catalog["pages"] = pages
        #expect(throws: (any Error).self) { try MultilingualCatalog.decode(data(catalog)) }
        // A v4 catalog without machine-checked targets is still a valid human-only catalog.
        targets["ko"] = catalogTarget("ko", directory: "releases-v2", content: "human_reviewed",
                                      audio: "unavailable", capabilities: ["text"])
        pages[0]["targets"] = targets
        catalog["pages"] = pages
        let human = try MultilingualCatalog.decode(data(catalog))
        #expect(human.defaultPage.targets.values.allSatisfy { !$0.isMachineChecked })
    }

    // MARK: Content v3 through a v4 release

    private func transcriptFixture(release id: String) throws -> (TargetLanguageReleasePackage, MultilingualPage) {
        let package = try TargetLanguageReleasePackage.decode(data(releaseCase(id)))
        let directory = package.isMachineChecked ? "releases-v4" : "releases-v2"
        let sourceIdentity = try #require(package.englishSourcePackageJsonSha256)
        let sourceMedia = try #require(package.sourceIdentity?.mediaSha256)
        let page = try JSONDecoder().decode(MultilingualPage.self, from: data([
            "id": package.pageId, "title": "Synthetic machine page", "date": "2026-10-04", "sourceLocale": "en",
            "sourceIdentitySha256": sourceIdentity, "sourceMediaSha256": sourceMedia,
            "defaultTargetLocale": package.targetLocale,
            "targets": [package.targetLocale: [
                "releasePackageUrl": "/\(directory)/\(package.pageId)/\(package.targetLocale).json",
                "releasePackageJsonSha256": hashA, "contentStatus": package.contentStatus,
                "audioStatus": package.audioStatus, "capabilities": ["text", "captions", "audio"],
            ]],
        ] as [String: Any]))
        try page.validate(catalogSchemaVersion: MultilingualCatalog.machineCheckedSchemaVersion)
        return (package, page)
    }

    private func content(_ package: TargetLanguageReleasePackage, page: MultilingualPage,
                         schemaVersion: String = PublishedContentReview.machineCheckedSchemaVersion,
                         status: String, disclosure: MachineCheckedDisclosure?) throws -> Data {
        let sourceMedia = try #require(page.sourceMediaSha256)
        var value: [String: Any] = [
            "schemaVersion": schemaVersion, "pageId": page.id, "targetLocale": package.targetLocale,
            "sourceLocale": "en", "status": status, "durationSeconds": 10, "audioDurationSeconds": 9.5,
            "reviewMode": "formal", "title": "Synthetic machine-checked title",
            "englishSourcePackageJsonSha256": page.sourceIdentitySha256,
            "targetLanguageCandidateJsonSha256": package.targetLanguageCandidateJsonSha256,
            "sourceMediaSha256": sourceMedia,
            "summary": "Synthetic summary", "questions": ["Synthetic question"],
            "cues": [["textGroupId": "g1", "sourceUnitIds": ["u1"], "text": "Synthetic sentence.", "start": 0, "end": 10]],
        ]
        if let disclosure {
            value["disclosure"] = ["locale": disclosure.locale, "text": disclosure.text, "english": disclosure.english]
        }
        return try data(value)
    }

    private func captions() throws -> Data {
        let value: [String: Any] = [
            "cues": [["textGroupId": "g1", "text": "Synthetic spoken sentence.", "start": 0, "end": 9.5]],
        ]
        return try data(value)
    }

    @Test func machineCheckedContentReadsOnlyThroughAMatchingV4Release() throws {
        let (package, page) = try transcriptFixture(release: "machine-checked-ko")
        let disclosure = try #require(package.disclosure)
        let result = try VerifiedPublishedTranscript.decode(
            content: content(package, page: page, status: "machine_checked", disclosure: disclosure),
            captions: captions(), package: package, page: page)
        #expect(result.contentStatus == "machine_checked")
        #expect(result.audioStatus == "machine_checked")
        #expect(result.isMachineChecked)
        #expect(result.disclosure == disclosure)
        // Study fields inside machine-checked text are never presented as reviewed.
        #expect(result.summary == nil)
        #expect(result.questions.isEmpty)
        #expect(result.fullText.map(\.text) == ["Synthetic sentence."])
        #expect(result.captions.map(\.text) == ["Synthetic spoken sentence."])

        let otherLocale = MachineCheckedDisclosure(locale: "es", text: "Otro idioma.", english: "Other locale.")
        let otherWording = MachineCheckedDisclosure(locale: disclosure.locale, text: "Different wording.",
                                                    english: disclosure.english)
        let rejected: [Data] = try [
            // Content status must equal the release content status.
            content(package, page: page, status: "human_reviewed", disclosure: nil),
            // Machine-checked content must carry its same-locale disclosure.
            content(package, page: page, status: "machine_checked", disclosure: nil),
            content(package, page: page, status: "machine_checked", disclosure: otherLocale),
            // ... and the very disclosure of its release.
            content(package, page: page, status: "machine_checked", disclosure: otherWording),
            // Content v2 cannot declare machine_checked.
            content(package, page: page, schemaVersion: "sermon-full-video-text-content-v2",
                    status: "machine_checked", disclosure: nil),
        ]
        for bytes in rejected {
            #expect(throws: (any Error).self) {
                try VerifiedPublishedTranscript.decode(content: bytes, captions: captions(), package: package, page: page)
            }
        }
    }

    @Test func humanTextWithMachineCheckedAudioKeepsHumanTextStatus() throws {
        let (package, page) = try transcriptFixture(release: "human-text-machine-audio")
        #expect(package.contentStatus == "human_reviewed")
        #expect(package.audioStatus == "machine_checked")
        for schemaVersion in ["sermon-full-video-text-content-v2", PublishedContentReview.machineCheckedSchemaVersion] {
            let result = try VerifiedPublishedTranscript.decode(
                content: content(package, page: page, schemaVersion: schemaVersion, status: "human_reviewed", disclosure: nil),
                captions: captions(), package: package, page: page)
            #expect(result.contentStatus == "human_reviewed")
            #expect(result.audioStatus == "machine_checked")
            #expect(result.isMachineChecked)
            #expect(result.disclosure == package.disclosure)
            #expect(result.summary == "Synthetic summary")
        }
        let disclosure = try #require(package.disclosure)
        #expect(throws: (any Error).self) {
            try VerifiedPublishedTranscript.decode(
                content: content(package, page: page, status: "machine_checked", disclosure: disclosure),
                captions: captions(), package: package, page: page)
        }
    }

    @Test func olderReleasesCannotDeclareMachineCheckedFields() throws {
        var release = try releaseCase("machine-checked-ko")
        release["schemaVersion"] = TargetLanguageReleasePackage.fourProductSchemaVersion
        release["contentStatus"] = "human_reviewed"
        release["audioStatus"] = "human_reviewed"
        // A v3 release with v4-only fields is rejected; without them it is a valid v3 release.
        #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data(release)) }
        release.removeValue(forKey: "reviewBasis")
        #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data(release)) }
        release.removeValue(forKey: "disclosure")
        let v3 = try TargetLanguageReleasePackage.decode(data(release))
        #expect(!v3.isMachineChecked)
        #expect(v3.disclosure == nil)
        release["contentStatus"] = "machine_checked"
        #expect(throws: (any Error).self) { try TargetLanguageReleasePackage.decode(data(release)) }
    }
}
