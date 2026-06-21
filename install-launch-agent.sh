#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="local.find-my-battery"
LEGACY_LABEL="com.kma.find-my-battery"
PLIST_NAME="$LABEL.plist"
DESTINATION="$HOME/Library/LaunchAgents/$PLIST_NAME"
LEGACY_DESTINATION="$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist"
DOMAIN="gui/$(id -u)"

if [[ ! -d "$PROJECT_DIR/Find My Battery.app" ]]; then
    "$PROJECT_DIR/build.sh"
fi
mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

/usr/bin/python3 - "$DESTINATION" "$PROJECT_DIR" "$LABEL" <<'PY'
import plistlib
import sys
from pathlib import Path

destination = Path(sys.argv[1])
project_dir = Path(sys.argv[2])
label = sys.argv[3]
configuration = {
    "Label": label,
    "ProgramArguments": [str(project_dir / "run.sh")],
    "StartCalendarInterval": {"Hour": 18, "Minute": 0},
    "StandardOutPath": str(project_dir / "logs" / "check.log"),
    "StandardErrorPath": str(project_dir / "logs" / "error.log"),
}
with destination.open("wb") as file:
    plistlib.dump(configuration, file)
PY

launchctl bootout "$DOMAIN/$LEGACY_LABEL" 2>/dev/null || true
rm -f "$LEGACY_DESTINATION"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DESTINATION"

echo "Installed daily check for 6:00 PM."
echo "Run once now to grant Accessibility access:"
echo "  open '$PROJECT_DIR/Find My Battery.app'"
