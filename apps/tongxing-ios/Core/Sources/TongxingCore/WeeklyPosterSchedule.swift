import Foundation

/// A weekly poster may be offered automatically from 08:00 on its page's own
/// service date. The page date is a calendar date, not an instant: the hour is
/// interpreted in the device's current time zone, so "Sunday morning" follows
/// the person holding the phone. A late-published poster still waits for the
/// next app open because the announcement must exist as well.
public enum WeeklyPosterSchedule {
    /// The local hour on the service date from which the poster may auto-present.
    public static let presentationHour = 8

    /// Gregorian calendar interpreted in the device time zone by default.
    public static func calendar(timeZone: TimeZone = .current) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        return calendar
    }

    /// The first instant the poster becomes eligible, or nil for a malformed
    /// or impossible service date (the client then never auto-presents it).
    public static func notBefore(pageDate: String, calendar: Calendar) -> Date? {
        guard Validation.isoDate(pageDate) else { return nil }
        let parts = pageDate.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var components = DateComponents()
        components.calendar = calendar
        components.timeZone = calendar.timeZone
        components.year = parts[0]
        components.month = parts[1]
        components.day = parts[2]
        components.hour = presentationHour
        components.minute = 0
        components.second = 0
        guard let date = calendar.date(from: components) else { return nil }
        // Calendar silently rolls over impossible values (for example 2026-02-30).
        // Require the exact local fields back before treating the date as due.
        let roundTrip = calendar.dateComponents([.year, .month, .day, .hour], from: date)
        guard roundTrip.year == parts[0], roundTrip.month == parts[1], roundTrip.day == parts[2],
              roundTrip.hour == presentationHour else { return nil }
        return date
    }

    public static func isDue(pageDate: String, now: Date, calendar: Calendar) -> Bool {
        guard let start = notBefore(pageDate: pageDate, calendar: calendar) else { return false }
        return now >= start
    }
}
