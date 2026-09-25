import Testing
@testable import TongxingCore

struct ListeningLayoutTests {
    @Test func twoColumnsStartAtDocumentedUsableWidth() {
        #expect(ListeningLayoutPolicy.layout(
            availableWidth: 839.99,
            hasRegularHorizontalSizeClass: true,
            usesAccessibilityTextSize: false
        ) == .singleColumn)
        #expect(ListeningLayoutPolicy.layout(
            availableWidth: 840,
            hasRegularHorizontalSizeClass: true,
            usesAccessibilityTextSize: false
        ) == .readingAndListening)
    }

    @Test func compactWidthAndAccessibilityTextKeepOneReadableColumn() {
        #expect(ListeningLayoutPolicy.layout(
            availableWidth: 1_200,
            hasRegularHorizontalSizeClass: false,
            usesAccessibilityTextSize: false
        ) == .singleColumn)
        #expect(ListeningLayoutPolicy.layout(
            availableWidth: 1_200,
            hasRegularHorizontalSizeClass: true,
            usesAccessibilityTextSize: true
        ) == .singleColumn)
    }

    @Test func invalidGeometryFailsDownToSingleColumn() {
        for width in [Double.nan, .infinity, -.infinity, -1] {
            #expect(ListeningLayoutPolicy.layout(
                availableWidth: width,
                hasRegularHorizontalSizeClass: true,
                usesAccessibilityTextSize: false
            ) == .singleColumn)
        }
    }
}
