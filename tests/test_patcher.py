import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "patch_source.py"

FIXTURE = '''use std::time::Duration;
async fn f() {
    if let Ok((Some(status), current_song)) = mpd.with_client(|client| async move {
        let status = client.command(commands::Status).await.ok();
        let current_song = if status.is_some() {
            client.command(commands::CurrentSong).await.ok().flatten()
        } else { None };
        (status, current_song)
    }).await {
        service.update_state(&status, current_song).await;
    }
    if let Ok((Some(status), current_song)) = mpd.with_client(|client| async move {
        let status = client.command(commands::Status).await.ok();
        let current_song = if status.is_some() {
            client.command(commands::CurrentSong).await.ok().flatten()
        } else { None };
        (status, current_song)
    }).await {
        service.update_state(&status, current_song).await;
    }
}
async fn update_state(&mut self, status: &Status, current_song: Option<SongInQueue>) {
    let url = self.album_art_client.get_album_art_url(song).await;
}
/// Extracts the formatting tokens from a formatting string
'''


class PatcherTests(unittest.TestCase):
    def test_patches_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "main.rs"
            source.write_text(FIXTURE)
            first = subprocess.run([sys.executable, str(PATCHER), str(source)], text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            patched = source.read_text()
            self.assertEqual(patched.count("client.album_art(&current.song.url)"), 2)
            self.assertEqual(patched.count("publish_embedded_art(embedded_art)"), 1)
            second = subprocess.run([sys.executable, str(PATCHER), str(source)], text=True, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("already present and verified", second.stdout)

    def test_refuses_unknown_source_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "main.rs"
            source.write_text("fn main() {}\n")
            before = source.read_text()
            result = subprocess.run([sys.executable, str(PATCHER), str(source)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_text(), before)


if __name__ == "__main__":
    unittest.main()
