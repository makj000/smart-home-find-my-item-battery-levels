#!/usr/bin/env python3

import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from html import escape
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
APP_PATH = PROJECT_DIR / "Find My Battery.app"
FIND_MY_APP_PATH = Path("/System/Applications/FindMy.app")
DATABASE_PATH = PROJECT_DIR / "battery_history.sqlite3"
REPORT_PATH = PROJECT_DIR / "battery_report.html"
NTFY_URL_PATH = PROJECT_DIR / "ntfy_url.txt"
THRESHOLD = 20
NO_WINDOW_ERROR = "Find My has no accessible window"


def activate_find_my(wait_seconds=3.0):
    subprocess.run(
        ["/usr/bin/open", str(FIND_MY_APP_PATH)],
        check=False,
    )
    time.sleep(wait_seconds)


def export_find_my_ui(attempts=3, wait_seconds=3.0):
    last_error = None
    for attempt in range(attempts):
        activate_find_my(wait_seconds)
        try:
            return export_find_my_ui_once()
        except RuntimeError as error:
            last_error = error
            if NO_WINDOW_ERROR not in str(error) or attempt == attempts - 1:
                raise
    raise last_error


def export_find_my_ui_once():
    with tempfile.TemporaryDirectory() as directory:
        stdout_path = Path(directory) / "find-my.json"
        stderr_path = Path(directory) / "find-my.err"
        completed = subprocess.run(
            [
                "/usr/bin/open",
                "--wait-apps",
                "--stdout",
                str(stdout_path),
                "--stderr",
                str(stderr_path),
                str(APP_PATH),
            ],
            check=False,
        )
        error = stderr_path.read_text(encoding="utf-8").strip()
        if completed.returncode or error:
            raise RuntimeError(error or "Find My exporter failed")
        output = stdout_path.read_text(encoding="utf-8").strip()
        if not output:
            raise RuntimeError("Find My exporter produced no JSON")
        return json.loads(output)


def parse_items(records):
    items = []
    current_item = None
    for record in records:
        texts = [
            value
            for key in ("description", "value", "title")
            if (value := record.get(key))
        ]
        for text in texts:
            if "Shared with" in text:
                first_line = text.splitlines()[0].strip(", ")
                current_item = first_line.split(",", 1)[0].strip()
                items.append(
                    {
                        "name": current_item,
                        "battery_percent": None,
                        "battery_status": None,
                        "last_seen_status": first_line,
                    }
                )
                continue
            if current_item and "battery" in text.lower():
                match = re.search(r"(\d{1,3})\s*(?:%|percent)", text, re.I)
                if match and int(match.group(1)) <= 100:
                    items[-1]["battery_percent"] = int(match.group(1))
                items[-1]["battery_status"] = text
    return items


def ensure_schema(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS battery_readings (
            item_name TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            reading_date TEXT NOT NULL,
            battery_percent INTEGER,
            battery_status TEXT,
            PRIMARY KEY (item_name, reading_date)
        )
        """
    )
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(battery_readings)")
    }
    if "last_seen_status" not in columns:
        connection.execute(
            "ALTER TABLE battery_readings ADD COLUMN last_seen_status TEXT"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS battery_observations (
            observed_at TEXT NOT NULL,
            note TEXT NOT NULL,
            PRIMARY KEY (observed_at, note)
        )
        """
    )


def record_history(items, checked_at=None):
    checked_at = checked_at or datetime.now().astimezone()
    with sqlite3.connect(DATABASE_PATH) as connection:
        ensure_schema(connection)
        for item in items:
            connection.execute(
                """
                INSERT INTO battery_readings (
                    item_name,
                    checked_at,
                    reading_date,
                    battery_percent,
                    battery_status,
                    last_seen_status
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_name, reading_date) DO UPDATE SET
                    checked_at = excluded.checked_at,
                    battery_percent = excluded.battery_percent,
                    battery_status = excluded.battery_status,
                    last_seen_status = excluded.last_seen_status
                """,
                (
                    item["name"],
                    checked_at.isoformat(timespec="seconds"),
                    checked_at.date().isoformat(),
                    item["battery_percent"],
                    item["battery_status"],
                    item.get("last_seen_status"),
                ),
            )


def record_observation(note, observed_at=None):
    observed_at = observed_at or datetime.now().astimezone()
    with sqlite3.connect(DATABASE_PATH) as connection:
        ensure_schema(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO battery_observations (observed_at, note)
            VALUES (?, ?)
            """,
            (observed_at.isoformat(timespec="seconds"), note),
        )


def load_history():
    with sqlite3.connect(DATABASE_PATH) as connection:
        ensure_schema(connection)
        return connection.execute(
            """
            SELECT
                item_name,
                reading_date,
                battery_percent,
                battery_status,
                last_seen_status
            FROM battery_readings
            ORDER BY item_name, reading_date
            """
        ).fetchall()


def load_observations():
    with sqlite3.connect(DATABASE_PATH) as connection:
        ensure_schema(connection)
        return connection.execute(
            """
            SELECT observed_at, note
            FROM battery_observations
            ORDER BY observed_at DESC, note
            """
        ).fetchall()


def combined_chart_svg(grouped):
    series = {
        name: [
            (date, percent)
            for _, date, percent, _, _ in readings
            if percent is not None
        ]
        for name, readings in grouped.items()
    }
    series = {name: readings for name, readings in series.items() if readings}
    if not series:
        return '<p class="unknown">No battery percentages are reported.</p>'

    dates = sorted(
        {date for readings in series.values() for date, _ in readings}
    )
    date_indexes = {date: index for index, date in enumerate(dates)}
    colors = [
        "#1677ff",
        "#e04b3f",
        "#2f9e44",
        "#9c36b5",
        "#f08c00",
        "#0b7285",
        "#d6336c",
        "#5f3dc4",
    ]
    width, height = 860, 360
    left, top, right, bottom = 52, 24, 24, 52
    plot_width = width - left - right
    plot_height = height - top - bottom

    def x(date):
        return left + (
            plot_width / max(len(dates) - 1, 1)
        ) * date_indexes[date]

    def y(percent):
        return top + plot_height * (100 - percent) / 100

    grid = []
    for percent in (0, 25, 50, 75, 100):
        line_y = y(percent)
        grid.append(
            f'<line x1="{left}" y1="{line_y:.1f}" '
            f'x2="{width - right}" y2="{line_y:.1f}" />'
            f'<text x="{left - 8}" y="{line_y + 4:.1f}">'
            f"{percent}%</text>"
        )

    lines = []
    legend = []
    for index, (name, readings) in enumerate(sorted(series.items())):
        color = colors[index % len(colors)]
        points = " ".join(
            f"{x(date):.1f},{y(percent):.1f}"
            for date, percent in readings
        )
        circles = "".join(
            f'<circle cx="{x(date):.1f}" cy="{y(percent):.1f}" r="4" '
            f'style="fill:{color}">'
            f"<title>{escape(name)} - {escape(date)}: {percent}%</title>"
            f"</circle>"
            for date, percent in readings
        )
        lines.append(
            f'<polyline points="{points}" style="stroke:{color}" />'
            f"{circles}"
        )
        legend.append(
            f'<span><i style="background:{color}"></i>{escape(name)}</span>'
        )

    date_labels = []
    label_step = max(1, len(dates) // 7)
    for index, date in enumerate(dates):
        if index % label_step == 0 or index == len(dates) - 1:
            date_labels.append(
                f'<text class="date" x="{x(date):.1f}" y="{height - 18}" '
                f'text-anchor="middle">{escape(date[5:])}</text>'
            )
    return f"""
    <div class="legend">{''.join(legend)}</div>
    <svg viewBox="0 0 {width} {height}" role="img">
      <g class="grid">{''.join(grid)}</g>
      <line class="threshold" x1="{left}" y1="{y(THRESHOLD):.1f}"
        x2="{width - right}" y2="{y(THRESHOLD):.1f}" />
      {''.join(lines)}
      {''.join(date_labels)}
    </svg>
    """


def generate_report():
    grouped = {}
    for row in load_history():
        grouped.setdefault(row[0], []).append(row)

    latest_rows = []
    for item_name, readings in grouped.items():
        latest = readings[-1]
        level = (
            f"{latest[2]}%"
            if latest[2] is not None
            else latest[3] or "not reported"
        )
        last_seen = latest[4] or "not reported"
        status_class = (
            "low"
            if latest[2] is not None and latest[2] <= THRESHOLD
            else ""
        )
        latest_rows.append(
            f"""
            <tr>
              <td>{escape(item_name)}</td>
              <td class="{status_class}">{escape(level)}</td>
              <td>{escape(last_seen)}</td>
            </tr>
            """
        )
    observation_rows = [
        f"""
        <tr>
          <td>{escape(observed_at)}</td>
          <td>{escape(note)}</td>
        </tr>
        """
        for observed_at, note in load_observations()
    ]

    generated = datetime.now().astimezone().strftime("%Y-%m-%d %I:%M %p %Z")
    REPORT_PATH.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Find My Battery History</title>
<style>
body {{ font: 16px -apple-system, sans-serif; margin: 32px auto;
  max-width: 900px; padding: 0 20px; color: #1d1d1f; }}
header {{ border-bottom: 1px solid #ddd; margin-bottom: 24px; }}
section {{ border: 1px solid #ddd; border-radius: 12px; margin: 18px 0;
  padding: 20px; }}
h2 {{ margin: 0; }}
.low {{ color: #c00; }}
.unknown {{ color: #666; }}
svg {{ width: 100%; height: auto; }}
.grid line {{ stroke: #e5e5e5; }}
.grid text, .date {{ fill: #666; font-size: 12px; }}
.threshold {{ stroke: #c00; stroke-dasharray: 5 5; }}
polyline {{ fill: none; stroke-width: 3; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 12px 0; }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.legend i {{ width: 12px; height: 12px; border-radius: 50%; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 10px; text-align: left; }}
</style>
</head>
<body>
<header>
  <h1>Find My Battery History</h1>
  <p>Generated {escape(generated)}. Low threshold: {THRESHOLD}%.</p>
</header>
<section>
  <h2>Daily Battery Trends</h2>
  {combined_chart_svg(grouped)}
</section>
<section>
  <h2>Latest Readings</h2>
  <table>
    <thead>
      <tr><th>Item</th><th>Battery</th><th>Find My item text</th></tr>
    </thead>
    <tbody>{''.join(latest_rows)}</tbody>
  </table>
</section>
<section>
  <h2>Observations</h2>
  <table>
    <thead><tr><th>Observed At</th><th>Note</th></tr></thead>
    <tbody>{''.join(observation_rows)}</tbody>
  </table>
</section>
</body>
</html>
""",
        encoding="utf-8",
    )


def load_ntfy_url():
    if not NTFY_URL_PATH.exists():
        raise RuntimeError(
            f"Missing ntfy topic URL. Create {NTFY_URL_PATH} with "
            "a topic URL such as https://ntfy.sh/my-topic."
        )
    url = NTFY_URL_PATH.read_text(encoding="utf-8").strip()
    if not url:
        raise RuntimeError(f"{NTFY_URL_PATH} is empty")
    if "://" not in url:
        url = f"https://ntfy.sh/{url}"
    return url.rstrip("/")


def notify(low_items):
    summary = ", ".join(
        f"{item['name']}: "
        f"{item['battery_percent']}%"
        if item["battery_percent"] is not None
        else f"{item['name']}: low"
        for item in low_items
    )
    request = urllib.request.Request(
        load_ntfy_url(),
        data=summary.encode("utf-8"),
        headers={
            "Title": "Find My battery warning",
            "Priority": "high",
            "Tags": "warning",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status >= 400:
            raise RuntimeError(f"ntfy publish failed: HTTP {response.status}")


def main():
    items = parse_items(export_find_my_ui())
    if not items:
        raise RuntimeError("No Find My Items were found")

    record_history(items)
    generate_report()

    low_items = []
    for item in items:
        level = (
            f"{item['battery_percent']}%"
            if item["battery_percent"] is not None
            else item["battery_status"] or "not reported"
        )
        print(f"{item['name']}: {level}")
        if (
            item["battery_percent"] is not None
            and item["battery_percent"] <= THRESHOLD
        ) or (
            item["battery_percent"] is None
            and item["battery_status"]
            and "low" in item["battery_status"].lower()
        ):
            low_items.append(item)

    if low_items:
        try:
            notify(low_items)
        except Exception as error:
            print(f"Warning: battery alert failed: {error}", file=sys.stderr)
    else:
        print(f"No batteries are at or below {THRESHOLD}%.")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
