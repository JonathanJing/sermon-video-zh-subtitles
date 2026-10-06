import Foundation
import CoreGraphics

/// Places the panel inside a usable rectangle, rather than nudging and then
/// clamping it back across a fold. A smaller result is a scrollable viewport.
enum PlaybackPanelLayout {
    static func viewport(preferred: CGRect, in bounds: CGRect, avoiding reserved: [CGRect],
                         margin: CGFloat = 12, gap: CGFloat = 8) -> CGRect? {
        let usable = bounds.insetBy(dx: margin, dy: margin)
        guard usable.width >= 160, usable.height >= 68,
              preferred.width > 0, preferred.height > 0 else { return nil }
        let barriers = reserved.filter { !$0.isNull && !$0.isEmpty }
            .map { $0.insetBy(dx: -gap, dy: -gap) }
        var regions = [usable]
        for barrier in barriers {
            regions = regions.flatMap { region -> [CGRect] in
                guard region.intersects(barrier) else { return [region] }
                let cut = region.intersection(barrier)
                // Overlapping candidates preserve the full width or full height
                // available on either side; each candidate excludes this barrier.
                return [
                    CGRect(x: region.minX, y: region.minY, width: cut.minX - region.minX, height: region.height),
                    CGRect(x: cut.maxX, y: region.minY, width: region.maxX - cut.maxX, height: region.height),
                    CGRect(x: region.minX, y: region.minY, width: region.width, height: cut.minY - region.minY),
                    CGRect(x: region.minX, y: cut.maxY, width: region.width, height: region.maxY - cut.maxY)
                ].filter { $0.width >= 160 && $0.height >= 68 }
            }
        }
        func place(in region: CGRect) -> CGRect {
            let size = CGSize(width: min(preferred.width, region.width),
                              height: min(preferred.height, region.height))
            return CGRect(x: min(max(preferred.minX, region.minX), region.maxX - size.width),
                          y: min(max(preferred.minY, region.minY), region.maxY - size.height),
                          width: size.width, height: size.height)
        }
        func distance(_ frame: CGRect) -> CGFloat {
            let dx = frame.midX - preferred.midX, dy = frame.midY - preferred.midY
            return dx * dx + dy * dy
        }
        let candidates = regions.map(place).filter {
            usable.contains($0) && !barriers.contains(where: $0.intersects)
        }
        let complete = candidates.filter { $0.size == preferred.size }
        if let nearest = complete.min(by: { distance($0) < distance($1) }) { return nearest }
        return candidates.sorted {
            let firstArea = $0.width * $0.height, secondArea = $1.width * $1.height
            return firstArea == secondArea ? distance($0) < distance($1) : firstArea > secondArea
        }.first
    }
}
