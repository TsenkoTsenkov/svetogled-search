#!/bin/bash
set -euo pipefail

#############################################################
# svetogled-search deploy — macOS on-prem variant.
# Idempotent; runs as the login user, no sudo. CI (the
# self-hosted runner on this Mac) executes it after syncing
# ~/svetogled-server/app to the pushed revision; manual runs
# are the same:  bash mac/deploy-mac.sh
#
# Mirrors the retired EC2 flow (terraform/user_data.sh +
# update.sh) with launchd instead of systemd and the shared
# host Caddy (cloudvideo-server's, which imports
# ~/caddy-tenants/*.caddy) instead of a private one:
#   git sync (CI does it) → ensure venv/binary/services →
#   re-index Meilisearch → refresh ingress drop-in → restart app
#############################################################

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

SERVER_DIR="${SVETOGLED_HOME:-$HOME/svetogled-server}"
APP_DIR="$SERVER_DIR/app"
BIN_DIR="$SERVER_DIR/bin"
LOG_DIR="$SERVER_DIR/logs"
VENV="$SERVER_DIR/venv"
TENANT_DIR="$HOME/caddy-tenants"

# Shared host Caddy, owned by cloudvideo-server's deploy.
SHARED_CADDY_BIN="$HOME/cloudvideo-server/bin/caddy"
SHARED_CADDYFILE="$HOME/cloudvideo-server/app/Caddyfile"
SHARED_CADDY_ENV="$HOME/cloudvideo-server/runtime/caddy.env"

MEILI_VERSION=1.6.2   # parity with the EC2 install; index is rebuilt --fresh anyway
APP_PORT=4100
GUI_DOMAIN="gui/$(id -u)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

log() { echo "[deploy-mac] $*"; }
fail() { echo "[deploy-mac] ERROR: $*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "this is the macOS deploy"
[ -f "$APP_DIR/search_app.py" ] || fail "app checkout missing at $APP_DIR"

mkdir -p "$BIN_DIR" "$LOG_DIR" "$SERVER_DIR/meili-data" "$TENANT_DIR" "$LAUNCH_AGENTS"

# --- 1. Python venv ----------------------------------------------------------
if [ ! -x "$VENV/bin/python3" ]; then
  log "creating venv"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q meilisearch

# --- 2. Meilisearch binary (pinned) -------------------------------------------
if [ ! -x "$BIN_DIR/meilisearch" ] \
   || ! "$BIN_DIR/meilisearch" --version 2>/dev/null | grep -q "$MEILI_VERSION"; then
  log "installing meilisearch $MEILI_VERSION"
  curl -fsSL -o "$BIN_DIR/meilisearch.tmp" \
    "https://github.com/meilisearch/meilisearch/releases/download/v${MEILI_VERSION}/meilisearch-macos-apple-silicon" \
    || fail "meilisearch download failed"
  chmod +x "$BIN_DIR/meilisearch.tmp"
  mv "$BIN_DIR/meilisearch.tmp" "$BIN_DIR/meilisearch"
fi

# --- 3. LaunchAgents (rewritten only on change) --------------------------------
TMP="$SERVER_DIR/.render.$$"

write_plist() { # path — body on stdin; echoes 1 if the file changed
  cat > "$TMP"
  if ! cmp -s "$TMP" "$1" 2>/dev/null; then
    mv "$TMP" "$1"; chmod 600 "$1"; echo 1
  else
    rm -f "$TMP"; echo 0
  fi
}

svc_loaded() { launchctl print "$GUI_DOMAIN/$1" >/dev/null 2>&1; }
svc_restart() { # (re)load with the current plist, restarting the process
  launchctl bootout "$GUI_DOMAIN/$1" 2>/dev/null || true
  for _ in $(seq 1 10); do svc_loaded "$1" || break; sleep 1; done
  for _ in $(seq 1 5); do
    launchctl bootstrap "$GUI_DOMAIN" "$LAUNCH_AGENTS/$1.plist" 2>/dev/null && return 0
    sleep 2
  done
  fail "could not bootstrap $1"
}

PL_MEILI=$(write_plist "$LAUNCH_AGENTS/com.svetogled.meilisearch.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>com.svetogled.meilisearch</string>
	<key>ProgramArguments</key>
	<array>
		<string>$BIN_DIR/meilisearch</string>
		<string>--db-path</string><string>$SERVER_DIR/meili-data</string>
		<string>--http-addr</string><string>127.0.0.1:7700</string>
		<string>--master-key</string><string>svetogled-search-key</string>
		<string>--env</string><string>production</string>
		<string>--no-analytics</string>
	</array>
	<key>WorkingDirectory</key><string>$SERVER_DIR</string>
	<key>RunAtLoad</key><true/>
	<key>KeepAlive</key><true/>
	<key>StandardOutPath</key><string>$LOG_DIR/meilisearch.log</string>
	<key>StandardErrorPath</key><string>$LOG_DIR/meilisearch.log</string>
</dict>
</plist>
EOF
)

PL_APP=$(write_plist "$LAUNCH_AGENTS/com.svetogled.app.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>com.svetogled.app</string>
	<key>ProgramArguments</key>
	<array>
		<string>$VENV/bin/python3</string>
		<string>search_app.py</string>
	</array>
	<key>WorkingDirectory</key><string>$APP_DIR</string>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PORT</key><string>$APP_PORT</string>
	</dict>
	<key>RunAtLoad</key><true/>
	<key>KeepAlive</key><true/>
	<key>StandardOutPath</key><string>$LOG_DIR/app.log</string>
	<key>StandardErrorPath</key><string>$LOG_DIR/app.log</string>
</dict>
</plist>
EOF
)

# --- 4. Meilisearch up ---------------------------------------------------------
if [ "$PL_MEILI" = "1" ] || ! svc_loaded com.svetogled.meilisearch; then
  svc_restart com.svetogled.meilisearch
fi
MEILI_OK=0
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:7700/health >/dev/null 2>&1 && { MEILI_OK=1; break; }
  sleep 2
done
[ "$MEILI_OK" = "1" ] || fail "meilisearch not healthy on :7700"

# --- 5. Re-index ----------------------------------------------------------------
log "re-indexing transcripts"
(cd "$APP_DIR" && "$VENV/bin/python3" index_to_meili.py --fresh)

# --- 6. Ingress drop-in (shared Caddy) -------------------------------------------
CADDY_CHANGED=0
cmp -s "$APP_DIR/mac/svetogled.caddy" "$TENANT_DIR/svetogled.caddy" 2>/dev/null || CADDY_CHANGED=1
install -m 644 "$APP_DIR/mac/svetogled.caddy" "$TENANT_DIR/svetogled.caddy"
if [ "$CADDY_CHANGED" = "1" ]; then
  if [ -x "$SHARED_CADDY_BIN" ] && [ -f "$SHARED_CADDYFILE" ]; then
    log "reloading shared caddy (tenant config changed)"
    # Env placeholders in the shared Caddyfile resolve at adapt time.
    ( set -a; [ -f "$SHARED_CADDY_ENV" ] && source "$SHARED_CADDY_ENV"; set +a
      "$SHARED_CADDY_BIN" reload --config "$SHARED_CADDYFILE" --adapter caddyfile ) \
      || log "WARNING: caddy reload failed — run cloudvideo's deploy or reload manually"
  else
    log "WARNING: shared caddy not found — ingress drop-in installed but not loaded"
  fi
fi

# --- 7. Restart app + health -------------------------------------------------------
if [ "$PL_APP" = "1" ] || ! svc_loaded com.svetogled.app; then
  svc_restart com.svetogled.app
else
  launchctl kickstart -k "$GUI_DOMAIN/com.svetogled.app"
fi

APP_OK=0
for _ in $(seq 1 15); do
  curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/" 2>/dev/null && { APP_OK=1; break; }
  sleep 2
done
[ "$APP_OK" = "1" ] || fail "app not answering on :$APP_PORT"

# Local TLS probe through the shared Caddy (the real outside-in probe is the
# GitHub-hosted health job in deploy.yml).
if curl -fsSk --max-time 10 --resolve "svetogled-arhiv.com:443:127.0.0.1" \
     -o /dev/null "https://svetogled-arhiv.com/" 2>/dev/null; then
  log "local TLS probe OK"
else
  log "WARNING: local TLS probe failed (cert may still be provisioning)"
fi

log "OK — meilisearch $("$BIN_DIR/meilisearch" --version 2>/dev/null | tr -d '\n'), app on :$APP_PORT, $(git -C "$APP_DIR" rev-parse --short HEAD)"
