import Foundation
import CoreGraphics

/// Keeps one control group out of local reserved regions. The caller supplies
/// already-safe bounds; this policy never derives geometry from a device name.
public enum PlaybackControlRegion {
    public static func resolve(in bounds: CGRect, excluding exclusions: [CGRect]) -> CGRect {
        guard bounds.width.isFinite, bounds.height.isFinite,
              bounds.width > 0, bounds.height > 0 else { return .zero }
        var candidates = [bounds]
        for exclusion in exclusions {
            guard exclusion.origin.x.isFinite, exclusion.origin.y.isFinite,
                  exclusion.width.isFinite, exclusion.height.isFinite,
                  exclusion.width > 0, exclusion.height > 0 else { continue }
            candidates = candidates.flatMap { candidate -> [CGRect] in
                let overlap = candidate.intersection(exclusion)
                guard !overlap.isNull, !overlap.isEmpty else { return [candidate] }
                return [
                    CGRect(x: candidate.minX, y: candidate.minY, width: overlap.minX - candidate.minX, height: candidate.height),
                    CGRect(x: overlap.maxX, y: candidate.minY, width: candidate.maxX - overlap.maxX, height: candidate.height),
                    CGRect(x: candidate.minX, y: candidate.minY, width: candidate.width, height: overlap.minY - candidate.minY),
                    CGRect(x: candidate.minX, y: overlap.maxY, width: candidate.width, height: candidate.maxY - overlap.maxY)
                ].filter { $0.width > 0 && $0.height > 0 }
            }
        }
        // Prefer the lower region for touch controls and trailing region in a
        // book pose. Don't choose a narrow camera-side sliver over usable space.
        let usable = candidates.filter { $0.width >= min(240, bounds.width) && $0.height >= 100 }
        let choices = usable.isEmpty ? candidates : usable
        return choices.max { lhs, rhs in
            if usable.isEmpty { return lhs.width * lhs.height < rhs.width * rhs.height }
            if lhs.maxY != rhs.maxY { return lhs.maxY < rhs.maxY }
            if lhs.maxX != rhs.maxX { return lhs.maxX < rhs.maxX }
            return lhs.width * lhs.height < rhs.width * rhs.height
        } ?? .zero
    }
}
