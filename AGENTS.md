# Find My Battery Monitor

Maintain a local macOS application that checks battery levels for Items in
Apple's Find My app.

## Goal

Use battery history to predict when an Item will need a battery replacement,
so a spare battery can be charged and ready beforehand. Charging takes several
hours, so the system should eventually provide advance notice rather than
waiting until an Item has already reached the low-battery threshold.

Prediction is a future requirement and is not part of the current
implementation.

## Behavior

1. Run once daily at 6:00 PM local time when the Mac is running.
2. Open Find My and select the Items tab.
3. Read item names and battery information through macOS Accessibility APIs.
4. Report all detected battery levels.
5. Send an ntfy notification when a battery is at or below 20%, or Find My
   explicitly reports a low-battery status.
6. Repeat the low-battery notification during every daily check while the Item
   remains low. Do not suppress repeated alerts across days.
7. Store one reading per item per day in SQLite.
8. Generate a self-contained HTML report showing battery changes over time.

## Architecture

- `Find My Battery.app` is the stable, permission-bearing Accessibility
  exporter.
- `find_my_exporter.swift` exports accessible Find My UI elements as JSON.
- `check_batteries.py` parses the JSON, records history, sends notifications,
  and generates the report.
- Notifications are published to the ntfy topic configured in ignored local
  file `ntfy_url.txt`.
- `battery_history.sqlite3` stores daily history.
- `battery_report.html` is the generated trend report.
- `install-launch-agent.sh` generates and installs the daily 6:00 PM schedule.

## Critical Constraint

Do not rebuild or replace `Find My Battery.app` for parser, threshold, storage,
notification, or report changes. Rebuilding changes its code signature and
invalidates its macOS Accessibility permission.

Make routine behavior changes only in `check_batteries.py`. Rebuild the app
only when the Accessibility export format itself must change, and expect the
user to remove and re-add the app in:

`System Settings > Privacy & Security > Accessibility`

## Current Limitations

- Find My does not expose a public API, so this relies on local UI automation.
- Find My may expose a percentage for only some Items. Record other Items as
  `not reported`; do not invent a value.
- UI changes in macOS may require updates to the Python parser or, as a last
  resort, the Swift exporter.

## Verification

Run:

```bash
/usr/bin/python3 -m unittest -v test_check_batteries.py
./run.sh
```

Confirm:

- The command exits successfully.
- `logs/error.log` is empty after a scheduled run.
- `battery_history.sqlite3` contains today's readings.
- `battery_report.html` displays the latest values and daily trend charts.
