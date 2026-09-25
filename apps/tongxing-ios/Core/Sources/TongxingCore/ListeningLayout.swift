/// The content arrangement for the listening screen.
///
/// This policy deliberately describes available space rather than a device or
/// posture. iPhone Duo, iPad multitasking, rotation, and accessibility settings
/// can all change the usable window while the same scene remains alive.
public enum ListeningLayout: Equatable, Sendable {
    case singleColumn
    case readingAndListening
}

public enum ListeningLayoutPolicy {
    /// The first-pass threshold leaves room for a 300 pt reading column, a
    /// 420 pt listening column, and the split view's system-managed separator.
    /// It remains a product value to calibrate with the Duo runtime and device.
    public static let minimumTwoColumnWidth = 840.0

    public static func layout(
        availableWidth: Double,
        hasRegularHorizontalSizeClass: Bool,
        usesAccessibilityTextSize: Bool
    ) -> ListeningLayout {
        guard availableWidth.isFinite,
              availableWidth >= minimumTwoColumnWidth,
              hasRegularHorizontalSizeClass,
              !usesAccessibilityTextSize else {
            return .singleColumn
        }
        return .readingAndListening
    }
}
