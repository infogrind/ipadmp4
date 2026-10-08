"""The streams of a movie, as far as track selection cares about them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

UNKNOWN_LANGUAGE = "und"

# Subtitles stored as pictures. MP4 on iOS can only hold toggleable *text*
# subtitles, so these can only be burned into the video.
IMAGE_SUBTITLE_CODECS = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})

# Several spellings for the same language: ISO 639-1, both ISO 639-2 forms,
# and English names (used in external subtitle file names like
# "Movie.English.srt"). Everything maps to one ISO 639-2 code, so "ger" in
# one file and "deu" in the next count as the same language.
_LANGUAGE_ALIASES = {
    "eng": ("en", "english"),
    "ger": ("de", "deu", "german", "deutsch"),
    "fre": ("fr", "fra", "french", "francais"),
    "spa": ("es", "spanish", "espanol"),
    "ita": ("it", "italian"),
    "jpn": ("ja", "japanese"),
    "kor": ("ko", "korean"),
    "chi": ("zh", "zho", "chinese"),
    "rus": ("ru", "russian"),
    "por": ("pt", "portuguese"),
    "dut": ("nl", "nld", "dutch"),
    "swe": ("sv", "swedish"),
    "dan": ("da", "danish"),
    "nor": ("no", "nb", "nob", "norwegian"),
    "fin": ("fi", "finnish"),
    "pol": ("pl", "polish"),
    "hin": ("hi", "hindi"),
}
_ALIAS_TO_CODE = {alias: code for code, aliases in _LANGUAGE_ALIASES.items() for alias in (code, *aliases)}


def normalize_language(value: str | None) -> str:
    """Return a 3-letter language code; unknown or missing gives 'und'.

    Tolerates IETF tags ("en-US") and English names ("English").
    """
    if not value:
        return UNKNOWN_LANGUAGE
    value = value.strip().lower().replace("_", "-")
    if value in _ALIAS_TO_CODE:
        return _ALIAS_TO_CODE[value]
    base = value.split("-")[0]
    if base in _ALIAS_TO_CODE:
        return _ALIAS_TO_CODE[base]
    if len(base) == 3 and base.isalpha():
        return base
    return UNKNOWN_LANGUAGE


def language_code(token: str) -> str | None:
    """The language a file-name token like "en" or "English" stands for, if any.

    Only known spellings count, so tokens like "sdh" or "x264" are no language.
    """
    return _ALIAS_TO_CODE.get(token.strip().lower())


@dataclass(frozen=True)
class VideoStream:
    index: int
    codec: str
    width: int
    height: int
    pix_fmt: str

    @property
    def bit_depth(self) -> int:
        return 10 if ("10" in self.pix_fmt or "p010" in self.pix_fmt) else 8


@dataclass(frozen=True)
class AudioTrack:
    index: int
    codec: str
    channels: int
    language: str
    title: str = ""
    profile: str = ""
    default: bool = False
    # Director's commentary or audio description for the blind: never
    # picked automatically.
    commentary: bool = False


@dataclass(frozen=True)
class SubtitleTrack:
    codec: str
    language: str
    title: str = ""
    forced: bool = False
    sdh: bool = False
    # Exactly one of these is set: the stream index inside the movie, or a
    # separate subtitle file next to it.
    index: int | None = None
    path: Path | None = None
    # Character set of an external file, when it isn't UTF-8.
    charset: str | None = None

    @property
    def image(self) -> bool:
        return self.codec in IMAGE_SUBTITLE_CODECS

    @property
    def external(self) -> bool:
        return self.path is not None


@dataclass(frozen=True)
class MediaInfo:
    video: VideoStream | None
    audio: tuple[AudioTrack, ...]
    subtitles: tuple[SubtitleTrack, ...]


_AUDIO_CODEC_NAMES = {
    "ac3": "AC-3",
    "eac3": "E-AC-3",
    "truehd": "TrueHD",
    "dts": "DTS",
    "aac": "AAC",
    "mp3": "MP3",
    "flac": "FLAC",
    "opus": "Opus",
    "vorbis": "Vorbis",
}
_SUBTITLE_CODEC_NAMES = {
    "subrip": "SRT",
    "ass": "ASS",
    "ssa": "SSA",
    "mov_text": "TX3G",
    "webvtt": "WebVTT",
    "hdmv_pgs_subtitle": "PGS",
    "dvd_subtitle": "VobSub",
    "dvb_subtitle": "DVB",
}


def channel_label(channels: int) -> str:
    return {1: "mono", 2: "stereo", 6: "5.1", 7: "6.1", 8: "7.1"}.get(channels, f"{channels}ch")


def describe_audio(track: AudioTrack) -> str:
    """E.g. 'eng  DTS-HD MA 5.1  "Surround"  (default)'."""
    codec = _AUDIO_CODEC_NAMES.get(track.codec, track.codec)
    if track.codec == "dts" and track.profile:
        codec = track.profile  # "DTS-HD MA", "DTS-ES", ...
    parts = [track.language, f"{codec} {channel_label(track.channels)}"]
    if track.title:
        parts.append(f'"{track.title}"')
    if track.default:
        parts.append("(default)")
    if track.commentary:
        parts.append("(commentary)")
    return "  ".join(parts)


def describe_subtitle(track: SubtitleTrack) -> str:
    """E.g. 'eng  SRT  SDH  "English SDH"' or 'eng  SRT  file Movie.en.srt'."""
    parts = [track.language, _SUBTITLE_CODEC_NAMES.get(track.codec, track.codec)]
    if track.sdh:
        parts.append("SDH")
    if track.forced:
        parts.append("forced")
    if track.external:
        assert track.path is not None
        parts.append(f"file {track.path.name}")
    elif track.title:
        parts.append(f'"{track.title}"')
    if track.image:
        parts.append("(image: burn-in only)")
    return "  ".join(parts)
