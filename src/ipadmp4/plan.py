"""Decide the tracks for each movie, asking the user where needed.

All questions happen here, for every file, before the first encode starts --
so a long batch never stops halfway to wait for an answer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .errors import Ipadmp4Error
from .select import pick_audio, pick_subtitle
from .tracks import AudioTrack, MediaInfo, SubtitleTrack, describe_audio, describe_subtitle

# Answers to "the subtitles are images, what now?"
BURN_IN = "b"
NO_SUBTITLES = "n"
PICK_OTHER = "p"
SKIP = "s"


@dataclass(frozen=True)
class Plan:
    audio: AudioTrack
    subtitle: SubtitleTrack | None
    # Draw an image subtitle into the picture (always visible).
    burn_in: bool = False

    def summary(self) -> str:
        parts = [f"audio {describe_audio(self.audio)}"]
        if self.subtitle is None:
            parts.append("no subtitles")
        else:
            how = "burned in" if self.burn_in else "toggleable"
            parts.append(f"subtitles {describe_subtitle(self.subtitle)} ({how})")
        return "; ".join(parts)


@dataclass
class Session:
    """Choices that carry over from one file to the next."""

    interactive: bool = False
    audio_language: str = "eng"
    # None: no subtitles at all.
    subtitle_language: str | None = "eng"
    # Remembered answer for files whose subtitles are only images.
    image_action: str | None = None


class Asker:
    """Terminal questions; `ask` and `say` are swappable for tests."""

    def __init__(self, ask: Callable[[str], str] = input, say: Callable[[str], None] = print):
        self._ask = ask
        self.say = say

    def ask(self, prompt: str) -> str:
        try:
            return self._ask(prompt).strip()
        except EOFError:
            raise Ipadmp4Error("input ended while a question was open") from None

    def yes(self, prompt: str) -> bool:
        while True:
            answer = self.ask(f"{prompt} [y/N] ").lower()
            if answer in ("", "n", "no"):
                return False
            if answer in ("y", "yes"):
                return True

    def letter(self, prompt: str, choices: str) -> str:
        while True:
            answer = self.ask(prompt).lower()
            if len(answer) == 1 and answer in choices:
                return answer

    def number(self, prompt: str, count: int, *, default: int | None, allow_zero: bool) -> int | None:
        """A number from 1..count (0 too if `allow_zero`), or None for "s" (skip file)."""
        lowest = 0 if allow_zero else 1
        while True:
            answer = self.ask(prompt).lower()
            if answer == "" and default is not None:
                return default
            if answer == "s":
                return None
            if answer.isdigit() and lowest <= int(answer) <= count:
                return int(answer)


def plan_file(name: str, info: MediaInfo, session: Session, asker: Asker, *, remaining: int) -> Plan | None:
    """Choose audio and subtitles for one movie; None means skip it.

    `remaining` is the number of files after this one, for the "same for
    all remaining files?" question.
    """
    asked = False

    audio = None if session.interactive else pick_audio(info.audio, session.audio_language)
    if audio is None:
        if not info.audio:
            asker.say(f"  {name} has no audio track.")
            return None
        if not session.interactive:
            asker.say(f"  {name}: no audio track in language '{session.audio_language}'.")
        audio = _choose_audio(info.audio, pick_audio(info.audio, session.audio_language), asker)
        if audio is None:
            return None
        asked = True

    want = session.subtitle_language
    if session.interactive:
        default = pick_subtitle(info.subtitles, want) if want else None
        choice = _choose_subtitle(info.subtitles, default, asker)
        asked = True
    elif want is None:
        choice = None
    else:
        choice = pick_subtitle(info.subtitles, want)
        if choice is None:
            asker.say(f"  {name}: no subtitles in language '{want}'.")
            choice = _choose_subtitle(info.subtitles, None, asker)
            asked = True

    if choice is SKIP:
        return None
    assert not isinstance(choice, str)

    plan = Plan(audio=audio, subtitle=choice)
    if choice is not None and choice.image:
        plan = _image_subtitle(plan, info, session, asker, remaining=remaining, picked=asked)
        if plan is None:
            return None

    if asked and remaining:
        subs = plan.subtitle.language if plan.subtitle else "no"
        if asker.yes(f"  Use {plan.audio.language} audio and {subs} subtitles for the {remaining} remaining file(s)?"):
            session.interactive = False
            session.audio_language = plan.audio.language
            session.subtitle_language = plan.subtitle.language if plan.subtitle else None
    return plan


def _choose_audio(tracks: Sequence[AudioTrack], default: AudioTrack | None, asker: Asker) -> AudioTrack | None:
    asker.say("  Audio tracks:")
    for n, t in enumerate(tracks, 1):
        asker.say(f"    {n}  {describe_audio(t)}")
    default_n = tracks.index(default) + 1 if default else None
    hint = f" [{default_n}]" if default_n else ""
    n = asker.number(f"  Audio track (number, s = skip file){hint}: ", len(tracks), default=default_n, allow_zero=False)
    return None if n is None else tracks[n - 1]


def _choose_subtitle(
    tracks: Sequence[SubtitleTrack], default: SubtitleTrack | None, asker: Asker
) -> SubtitleTrack | str | None:
    """A track, None for no subtitles, or SKIP."""
    asker.say("  Subtitle tracks:")
    asker.say("    0  none")
    for n, t in enumerate(tracks, 1):
        asker.say(f"    {n}  {describe_subtitle(t)}")
    default_n = tracks.index(default) + 1 if default else 0
    n = asker.number(
        f"  Subtitle track (number, s = skip file) [{default_n}]: ", len(tracks), default=default_n, allow_zero=True
    )
    if n is None:
        return SKIP
    return tracks[n - 1] if n else None


def _image_subtitle(
    plan: Plan, info: MediaInfo, session: Session, asker: Asker, *, remaining: int, picked: bool
) -> Plan | None:
    """The chosen subtitles are pictures, which an MP4 can't hold as a
    toggleable track: burn them in, drop them, or pick something else."""
    sub = plan.subtitle
    assert sub is not None
    if picked:
        # The user chose this very track: just confirm the consequence.
        if asker.yes(
            "  That track is an image subtitle; it can only be burned in (always visible, video re-encoded). OK?"
        ):
            return Plan(audio=plan.audio, subtitle=sub, burn_in=True)
        action = None
    else:
        action = session.image_action

    if action is None:
        asker.say(
            f"  The best '{sub.language}' subtitles are images ({describe_subtitle(sub)}).\n"
            "  The TV app can only switch text subtitles on and off.\n"
            "    b  burn them in (always visible; re-encodes the video)\n"
            "    n  no subtitles\n"
            "    p  pick another subtitle track\n"
            "    s  skip this file"
        )
        action = asker.letter("  Choice [b/n/p/s]: ", "bnps")
        if (
            action in (BURN_IN, NO_SUBTITLES)
            and remaining
            and not picked
            and asker.yes("  Do the same for other files that only have image subtitles?")
        ):
            session.image_action = action

    if action == BURN_IN:
        return Plan(audio=plan.audio, subtitle=sub, burn_in=True)
    if action == NO_SUBTITLES:
        return Plan(audio=plan.audio, subtitle=None)
    if action == SKIP:
        return None
    # PICK_OTHER
    choice = _choose_subtitle(info.subtitles, None, asker)
    if choice is SKIP:
        return None
    assert not isinstance(choice, str)
    if choice is None or not choice.image:
        return Plan(audio=plan.audio, subtitle=choice)
    return _image_subtitle(Plan(audio=plan.audio, subtitle=choice), info, session, asker, remaining=0, picked=True)
