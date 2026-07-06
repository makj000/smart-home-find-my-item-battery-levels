import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import check_batteries


class BatteryHistoryTest(unittest.TestCase):
    def test_export_find_my_ui_retries_missing_window(self):
        with (
            patch.object(check_batteries, "activate_find_my") as activate,
            patch.object(
                check_batteries,
                "export_find_my_ui_once",
                side_effect=[
                    RuntimeError("Error: Find My has no accessible window."),
                    [{"description": "Car Keys\nShared with Family Member"}],
                ],
            ),
        ):
            records = check_batteries.export_find_my_ui(
                attempts=2,
                wait_seconds=0,
            )

        self.assertEqual(
            [{"description": "Car Keys\nShared with Family Member"}],
            records,
        )
        self.assertEqual(2, activate.call_count)

    def test_export_find_my_ui_does_not_retry_unrelated_errors(self):
        with (
            patch.object(check_batteries, "activate_find_my") as activate,
            patch.object(
                check_batteries,
                "export_find_my_ui_once",
                side_effect=RuntimeError("Accessibility permission is required."),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Accessibility"):
                check_batteries.export_find_my_ui(
                    attempts=3,
                    wait_seconds=0,
                )

        self.assertEqual(1, activate.call_count)

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

    def test_main_warns_when_alert_fails_after_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite3"
            report = Path(directory) / "report.html"
            stderr = StringIO()
            with (
                patch.object(check_batteries, "DATABASE_PATH", database),
                patch.object(check_batteries, "REPORT_PATH", report),
                patch.object(
                    check_batteries,
                    "export_find_my_ui",
                    return_value=[
                        {
                            "description": (
                                "Car Keys\nShared with Family Member"
                            )
                        },
                        {"description": "Battery charge is 15 percent."},
                    ],
                ),
                patch.object(
                    check_batteries,
                    "notify",
                    side_effect=RuntimeError("rate limited"),
                ),
                patch("sys.stderr", stderr),
            ):
                check_batteries.main()

            self.assertTrue(report.exists())
            self.assertIn("battery alert failed", stderr.getvalue())

    def test_notify_publishes_to_ntfy(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with tempfile.TemporaryDirectory() as directory:
            ntfy_url = Path(directory) / "ntfy_url.txt"
            ntfy_url.write_text("https://ntfy.sh/example-topic")
            with (
                patch.object(check_batteries, "NTFY_URL_PATH", ntfy_url),
                patch.object(
                    check_batteries.urllib.request,
                    "urlopen",
                    return_value=response,
                ) as urlopen,
            ):
                check_batteries.notify(
                    [
                        {
                            "name": "Car Keys",
                            "battery_percent": 15,
                            "battery_status": (
                                "Battery charge is 15 percent."
                            ),
                        },
                        {
                            "name": "Camera Bag",
                            "battery_percent": None,
                            "battery_status": "Low Battery",
                        },
                    ]
                )

        request = urlopen.call_args.args[0]
        self.assertEqual("https://ntfy.sh/example-topic", request.full_url)
        self.assertEqual("POST", request.get_method())
        self.assertEqual(
            b"Car Keys: 15%, Camera Bag: low",
            request.data,
        )
        self.assertEqual(
            "Find My battery warning",
            request.get_header("Title"),
        )
        self.assertEqual("high", request.get_header("Priority"))

    def test_load_ntfy_url_accepts_topic_name(self):
        with tempfile.TemporaryDirectory() as directory:
            ntfy_url = Path(directory) / "ntfy_url.txt"
            ntfy_url.write_text("example-topic\n")
            with patch.object(check_batteries, "NTFY_URL_PATH", ntfy_url):
                self.assertEqual(
                    "https://ntfy.sh/example-topic",
                    check_batteries.load_ntfy_url(),
                )

    def test_load_ntfy_url_requires_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                check_batteries,
                "NTFY_URL_PATH",
                Path(directory) / "missing.txt",
            ):
                with self.assertRaisesRegex(RuntimeError, "Missing ntfy"):
                    check_batteries.load_ntfy_url()


if __name__ == "__main__":
    unittest.main()
