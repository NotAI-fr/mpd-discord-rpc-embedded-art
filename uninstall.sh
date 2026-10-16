#!/usr/bin/env bash
set -euo pipefail

LIBEXEC_DIR="$HOME/.local/libexec/mpd-discord-rpc-embedded-art"
BIN_DIR="$HOME/.local/bin"
DROPIN="$HOME/.config/systemd/user/mpd-discord-rpc.service.d/embedded-art.conf"
PURGE=0
if [[ "${1:-}" == "--purge" ]]; then PURGE=1; elif [[ -n "${1:-}" ]]; then echo "Usage: $0 [--purge]" >&2; exit 2; fi

systemctl --user stop mpd-discord-rpc.service 2>/dev/null || true
rm -f "$DROPIN"
systemctl --user daemon-reload
rm -rf "$LIBEXEC_DIR"
rm -f "$BIN_DIR/mpd-discord-art"

if systemctl --user cat mpd-discord-rpc.service >/dev/null 2>&1; then
  systemctl --user restart mpd-discord-rpc.service || true
fi

if [[ "$PURGE" == 1 ]]; then
  rm -f "$BIN_DIR/mpd-discord-rpc"
  rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/src/mpd-discord-rpc-embedded-art"
  rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/mpd-discord-rpc-embedded-art"
  rm -rf "$HOME/.cache/mpd-discord-rpc-art"
  echo "Removed the patched user binary, source clone, state backup, and artwork cache. The distro/AUR package was not removed."
else
  echo "Removed the supervisor and restored the package's original user service configuration."
  echo "The patched binary/source and cached cover were left in place as a safety backup."
  echo "For full cleanup of those user-local files, rerun: bash $0 --purge"
fi
