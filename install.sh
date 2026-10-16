#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/src/mpd-discord-rpc-embedded-art"
BIN_DIR="$HOME/.local/bin"
LIBEXEC_DIR="$HOME/.local/libexec/mpd-discord-rpc-embedded-art"
ART_DIR="$HOME/.cache/mpd-discord-rpc-art"
DROPIN_DIR="$HOME/.config/systemd/user/mpd-discord-rpc.service.d"
DROPIN="$DROPIN_DIR/embedded-art.conf"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/mpd-discord-rpc-embedded-art"
BACKUP="$STATE_DIR/previous-embedded-art.conf"
PORT=8765
UPSTREAM_REF="${MPD_DISCORD_RPC_UPSTREAM_REF:-v1.11.0}"

fail() { echo "ERROR: $*" >&2; exit 1; }
for cmd in git cargo rustc python3 systemctl install; do
    command -v "$cmd" >/dev/null 2>&1 || fail "Required command '$cmd' was not found. Install it and retry."
done
command -v cloudflared >/dev/null 2>&1 || fail "cloudflared was not found in PATH. Install cloudflared first."
systemctl --user cat mpd-discord-rpc.service >/dev/null 2>&1 || fail "The mpd-discord-rpc user systemd service was not found. Install mpd-discord-rpc first."

# If this setup was already installed, stop its supervisor before checking port 8765.
if [[ -f "$DROPIN" ]] && grep -q 'mpd-discord-rpc-embedded-art/supervisor.py' "$DROPIN"; then
    systemctl --user stop mpd-discord-rpc.service || true
fi

if python3 - "$PORT" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.25)
try:
    busy = s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0
finally:
    s.close()
sys.exit(0 if busy else 1)
PY
then
    fail "Port $PORT is already serving something on localhost. Stop the manually started 'python -m http.server 8765' terminal (Ctrl+C), then rerun this installer. Also stop your manually started cloudflared Quick Tunnel so only systemd manages it."
fi

mkdir -p "$(dirname "$SRC_DIR")" "$BIN_DIR" "$LIBEXEC_DIR" "$ART_DIR" "$DROPIN_DIR" "$STATE_DIR"

if [[ ! -d "$SRC_DIR/.git" ]]; then
    [[ ! -e "$SRC_DIR" ]] || fail "Refusing to overwrite non-git path: $SRC_DIR"
    echo "Cloning upstream mpd-discord-rpc source into $SRC_DIR"
    git clone --depth 1 --branch "$UPSTREAM_REF" https://github.com/JakeStanger/mpd-discord-rpc.git "$SRC_DIR"
else
    echo "Using existing source tree: $SRC_DIR"
fi

# Preserve the previous static-URL drop-in for reference, but do not restore it on uninstall:
# its Quick Tunnel URL is temporary and may already be dead.
if [[ -f "$DROPIN" ]] && ! grep -q 'mpd-discord-rpc-embedded-art/supervisor.py' "$DROPIN" && [[ ! -e "$BACKUP" ]]; then
    cp -p "$DROPIN" "$BACKUP"
fi

install -m755 "$PACKAGE_DIR/patch_source.py" "$LIBEXEC_DIR/patch_source.py"
install -m755 "$PACKAGE_DIR/supervisor.py" "$LIBEXEC_DIR/supervisor.py"
install -m755 "$PACKAGE_DIR/art-server.py" "$LIBEXEC_DIR/art-server.py"
install -m755 "$PACKAGE_DIR/mpd-discord-art" "$BIN_DIR/mpd-discord-art"

python3 "$LIBEXEC_DIR/patch_source.py" "$SRC_DIR/src/main.rs"
echo "Building patched RPC binary (package-managed binary is left untouched)..."
cargo build --locked --release --manifest-path "$SRC_DIR/Cargo.toml"
install -Dm755 "$SRC_DIR/target/release/mpd-discord-rpc" "$BIN_DIR/mpd-discord-rpc"

cat > "$DROPIN" <<EOF
[Service]
ExecStart=
ExecStart="$LIBEXEC_DIR/supervisor.py"
Environment="MPD_DISCORD_RPC_ART_DIR=$ART_DIR"
Environment=MPD_DISCORD_RPC_ART_SERVER_PORT=$PORT
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=15
EOF

systemctl --user daemon-reload
systemctl --user enable mpd-discord-rpc.service >/dev/null
systemctl --user restart mpd-discord-rpc.service
sleep 2
if ! systemctl --user is-active --quiet mpd-discord-rpc.service; then
    echo "The service did not remain active. Recent logs:" >&2
    journalctl --user -u mpd-discord-rpc.service -n 80 --no-pager >&2 || true
    fail "Installation files are in place, but the service failed to start."
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "NOTE: $BIN_DIR is not on PATH. Add 'export PATH=\"$BIN_DIR:\$PATH\"' to your shell profile, then open a new shell." ;;
esac

cat <<EOF

Installed: embedded-cover Discord Rich Presence

The service now manages all three parts automatically:
  - patched mpd-discord-rpc
  - local cover-only HTTP server on 127.0.0.1:$PORT
  - Cloudflare Quick Tunnel (the current URL is detected automatically)

No terminals need to stay open. The service starts at your next user login.

Useful commands:
  mpd-discord-art status    Show service status
  mpd-discord-art logs      Follow service and tunnel logs
  mpd-discord-art url       Print the most recently logged Quick Tunnel URL
  mpd-discord-art restart   Restart the full setup
  mpd-discord-art stop      Stop everything
  mpd-discord-art start     Start everything

Raw systemd commands:
  systemctl --user status mpd-discord-rpc
  journalctl --user -fu mpd-discord-rpc

Uninstall/revert:
  bash "$PACKAGE_DIR/uninstall.sh"

Note: Quick Tunnel URLs change when cloudflared restarts. This supervisor detects the new URL and restarts the RPC with it. The artwork endpoint is public to anyone who has that URL; it only serves the current cover images, not your music files.
EOF
