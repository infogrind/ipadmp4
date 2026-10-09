"""Shared builders for test fixtures.

Tests describe a movie as e.g.
`media(audio=[aud("eng", "dts", 6)], subs=[sub("eng", "subrip")])`
instead of hand-writing ffprobe JSON or full dataclasses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipadmp4.plan import Asker
from ipadmp4.tracks import AudioTrack, MediaInfo, SubtitleTrack, VideoStream


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path_factory, monkeypatch):
    """Never read the real ~/.config/ipadmp4 during tests."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))


def aud(language: str = "eng", codec: str = "ac3", channels: int = 6, index: int = 1, **kw) -> AudioTrack:
    return AudioTrack(index=index, codec=codec, channels=channels, language=language, **kw)


def sub(language: str = "eng", codec: str = "subrip", index: int | None = 10, **kw) -> SubtitleTrack:
    if "path" in kw:
        index = None
    return SubtitleTrack(codec=codec, language=language, index=index, **kw)


def media(
    audio: list[AudioTrack] | None = None,
    subs: list[SubtitleTrack] | None = None,
    *,
    codec: str = "h264",
    width: int = 1920,
    height: int = 1080,
    pix_fmt: str = "yuv420p",
) -> MediaInfo:
    """Audio indexes are renumbered 1, 2, ... and subtitle indexes follow them."""
    audio = [aud()] if audio is None else audio
    subs = [] if subs is None else subs
    audio = [AudioTrack(**{**a.__dict__, "index": i}) for i, a in enumerate(audio, 1)]
    subs = [s if s.path else SubtitleTrack(**{**s.__dict__, "index": len(audio) + i}) for i, s in enumerate(subs, 1)]
    return MediaInfo(
        video=VideoStream(index=0, codec=codec, width=width, height=height, pix_fmt=pix_fmt),
        audio=tuple(audio),
        subtitles=tuple(subs),
    )


class ScriptedAsker(Asker):
    """Answers questions from a list and records everything shown."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.output: list[str] = []
        super().__init__(ask=self._next, say=self.output.append)

    def _next(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    @property
    def text(self) -> str:
        return "\n".join(self.output + self.prompts)


def ext(name: str, language: str = "eng", **kw) -> SubtitleTrack:
    return SubtitleTrack(codec="subrip", language=language, path=Path(name), **kw)
