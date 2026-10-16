#!/usr/bin/env python3
"""One-process supervisor for the RPC, private local cover server, and Quick Tunnel."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
HOME = Path.home()
ART_DIR = Path(os.environ.get("MPD_DISCORD_RPC_ART_DIR", str(HOME / ".cache/mpd-discord-rpc-art"))).expanduser()
RPC_BIN = Path(os.environ.get("MPD_DISCORD_RPC_BIN", str(HOME / ".local/bin/mpd-discord-rpc"))).expanduser()
SERVER_PORT = int(os.environ.get("MPD_DISCORD_RPC_ART_SERVER_PORT", "8765"))
TUNNEL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
STOP = threading.Event()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s mpd-discord-art-supervisor: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("mpd-discord-art-supervisor")


def request_stop(signum, _frame):
    log.info("Received signal %s; shutting down child processes", signum)
    STOP.set()


for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(sig, request_stop)


def stop_process(proc: subprocess.Popen | None, name: str, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    log.info("Stopping %s", name)
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        log.warning("%s did not stop in %.1fs; killing it", name, timeout)
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def start_streamed(label: str, command: list[str], env: dict[str, str], notifications=None):
    log.info("Starting %s: %s", label, " ".join(command))
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
        env=env,
    )

    def pump():
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                log.info("[%s] %s", label, line)
                if notifications is not None:
                    notifications.put((proc.pid, line))
        except (OSError, ValueError) as exc:
            log.debug("Output reader for %s ended: %s", label, exc)

    threading.Thread(target=pump, name=f"log-{label}", daemon=True).start()
    return proc


def wait_for_tunnel(cloudflared: str, base_env: dict[str, str]):
    """Start a Quick Tunnel and return it once its public URL appears in logs."""
    delay = 3
    while not STOP.is_set():
        notices: queue.Queue = queue.Queue()
        tunnel = start_streamed(
            "cloudflared",
            [cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{SERVER_PORT}"],
            base_env,
            notices,
        )
        deadline = time.monotonic() + 90
        public_url = None
        while not STOP.is_set() and tunnel.poll() is None and time.monotonic() < deadline:
            try:
                pid, line = notices.get(timeout=0.5)
            except queue.Empty:
                continue
            if pid == tunnel.pid:
                match = TUNNEL_PATTERN.search(line)
                if match:
                    public_url = match.group(0)
                    break
        if public_url and tunnel.poll() is None:
            log.info("Quick Tunnel ready: %s", public_url)
            return tunnel, public_url

        if not STOP.is_set():
            if tunnel.poll() is None:
                log.warning("Timed out waiting for Cloudflare Quick Tunnel URL")
            else:
                log.warning("cloudflared exited before publishing a URL (code %s)", tunnel.returncode)
        stop_process(tunnel, "cloudflared")
        if STOP.wait(delay):
            break
        delay = min(delay * 2, 30)
    return None, None


def main() -> int:
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        log.error("cloudflared was not found in PATH. Install it and restart this service.")
        return 127
    if not RPC_BIN.is_file() or not os.access(RPC_BIN, os.X_OK):
        log.error("Patched RPC binary is missing or not executable: %s", RPC_BIN)
        return 127

    ART_DIR.mkdir(parents=True, exist_ok=True)
    base_env = os.environ.copy()
    base_env["MPD_DISCORD_RPC_ART_DIR"] = str(ART_DIR)
    base_env["MPD_DISCORD_RPC_ART_SERVER_PORT"] = str(SERVER_PORT)
    base_env["PYTHONUNBUFFERED"] = "1"

    server = start_streamed(
        "art-server",
        [sys.executable, str(HERE / "art-server.py")],
        base_env,
    )
    time.sleep(0.6)
    if server.poll() is not None:
        log.error("Artwork HTTP server exited immediately; is port %s already in use?", SERVER_PORT)
        return 1

    try:
        while not STOP.is_set():
            tunnel, public_url = wait_for_tunnel(cloudflared, base_env)
            if STOP.is_set():
                break
            if tunnel is None or public_url is None:
                continue

            rpc = None
            restart_rpc_at = 0.0
            while not STOP.is_set():
                if server.poll() is not None:
                    log.error("Artwork HTTP server exited (code %s)", server.returncode)
                    stop_process(rpc, "mpd-discord-rpc")
                    stop_process(tunnel, "cloudflared")
                    return 1
                if tunnel.poll() is not None:
                    log.warning("Cloudflare tunnel ended (code %s); renewing URL and RPC", tunnel.returncode)
                    break
                if rpc is None and time.monotonic() >= restart_rpc_at:
                    child_env = base_env.copy()
                    child_env["MPD_DISCORD_RPC_ART_BASE_URL"] = public_url
                    log.info("Launching RPC with embedded-art URL %s", public_url)
                    rpc = start_streamed("mpd-discord-rpc", [str(RPC_BIN)], child_env)
                elif rpc is not None and rpc.poll() is not None:
                    log.warning("mpd-discord-rpc exited (code %s); retrying in 2 seconds", rpc.returncode)
                    rpc = None
                    restart_rpc_at = time.monotonic() + 2
                STOP.wait(0.5)

            stop_process(rpc, "mpd-discord-rpc")
            stop_process(tunnel, "cloudflared")
            if not STOP.is_set():
                STOP.wait(2)

    finally:
        STOP.set()
        stop_process(server, "art-server")
    log.info("Supervisor stopped cleanly")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        STOP.set()
        raise SystemExit(0)
