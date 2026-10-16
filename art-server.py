#!/usr/bin/env python3
"""Expose only the current cover image; never list or serve the music library."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

ART_DIR = Path(os.environ.get("MPD_DISCORD_RPC_ART_DIR", str(Path.home() / ".cache/mpd-discord-rpc-art")))
HOST = "127.0.0.1"
PORT = int(os.environ.get("MPD_DISCORD_RPC_ART_SERVER_PORT", "8765"))
MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".avif": "image/avif",
}
ALLOWED = {"cover.jpg", "cover.jpeg", "cover.png", "cover.webp", "cover.gif", "cover.avif"}

class Handler(BaseHTTPRequestHandler):
    server_version = "MPDDiscordArtwork/1.0"

    def do_HEAD(self):
        self._serve(send_body=False)

    def do_GET(self):
        self._serve(send_body=True)

    def _serve(self, send_body: bool):
        from urllib.parse import urlsplit
        name = urlsplit(self.path).path.lstrip("/")
        if name not in ALLOWED:
            self.send_error(404)
            return
        path = ART_DIR / name
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return
        except OSError:
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES[path.suffix.lower()])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if send_body:
            self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"HTTP {self.address_string()} - {fmt % args}", flush=True)

if __name__ == "__main__":
    ART_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Serving current embedded artwork only on http://{HOST}:{PORT}/", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
