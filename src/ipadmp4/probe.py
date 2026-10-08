"""Inspect a movie's streams with ffprobe and find subtitle files next to it."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .errors import Ipadmp4Error
from .tracks import (
    UNKNOWN_LANGUAGE,
    AudioTrack,
    MediaInfo,
    SubtitleTrack,
    VideoStream,
    language_code,
    normalize_language,
)

_COMMENTARY = re.compile(r"comment|descriptive|audio description|\bAD\b", re.IGNORECASE)
_SDH = re.compile(r"\bSDH\b|\bCC\b|\bHI\b|hearing", re.IGNORECASE)
_FORCED = re.compile(r"forced|foreign parts", re.IGNORECASE)

# Words in external subtitle file names like "Movie.en.sdh.srt".
_SDH_WORDS = frozenset({"sdh", "cc", "hi"})
_FORCED_WORDS = frozenset({"forced", "foreign"})


def parse_ffprobe_json(text: str) -> MediaInfo:
    """Turn `ffprobe -show_streams -of json` output into a MediaInfo.

    Only the first real video stream is used; cover art (an "attached
    picture") also shows up as a video stream and is skipped.
    """
    streams = json.loads(text).get("streams", [])
    video = None
    audio = []
    subtitles = []
    for s in streams:
        kind = s.get("codec_type")
        codec = s.get("codec_name", "unknown")
        tags = {k.lower(): v for k, v in s.get("tags", {}).items()}
        disposition = s.get("disposition", {})
        title = tags.get("title", "").strip()
        language = normalize_language(tags.get("language"))
        if kind == "video" and video is None:
            if disposition.get("attached_pic") == 1:
                continue
            video = VideoStream(
                index=s["index"],
                codec=codec,
                width=int(s.get("width", 0)),
                height=int(s.get("height", 0)),
                pix_fmt=s.get("pix_fmt", ""),
            )
        elif kind == "audio":
            audio.append(
                AudioTrack(
                    index=s["index"],
                    codec=codec,
                    channels=int(s.get("channels", 2)),
                    language=language,
                    title=title,
                    profile=s.get("profile", ""),
                    default=disposition.get("default") == 1,
                    commentary=bool(
                        disposition.get("comment") == 1
                        or disposition.get("visual_impaired") == 1
                        or _COMMENTARY.search(title)
                    ),
                )
            )
        elif kind == "subtitle":
            subtitles.append(
                SubtitleTrack(
                    codec=codec,
                    language=language,
                    title=title,
                    forced=bool(disposition.get("forced") == 1 or _FORCED.search(title)),
                    sdh=bool(disposition.get("hearing_impaired") == 1 or _SDH.search(title)),
                    index=s["index"],
                )
            )
    return MediaInfo(video=video, audio=tuple(audio), subtitles=tuple(subtitles))


def external_subtitles(movie: Path) -> list[SubtitleTrack]:
    """SRT files belonging to `movie`: "Movie.srt", "Movie.en.srt", "Movie.English.SDH.srt", ...

    The language comes from the file name; a file without one is assumed to
    be English, as that is what an untagged subtitle file next to a movie
    usually is.
    """
    prefix = movie.stem + "."
    found = []
    try:
        candidates = sorted(movie.parent.iterdir())
    except OSError:
        return []
    for path in candidates:
        name = path.name
        if not (name.startswith(prefix) and name.lower().endswith(".srt")) or not path.is_file():
            continue
        words = [w.lower() for w in name[len(prefix) : -len(".srt")].split(".") if w]
        found.append(
            SubtitleTrack(
                codec="subrip",
                language=_language_from_words(words),
                sdh=any(w in _SDH_WORDS for w in words),
                forced=any(w in _FORCED_WORDS for w in words),
                path=path,
                charset=_charset(path),
            )
        )
    return found


def _language_from_words(words: list[str]) -> str:
    others = [w for w in words if w not in _SDH_WORDS | _FORCED_WORDS]
    if not others:
        return "eng"  # "Movie.srt", "Movie.sdh.srt"
    for w in others:
        if code := language_code(w):
            return code
    for w in others:
        # An unknown three-letter code like "cze" is still a language.
        if len(w) == 3 and w.isalpha():
            return w
    return UNKNOWN_LANGUAGE


def _charset(path: Path) -> str | None:
    """None for UTF-8 (ffmpeg's default); otherwise assume Windows Latin-1, the usual alternative."""
    try:
        path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return "CP1252"
    except OSError:
        return None
    return None


def probe(path: Path) -> MediaInfo:
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise Ipadmp4Error(f"ffprobe could not read {path}: {detail}")
    info = parse_ffprobe_json(result.stdout)
    return MediaInfo(video=info.video, audio=info.audio, subtitles=(*info.subtitles, *external_subtitles(path)))
