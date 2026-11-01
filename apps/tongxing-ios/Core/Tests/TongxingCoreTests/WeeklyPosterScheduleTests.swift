import Foundation
import Testing
@testable import TongxingCore

struct WeeklyPosterScheduleTests {
    private func calendar(_ zone: String) -> Calendar {
        WeeklyPosterSchedule.calendar(timeZone: TimeZone(identifier: zone)!)
    }
    private func instant(_ value: String) -> Date {
        ISO8601DateFormatter().date(from: value)!
    }

    @Test func presentationStartsAtEightOnTheServiceDate() {
        let utc = calendar("UTC")
        let eight = instant("2026-11-01T08:00:00Z")
        #expect(!WeeklyPosterSchedule.isDue(pageDate: "2026-11-01", now: eight.addingTimeInterval(-1), calendar: utc))
        #expect(WeeklyPosterSchedule.isDue(pageDate: "2026-11-01", now: eight, calendar: utc))
        #expect(WeeklyPosterSchedule.isDue(pageDate: "2026-11-01", now: eight.addingTimeInterval(86_400 * 3), calendar: utc))
    }

    @Test func earlierServiceDatesAreAlreadyDueAndLaterOnesWait() {
        let utc = calendar("UTC")
        let now = instant("2026-11-01T12:00:00Z")
        #expect(WeeklyPosterSchedule.isDue(pageDate: "2026-10-25", now: now, calendar: utc))
        #expect(!WeeklyPosterSchedule.isDue(pageDate: "2026-11-08", now: now, calendar: utc))
    }

    @Test func eightOClockFollowsTheDeviceTimeZone() {
        let now = instant("2026-10-31T23:00:00Z")
        #expect(WeeklyPosterSchedule.isDue(pageDate: "2026-11-01", now: now, calendar: calendar("Asia/Seoul")))
        #expect(!WeeklyPosterSchedule.isDue(pageDate: "2026-11-01", now: now.addingTimeInterval(-1),
                                            calendar: calendar("Asia/Seoul")))
        // 08:00 in Seoul is still Saturday afternoon in the church's time zone;
        // the same instant is not Sunday 08:00 in Los Angeles.
        #expect(!WeeklyPosterSchedule.isDue(pageDate: "2026-11-01", now: now,
                                            calendar: calendar("America/Los_Angeles")))
    }

    @Test func daylightSavingTransitionsKeepTheLocalHour() {
        // Both US transitions fall on a Sunday; 08:00 must remain 08:00 local.
        let losAngeles = calendar("America/Los_Angeles")
        let spring = WeeklyPosterSchedule.notBefore(pageDate: "2026-03-08", calendar: losAngeles)
        let fall = WeeklyPosterSchedule.notBefore(pageDate: "2026-11-01", calendar: losAngeles)
        // Exact instants: 08:00 PDT is 15:00Z, while 08:00 PST after the fall-back
        // is 16:00Z. A fixed-offset implementation passes the hour check above
        // but fails these equalities.
        #expect(spring == instant("2026-03-08T15:00:00Z"))
        #expect(fall == instant("2026-11-01T16:00:00Z"))
        #expect(losAngeles.component(.hour, from: spring!) == 8)
        #expect(losAngeles.component(.hour, from: fall!) == 8)
        #expect(spring! < fall!)
    }

    @Test func malformedOrImpossibleDatesAreNeverDue() {
        let utc = calendar("UTC")
        for value in ["", "2026-1-1", "20261101", "2026-13-01", "2026-02-30",
                      "2026-11-01T00:00:00Z", "2026-11-00", "2026-11-32"] {
            #expect(WeeklyPosterSchedule.notBefore(pageDate: value, calendar: utc) == nil)
            #expect(!WeeklyPosterSchedule.isDue(pageDate: value, now: Date(), calendar: utc))
        }
    }
}
