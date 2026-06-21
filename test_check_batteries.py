import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import check_batteries


class BatteryHistoryTest(unittest.TestCase):
    def test_parse_items(self):
        records = [
            {
                "description": (
                    "Car Keys, Home, 2 days ago\nShared with Family Member"
                )
            },
            {"description": "Battery charge is 15 percent."},
            {
                "description": (
                    "Camera Bag, No location found\n"
                    "Shared with Family Member"
                )
            },
        ]
        self.assertEqual(
            [
                {
                    "name": "Car Keys",
                    "battery_percent": 15,
                    "battery_status": "Battery charge is 15 percent.",
                },
                {
                    "name": "Camera Bag",
                    "battery_percent": None,
                    "battery_status": None,
                },
            ],
            check_batteries.parse_items(records),
        )

    def test_history_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite3"
            report = Path(directory) / "report.html"
            with (
                patch.object(check_batteries, "DATABASE_PATH", database),
                patch.object(check_batteries, "REPORT_PATH", report),
            ):
                check_batteries.record_history(
                    [
                        {
                            "name": "Keys",
                            "battery_percent": 9,
                            "battery_status": "Battery charge is 9 percent.",
                        }
                    ],
                    datetime.fromisoformat("2026-06-13T18:00:00-07:00"),
                )
                check_batteries.generate_report()
                contents = report.read_text()
                self.assertIn("Daily Battery Trends", contents)
                self.assertIn("Keys", contents)
                self.assertIn("9%", contents)
                self.assertEqual(1, contents.count("<svg"))

    def test_notify_passes_summary_as_osascript_argument(self):
        with patch.object(check_batteries.subprocess, "run") as run:
            check_batteries.notify(
                [
                    {
                        "name": "Car Keys",
                        "battery_percent": 15,
                        "battery_status": "Battery charge is 15 percent.",
                    },
                    {
                        "name": "Camera Bag",
                        "battery_percent": None,
                        "battery_status": "Low Battery",
                    },
                ]
            )

        args = run.call_args.args[0]
        self.assertIn(
            "display notification item 1 of argv with title item 2 of argv",
            args,
        )
        self.assertIn("Car Keys: 15%, Camera Bag: low", args)
        self.assertEqual("Find My battery warning", args[-1])


if __name__ == "__main__":
    unittest.main()
