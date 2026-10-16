#!/usr/bin/env python3
"""Apply the reproducible embedded-art patch to mpd-discord-rpc/src/main.rs."""
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit(f"Usage: {sys.argv[0]} /path/to/mpd-discord-rpc/src/main.rs")

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(f"Source file not found: {path}")
s = path.read_text()

# Existing patch: confirm it is the version this setup expects, and repair the
# historical `.file` typo if the rest of the patch is already present.
if "fn publish_embedded_art(" in s or "MPD_DISCORD_RPC_ART_BASE_URL" in s:
    if "fn publish_embedded_art(" not in s or "MPD_DISCORD_RPC_ART_BASE_URL" not in s:
        raise SystemExit("Source has a partial/unknown embedded-art patch; refusing to guess at repairs.")
    bad = "client.album_art(&current.song.file)"
    good = "client.album_art(&current.song.url)"
    if s.count(good) == 2:
        print("Embedded-art patch already present and verified.")
    elif s.count(bad) == 2:
        s = s.replace(bad, good)
        path.write_text(s)
        print("Repaired both Song field references (.file -> .url).")
    else:
        raise SystemExit(
            "Embedded-art patch exists but its MPD artwork calls do not match the expected source; refusing to modify it."
        )
    sys.exit(0)

old_import = "use std::time::Duration;"
new_import = (
    "use std::fs;\n"
    "use std::hash::{Hash, Hasher};\n"
    "use std::path::PathBuf;\n"
    "use std::time::Duration;"
)
if s.count(old_import) != 1:
    raise SystemExit("Could not find the expected import line; no source patch written.")
s = s.replace(old_import, new_import, 1)

tuple_pattern = re.compile(r"(?m)^([ \t]*)\(status, current_song\)[ \t]*$")

def add_artwork_fetch(match: re.Match[str]) -> str:
    i = match.group(1)
    return (
        f'{i}let embedded_art = if std::env::var_os("MPD_DISCORD_RPC_ART_BASE_URL").is_some() {{\n'
        f'{i}    if let Some(current) = current_song.as_ref() {{\n'
        f'{i}        client.album_art(&current.song.url).await.ok().flatten()\n'
        f'{i}            .map(|(data, mime)| (data.to_vec(), mime))\n'
        f'{i}    }} else {{\n'
        f'{i}        None\n'
        f'{i}    }}\n'
        f'{i}}} else {{\n'
        f'{i}    None\n'
        f'{i}}};\n'
        f'{i}(status, current_song, embedded_art)'
    )

s, tuple_count = tuple_pattern.subn(add_artwork_fetch, s)
if tuple_count != 2:
    raise SystemExit(f"Expected to update 2 MPD state tuples, found {tuple_count}; no patched source written.")

old_outer = "if let Ok((Some(status), current_song)) = mpd.with_client"
if s.count(old_outer) != 2:
    raise SystemExit(f"Expected 2 outer MPD result patterns, found {s.count(old_outer)}; no patched source written.")
s = s.replace(old_outer, "if let Ok((Some(status), current_song, embedded_art)) = mpd.with_client")

old_call = "service.update_state(&status, current_song).await;"
if s.count(old_call) != 2:
    raise SystemExit(f"Expected 2 service update calls, found {s.count(old_call)}; no patched source written.")
s = s.replace(old_call, "service.update_state(&status, current_song, embedded_art).await;")

old_sig = "async fn update_state(&mut self, status: &Status, current_song: Option<SongInQueue>) {"
new_sig = (
    "async fn update_state(&mut self, status: &Status, current_song: Option<SongInQueue>, "
    "embedded_art: Option<(Vec<u8>, Option<String>)>) {"
)
if s.count(old_sig) != 1:
    raise SystemExit("Could not find update_state signature; no source patch written.")
s = s.replace(old_sig, new_sig, 1)

old_art = "let url = self.album_art_client.get_album_art_url(song).await;"
new_art = (
    "let url = match publish_embedded_art(embedded_art) {\n"
    "                    Some(url) => Some(url),\n"
    "                    None => self.album_art_client.get_album_art_url(song).await,\n"
    "                };"
)
if s.count(old_art) != 1:
    raise SystemExit("Could not find MusicBrainz artwork lookup; no source patch written.")
s = s.replace(old_art, new_art, 1)

anchor = "/// Extracts the formatting tokens from a formatting string"
helper = r'''fn publish_embedded_art(artwork: Option<(Vec<u8>, Option<String>)>) -> Option<String> {
    let (data, mime) = artwork?;
    let base_url = std::env::var("MPD_DISCORD_RPC_ART_BASE_URL").ok()?;
    let extension = image_extension(&data, mime.as_deref())?;
    let art_dir = std::env::var_os("MPD_DISCORD_RPC_ART_DIR")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os("HOME")
                .map(|home| PathBuf::from(home).join(".cache/mpd-discord-rpc-art"))
        })?;

    if let Err(err) = fs::create_dir_all(&art_dir) {
        error!("Could not create artwork directory: {err}");
        return None;
    }

    let filename = format!("cover.{extension}");
    let destination = art_dir.join(&filename);
    let temporary = art_dir.join(format!(".{filename}.tmp"));
    if let Err(err) = fs::write(&temporary, &data) {
        error!("Could not write embedded artwork: {err}");
        return None;
    }
    if let Err(err) = fs::rename(&temporary, &destination) {
        error!("Could not publish embedded artwork: {err}");
        let _ = fs::remove_file(&temporary);
        return None;
    }

    for other_extension in ["jpg", "png", "webp", "gif", "avif"] {
        if other_extension != extension {
            let _ = fs::remove_file(art_dir.join(format!("cover.{other_extension}")));
        }
    }

    // A content-derived query string lets Discord distinguish changed artwork.
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    data.hash(&mut hasher);
    let version = hasher.finish();
    let url = format!("{}/{}?v={version:016x}", base_url.trim_end_matches('/'), filename);
    info!("Published MPD artwork at {url}");
    Some(url)
}

fn image_extension(data: &[u8], mime: Option<&str>) -> Option<&'static str> {
    let from_mime = mime
        .and_then(|value| value.split(';').next())
        .map(|value| value.trim().to_ascii_lowercase())
        .and_then(|value| match value.as_str() {
            "image/jpeg" | "image/jpg" => Some("jpg"),
            "image/png" => Some("png"),
            "image/webp" => Some("webp"),
            "image/gif" => Some("gif"),
            "image/avif" => Some("avif"),
            _ => None,
        });
    from_mime.or_else(|| {
        if data.starts_with(b"\xFF\xD8\xFF") {
            Some("jpg")
        } else if data.starts_with(b"\x89PNG\r\n\x1A\n") {
            Some("png")
        } else if data.starts_with(b"RIFF") && data.get(8..12).is_some_and(|tag| tag == b"WEBP") {
            Some("webp")
        } else if data.starts_with(b"GIF87a") || data.starts_with(b"GIF89a") {
            Some("gif")
        } else if data.len() >= 12
            && &data[4..8] == b"ftyp"
            && (&data[8..12] == b"avif" || &data[8..12] == b"avis")
        {
            Some("avif")
        } else {
            None
        }
    })
}

'''
if s.count(anchor) != 1:
    raise SystemExit("Could not find helper insertion point; no source patch written.")
s = s.replace(anchor, helper + anchor, 1)
path.write_text(s)
print("Patched main.rs to prefer MPD artwork, cache the image, and retain MusicBrainz fallback.")
