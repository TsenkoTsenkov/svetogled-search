#!/bin/bash
# Install a daily LaunchAgent on THIS Mac that refreshes the YOUTUBE_COOKIES
# GitHub secret from Chrome (scripts/refresh_youtube_cookies.py), so the
# weekly transcript workflow never runs on an expired cookie jar.
#
# Run once on a Mac where Chrome is signed in to YouTube and gh is logged in
# as the repo owner. Safe to re-run. launchd runs a missed daily slot when the
# Mac wakes, so a laptop that sleeps overnight still refreshes every day.
#
# Why an app: macOS refuses plain launchd jobs access to another app's data
# ("Operation not permitted" on Chrome's profile folder). The job therefore
# runs inside a tiny AppleScript applet, which macOS lets you grant access
# once: System Settings → Privacy & Security → Full Disk Access → add
# ~/Applications/SvetogledCookieRefresh.app. The grant is tied to the app's
# signature, so the app is built only if missing — deleting and rebuilding it
# means granting access again.
#
# Uninstall: launchctl bootout gui/$(id -u)/com.svetogled.cookie-refresh
#            rm ~/Library/LaunchAgents/com.svetogled.cookie-refresh.plist
#            rm -r ~/Applications/SvetogledCookieRefresh.app
set -euo pipefail

LABEL=com.svetogled.cookie-refresh
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_DIR/scripts/refresh_youtube_cookies.py"
APP="$HOME/Applications/SvetogledCookieRefresh.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/svetogled-cookie-refresh.log"
GUI_DOMAIN="gui/$(id -u)"

UV="$(command -v uv)" || { echo "uv not found — brew install uv" >&2; exit 1; }
GH="$(command -v gh)" || { echo "gh not found — brew install gh" >&2; exit 1; }
RUN_PATH="$(dirname "$UV"):$(dirname "$GH"):/usr/bin:/bin:/usr/sbin:/sbin"

# Validate before scheduling: Chrome readable, signed in, jar within limits.
"$UV" run --script "$SCRIPT" --dry-run

if [ ! -d "$APP" ]; then
  mkdir -p "$(dirname "$APP")"
  SRC="$(mktemp -t cookie-refresh).applescript"
  # --upgrade keeps yt-dlp current with Chrome's cookie encryption. The try
  # block stops a failed run from popping a modal error dialog; the script
  # itself posts a notification and logs the reason.
  cat > "$SRC" <<EOF
try
	do shell script "export PATH=" & quoted form of "$RUN_PATH" & "; " & ¬
		quoted form of "$UV" & " run --script --upgrade " & quoted form of "$SCRIPT" & ¬
		" >> " & quoted form of "$LOG" & " 2>&1"
end try
EOF
  osacompile -o "$APP" "$SRC"
  rm -f "$SRC"
  # Background-only: no Dock icon while it runs. Re-sign after the edit.
  plutil -replace LSUIElement -bool true "$APP/Contents/Info.plist"
  codesign --force --sign - "$APP"
  echo "Built $APP — grant it Full Disk Access (see header)."
fi

mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>$LABEL</string>
	<key>ProgramArguments</key>
	<array><string>/usr/bin/open</string><string>-g</string><string>$APP</string></array>
	<key>StartCalendarInterval</key>
	<dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
</dict>
</plist>
EOF

launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$GUI_DOMAIN" "$PLIST"
echo "Installed $LABEL — refreshes daily at 08:00 local time."
echo "Log:      $LOG"
echo "Run now:  open -g $APP"
