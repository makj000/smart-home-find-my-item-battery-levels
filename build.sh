#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$PROJECT_DIR/Find My Battery.app"
EXECUTABLE_DIR="$APP_DIR/Contents/MacOS"
mkdir -p "$EXECUTABLE_DIR" "$PROJECT_DIR/logs"

CLANG_MODULE_CACHE_PATH="${TMPDIR:-/tmp}/find-my-swift-cache" \
    swiftc "$PROJECT_DIR/find_my_exporter.swift" \
    -o "$EXECUTABLE_DIR/find-my-exporter"

cp "$PROJECT_DIR/Info.plist" "$APP_DIR/Contents/Info.plist"
codesign --force --deep --sign - "$APP_DIR"

echo "Built stable exporter: $APP_DIR"
