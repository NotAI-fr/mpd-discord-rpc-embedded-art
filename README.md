# MPD Discord RPC — Embedded Cover Art

An unofficial Linux add-on for [`mpd-discord-rpc`](https://github.com/JakeStanger/mpd-discord-rpc) that makes Discord Rich Presence use the cover embedded in the currently playing MPD track first, rather than an unrelated MusicBrainz match. If MPD has no embedded/local artwork, the original online lookup remains the fallback.

The installer leaves the distro/AUR-managed executable alone. It builds a patched copy under `~/.local/bin/` and uses one `systemd --user` service to manage the RPC, a small local image server, and a Cloudflare Quick Tunnel. No terminal windows need to stay open.

## Requirements

You need all of the following:

- Linux with `systemd --user`.
- A working MPD server and a working Discord desktop client.
- The upstream `mpd-discord-rpc` package and its user service (`mpd-discord-rpc.service`).
- `git`, Rust/Cargo, Python 3.10+, and `cloudflared` in `PATH`.
- Internet access when building and while showing covers to Discord.

### Arch Linux

Install build/runtime dependencies:

```bash
sudo pacman -S --needed git rust python cloudflared
```

Install `mpd-discord-rpc` separately if you don't already have it. For example, with an AUR helper:

```bash
yay -S mpd-discord-rpc
```

The package/source names can differ on other distributions. This repository does **not** install or configure MPD itself, install Discord, or install the upstream `mpd-discord-rpc` package for you.

## Publish this folder as your GitHub repository

1. Create an **empty** repository on GitHub named `mpd-discord-rpc-embedded-art` (do not pre-create a README or license there; this folder already contains both).
2. From this project folder, run the following, replacing the owner name:

```bash
git init
git add .
git commit -m "Initial release"
git branch -M main
git remote add origin https://github.com/<YOUR-USERNAME>/mpd-discord-rpc-embedded-art.git
git push -u origin main
```

After it is published, other machines can follow the install command below using the real repository URL.

## Install

Once requirements are installed:

```bash
git clone https://github.com/<YOUR-USERNAME>/mpd-discord-rpc-embedded-art.git
cd mpd-discord-rpc-embedded-art
bash install.sh
```

Replace `<YOUR-USERNAME>` with the GitHub account that hosts this repository. The installer:

1. Checks required commands and confirms the upstream user service exists.
2. Clones upstream `mpd-discord-rpc` at `v1.11.0` for a fresh install, then applies a guarded patch. If you've already got the source clone from an earlier install, it reuses that clone.
3. Builds with Cargo's lockfile (`--locked`) and only switches the user service after a successful build.
4. Installs the helper command and a systemd override, then enables and starts the service.

The package-managed binary is not replaced. The first build downloads Rust dependencies and may take a little while.

If the installer reports that port `8765` is occupied, stop any manually started Python HTTP server or old test setup on that port, then rerun `bash install.sh`.

## Everyday commands

```bash
mpd-discord-art start
mpd-discord-art stop
mpd-discord-art restart
mpd-discord-art status
mpd-discord-art logs
mpd-discord-art url
```

- `start` / `stop` start or stop the full setup.
- `restart` refreshes the RPC, artwork server, and tunnel.
- `status` shows the systemd user service.
- `logs` follows the combined logs; press `Ctrl+C` to stop viewing logs, not the service.
- `url` prints the latest Quick Tunnel URL.

Raw service controls are also available:

```bash
systemctl --user status mpd-discord-rpc.service
systemctl --user enable mpd-discord-rpc.service   # start at user login
systemctl --user disable mpd-discord-rpc.service  # disable autostart
journalctl --user -fu mpd-discord-rpc.service
```

The helper is installed to `~/.local/bin/mpd-discord-art`. If your shell cannot find it, ensure `~/.local/bin` is on your `PATH`, then open a new shell.

## How the artwork path works

1. The patched RPC asks MPD for the current track's artwork.
2. The embedded image is written to `~/.cache/mpd-discord-rpc-art/`.
3. A local HTTP server bound only to `127.0.0.1:8765` exposes allow-listed image filenames only; it does not list directories or serve music files.
4. `cloudflared` creates a public HTTPS Quick Tunnel to that image server.
5. If the Quick Tunnel URL changes, the supervisor restarts the RPC using the new URL.

### Privacy and reliability notes

- Cloudflare Quick Tunnels are intended for testing/development and use temporary `trycloudflare.com` hostnames; no Cloudflare account or domain is needed. A URL may change after a restart.
- Anyone who gets the current tunnel URL can fetch the current cover image. Do not place private images in the artwork cache while the tunnel is running. The service exposes cover images only, not your music files.
- The service requires the network for Discord presence and tunnel operation.

See [Cloudflare Quick Tunnels documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Troubleshooting

```bash
mpd-discord-art status
journalctl --user -u mpd-discord-rpc.service -n 100 --no-pager
```

- **Service won't start:** use `status` and the journal command above.
- **Port 8765 is occupied:** stop any manual HTTP server on that port and rerun the installer.
- **Wrong/stale cover:** switch tracks and run `mpd-discord-art logs`; look for `Published MPD artwork at` and `Quick Tunnel ready`.
- **Missing dependency:** install the command named in the installer's error message.
- **Source mismatch:** the patcher stops instead of guessing if the upstream source structure differs. Review the error before changing or deleting the source clone.

## Uninstall / rollback

Restore the original package-managed systemd service configuration:

```bash
bash uninstall.sh
```

Remove the add-on's user-local binary, source clone, state, and cached cover too:

```bash
bash uninstall.sh --purge
```

Neither option uninstalls the distro/AUR `mpd-discord-rpc` package. `--purge` removes the add-on's `~/.local/bin/mpd-discord-rpc`, so use it only if that path is the copy installed by this project.

## Development checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q art-server.py supervisor.py patch_source.py
bash -n install.sh uninstall.sh mpd-discord-art
```

## Attribution

This is an independent add-on, not affiliated with or endorsed by Jake Stanger, Discord, or Cloudflare. It fetches the upstream [`mpd-discord-rpc`](https://github.com/JakeStanger/mpd-discord-rpc) source at install time; upstream has its own MIT license. This repository's own installer and helper scripts are MIT-licensed.
