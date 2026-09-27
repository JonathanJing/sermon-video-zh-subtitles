import datetime as dt
import importlib.util
import json
import pathlib
import plistlib
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "collect_resi_event_uuids.py"
SPEC = importlib.util.spec_from_file_location("collect_resi_event_uuids", MODULE_PATH)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
PACIFIC = ZoneInfo("America/Los_Angeles")


class ResiEventInventoryTests(unittest.TestCase):
    def test_weekend_gate_and_sunday_weekend_date_across_dst(self):
        for date in ("2026-09-27", "2026-11-01"):
            with self.subTest(date=date):
                sunday = dt.datetime.fromisoformat(f"{date}T08:50:00").replace(tzinfo=PACIFIC)
                weekend, window = collector.local_window(sunday)
                self.assertEqual(weekend, (sunday.date() - dt.timedelta(days=1)).isoformat())
                self.assertEqual(window, "sun-0830")
        self.assertIsNone(collector.local_window(
            dt.datetime(2026, 9, 28, 8, 50, tzinfo=PACIFIC)))

    def test_id_parser_uses_player_element_not_other_uuid(self):
        parser = collector.EmbedIdParser()
        parser.feed('<div data-embed-id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa">'
                    '<div data-embed-id="fc7c04d4-80b9-4c8a-ac1c-fc7f808a6f55" '
                    'id="resi-video-player"></div>')
        self.assertEqual(parser.embed_id, "fc7c04d4-80b9-4c8a-ac1c-fc7f808a6f55")

    def test_outside_window_makes_no_request_or_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = pathlib.Path(directory) / "inventory"
            with mock.patch.object(collector, "fetch_embed_id") as embed, \
                 mock.patch.object(collector, "fetch_event") as event:
                result = collector.collect_once(
                    data_dir, dt.datetime(2026, 9, 28, 8, 0, tzinfo=PACIFIC))
            self.assertEqual(result, {"status": "outside_window"})
            self.assertFalse(data_dir.exists())
            embed.assert_not_called()
            event.assert_not_called()

    def test_records_each_poll_and_refreshes_embed_only_next_local_day(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = pathlib.Path(directory)
            saturday = dt.datetime(2026, 9, 26, 16, 10, tzinfo=PACIFIC)
            sunday = dt.datetime(2026, 9, 27, 7, 10, tzinfo=PACIFIC)
            with mock.patch.object(collector, "fetch_embed_id", return_value=
                                   "fc7c04d4-80b9-4c8a-ac1c-fc7f808a6f55") as embed, \
                 mock.patch.object(collector, "fetch_event", side_effect=[
                     ("11111111-1111-4111-8111-111111111111", "Saturday 4pm"),
                     ("11111111-1111-4111-8111-111111111111", "Saturday 4pm"),
                     ("22222222-2222-4222-8222-222222222222", "Sunday 7am"),
                 ]):
                collector.collect_once(data_dir, saturday)
                collector.collect_once(data_dir, saturday + dt.timedelta(minutes=20))
                collector.collect_once(data_dir, sunday)
            self.assertEqual(embed.call_count, 2)
            rows = [json.loads(line) for line in (data_dir / "observations.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertEqual({row["weekendDate"] for row in rows}, {"2026-09-26"})
            self.assertTrue(all("cloud" not in row and "mediaUrl" not in row for row in rows))
            report = collector.summarize(data_dir, "2026-09-26")
            self.assertEqual(report["windows"]["sat-1600"]["polls"], 2)
            self.assertEqual(report["windows"]["sat-1600"]["uuids"],
                             ["11111111-1111-4111-8111-111111111111"])
            self.assertEqual(report["windows"]["sun-0700"]["uuids"],
                             ["22222222-2222-4222-8222-222222222222"])

    def test_launchd_is_weekend_only_and_has_29_polls(self):
        with tempfile.TemporaryDirectory() as directory:
            deployed = pathlib.Path(directory) / "collector.py"
            config = plistlib.loads(collector.launchd_plist(pathlib.Path(directory), deployed))
        calendar = config["StartCalendarInterval"]
        self.assertEqual(len(calendar), 29)
        self.assertEqual({entry["Weekday"] for entry in calendar}, {0, 6})
        self.assertNotIn("RunAtLoad", config)
        self.assertEqual(config["ProgramArguments"][1], str(deployed))


if __name__ == "__main__":
    unittest.main()
