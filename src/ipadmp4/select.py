"""Pick the best audio and subtitle track for a language (pure, no I/O)."""

from __future__ import annotations

from collections.abc import Sequence

from .tracks import UNKNOWN_LANGUAGE, AudioTrack, SubtitleTrack

# Surround codecs the TV app plays with Spatial Audio, copied untouched.
# (E-AC-3 includes Dolby Atmos, which therefore survives as well.)
SPATIAL_AUDIO_CODECS = frozenset({"ac3", "eac3"})


def pick_audio(tracks: Sequence[AudioTrack], language: str) -> AudioTrack | None:
    """The best track in `language`: most channels (7.1 counts like 5.1, as it
    ends up as 5.1 anyway), then one that can be copied, then the file's
    default track. Commentary and audio description are never picked.

    A file whose only audio track has no language tag gets that track.
    """
    candidates = [t for t in tracks if t.language == language and not t.commentary]
    if not candidates:
        regular = [t for t in tracks if not t.commentary]
        if len(regular) == 1 and regular[0].language == UNKNOWN_LANGUAGE:
            return regular[0]
        return None
    return min(
        candidates,
        key=lambda t: (-min(t.channels, 6), t.codec not in SPATIAL_AUDIO_CODECS, not t.default, t.index),
    )


def pick_subtitle(tracks: Sequence[SubtitleTrack], language: str) -> SubtitleTrack | None:
    """The best full (not forced-only) subtitle track in `language`: text
    before image, regular before SDH, inside the movie before a separate file.

    The result may be an image track; the caller decides what to do with it.
    """
    candidates = [(n, t) for n, t in enumerate(tracks) if t.language == language and not t.forced]
    if not candidates:
        return None
    return min(candidates, key=lambda c: (c[1].image, c[1].sdh, c[1].external, c[0]))[1]
