# Shared videoDelivery catalog admission matrix

This tests-only extension to the [shared client contract evidence](shared-client-release-contracts.zh.md)
uses one [61-case JSON fixture](../apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-video-delivery.json).
It was scoped against `dev@63c0a18040b7f7744b334cebdb31778de228b064` and does not change any runtime, schema,
production state, UI, or CI workflow. The existing release, catalog and text-only matrices remain separate.

## Three independent outcomes

- `schemaAcceptance`: the current catalog v3 JSON Schema, with date/date-time format checking
- `webAcceptance`: `validatePublishedCatalogHeader`, `validatePublishedPage` and `validatePublishedTarget`,
  the catalog gates actually called by the published Web loader
- `swiftAcceptance`: `MultilingualCatalog.decode`, including its existing catalog/page/target validation

Every row records all three outcomes explicitly. The Python test executes only the schema outcome; it
does not implement or claim to execute the Web or Swift decoders. Node and Swift consume the same JSON
resource and use their real production admission functions. Python additionally checks coverage,
unique case IDs, and that malformed-video cases have otherwise schema-valid base catalogs.

## Covered boundaries and current differences

- Old v3 catalogs without `videoDelivery`, with and without the optional source-media hash
- Valid `dev` and `prod` bucket shapes for `zh-Hans`, `ko` and `es`, one-byte minimum and 160-character page ID
- Canonical URL and immutable storage URL: wrong paths, page/locale segments, traversal, encoded traversal,
  query/fragment, external host, HTTP, unknown bucket/environment and the 161-character path boundary
- Malformed/missing video hashes and required fields; absent, null, non-object or wrong-version metadata;
  zero, negative, fractional, string and boolean byte counts
- Missing/null/malformed source-media hashes, wrong release-locale binding and unknown fields at the
  catalog, page, target and video levels

At this baseline both clients ignore `videoDelivery`, including malformed video metadata. Schema
rejection therefore does **not** imply client rejection. Clients still reject a malformed known
`sourceMediaSha256` or a release path bound to a different target locale. Missing/null optional source
hashes remain client-admissible even when `videoDelivery` is present, while schema rejects those rows.

The schema constrains video path syntax and allows either dedicated bucket. It does not bind the
canonical/storage page segment to the enclosing page ID, bind the storage filename hash to `sha256`,
or select a deployment environment. Those syntactically valid mismatches are explicitly accepted
rows, not evidence of a validated delivery. Source-media and browser-video hashes are separate
identities and are intentionally different in the valid fixtures.

Unknown fields are rejected by schema `additionalProperties: false` and ignored by both clients.
There are 15 expected schema acceptances and 58 expected acceptances for each client. These are
recorded behavior, not a recommendation to admit unsafe video metadata or a full-equivalence claim.
The fixtures do not replace producer/assembly validation of assets, content hashes and redirects.

## Reproduce offline

From the repository root:

```sh
python -m unittest tests.test_shared_video_delivery_fixtures -v
node --test experiments/sermon-dubbing-poc/web/shared-video-delivery.test.mjs
# On an available Swift/Xcode toolchain, with the existing package resources:
swift test --package-path apps/tongxing-ios/Core --filter SharedVideoDeliveryTests
```

The existing Node wildcard and Python discovery include the new tests. SwiftPM discovers the new
test and its JSON via the existing `.copy("Fixtures")` resource; no package or CI edit is needed.
The current draft-PR native workflow skips its Swift/macOS jobs. A green `native-client` routing
summary must not be reported as executed Swift tests. Swift expectations require an actual supported
toolchain run before native qualification; a cloud Node/Python pass alone is insufficient.

All review/status values are synthetic decoder inputs under
`synthetic_decoder_tests_not_production_approval`. These tests perform no remote media requests and
do not establish video fetch safety, byte/hash integrity, redirects, playback, content approval,
publication, iPhone/simulator qualification, or device/venue acceptance. E6 remains incomplete.
