"""Build the ffmpeg command line for one movie (pure, no subprocesses).

Every decision -- copy or re-encode, which codecs, which filters -- is
unit-testable and shown verbatim with --dry-run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .plan import Plan
from .select import SPATIAL_AUDIO_CODECS
from .tracks import UNKNOWN_LANGUAGE, MediaInfo, VideoStream

# Stereo codecs that go into MP4 as they are.
STEREO_COPY_CODECS = frozenset({"aac", "ac3", "eac3", "mp3"})
# AC-3's maximum; plenty for 5.1. AC-3 is the format with the most reliable
# Spatial Audio support in Apple's player.
SURROUND_BITRATE = "640k"
STEREO_BITRATE = "192k"

# Hardware HEVC encoder quality (1-100). File size hardly matters here, so
# this is on the generous side.
VIDEOTOOLBOX_QUALITY = 70

COPY_PIX_FMTS = {
    "h264": ("yuv420p", "yuvj420p"),
    "hevc": ("yuv420p", "yuvj420p", "yuv420p10le"),
}

TEXT_SUBTITLE_CODECS = frozenset({"subrip", "ass", "ssa", "mov_text", "webvtt", "text"})


@dataclass(frozen=True)
class Options:
    reencode: bool = False
    verbose: bool = False
    # Embed a title card (the file name, white on black) as cover art.
    cover_art: bool = True


def copies_video(video: VideoStream, plan: Plan, opts: Options) -> bool:
    """4:2:0 H.264 (8-bit) and HEVC (8/10-bit) play on the iPad as they are.

    Not 10-bit H.264 ("Hi10P", common in anime) and not 4:2:2/4:4:4.
    """
    if opts.reencode or plan.burn_in:
        return False
    return video.pix_fmt in COPY_PIX_FMTS.get(video.codec, ())


def copies_audio(plan: Plan) -> bool:
    a = plan.audio
    return a.codec in (SPATIAL_AUDIO_CODECS if a.channels > 2 else STEREO_COPY_CODECS)


def describe(info: MediaInfo, plan: Plan, opts: Options) -> str:
    """Short human summary, e.g. 'copy video h264, encode audio dts -> ac3 5.1, subtitles subrip -> text'."""
    video = info.video
    assert video is not None
    a = plan.audio
    parts = [f"copy video {video.codec}" if copies_video(video, plan, opts) else f"encode video {video.codec} -> hevc"]
    if copies_audio(plan):
        parts.append(f"copy audio {a.codec}")
    elif a.channels > 2:
        parts.append(f"encode audio {a.codec} -> ac3 5.1")
    else:
        parts.append(f"encode audio {a.codec} -> aac")
    if plan.subtitle is None:
        parts.append("no subtitles")
    elif plan.burn_in:
        parts.append(f"burn in {plan.subtitle.codec} subtitles")
    else:
        parts.append(f"subtitles {plan.subtitle.codec} -> text")
    if opts.cover_art:
        parts.append("cover art")
    return ", ".join(parts)


def build_command(
    src: Path,
    dst: Path,
    info: MediaInfo,
    plan: Plan,
    opts: Options,
    *,
    cover: Path | None = None,
    overwrite: bool = False,
) -> list[str]:
    """`cover` is an image to embed as cover art (see artwork.py)."""
    video = info.video
    if video is None:
        raise ValueError("build_command needs a file with a video stream")
    sub = plan.subtitle
    if sub is not None and not plan.burn_in and sub.codec not in TEXT_SUBTITLE_CODECS:
        raise ValueError(f"{sub.codec} subtitles can only be burned in")

    cmd = ["ffmpeg", "-nostdin"]
    if not opts.verbose:
        cmd += ["-hide_banner", "-loglevel", "warning", "-stats"]
    if overwrite:
        cmd.append("-y")
    cmd += ["-i", str(src)]
    external = sub is not None and sub.path is not None and not plan.burn_in
    if external:
        assert sub is not None and sub.path is not None
        if sub.charset:
            cmd += ["-sub_charenc", sub.charset]
        cmd += ["-i", str(sub.path)]
    if cover is not None:
        cover_input = 2 if external else 1
        cmd += ["-i", str(cover)]

    # Video (possibly with the subtitle drawn into it).
    if plan.burn_in:
        assert sub is not None and sub.index is not None
        chain = f"[0:{video.index}][0:{sub.index}]overlay=eof_action=pass"
        if video.width % 2 or video.height % 2:
            chain += ",scale=trunc(iw/2)*2:trunc(ih/2)*2"
        cmd += ["-filter_complex", f"{chain}[v]", "-map", "[v]"]
    else:
        cmd += ["-map", f"0:{video.index}"]
    cmd += ["-map", f"0:{plan.audio.index}"]
    if sub is not None and not plan.burn_in:
        cmd += ["-map", "1:0" if external else f"0:{sub.index}"]
    if cover is not None:
        cmd += ["-map", f"{cover_input}:0"]
    cmd += ["-map_metadata", "0", "-map_chapters", "0"]
    # The TV app shows this title (the MP4's "©nam" tag). The movie's own
    # title tag is often missing or messy, so use the file name instead.
    cmd += ["-metadata", f"title={src.stem}"]

    cmd += _video_args(video, plan, opts)
    if cover is not None:
        # A second "video" stream flagged as attached picture becomes the
        # MP4's cover art ("covr" tag), which the TV app can use as thumbnail.
        cmd += ["-c:v:1", "copy", "-disposition:v:1", "attached_pic"]
    cmd += _audio_args(plan)
    if sub is not None and not plan.burn_in:
        # mov_text is the toggleable subtitle format of MP4. The language tag
        # is what the TV app shows in its subtitle menu.
        language = sub.language if sub.language != UNKNOWN_LANGUAGE else "eng"
        cmd += ["-c:s", "mov_text", "-metadata:s:s:0", f"language={language}", "-disposition:s:0", "default"]

    # faststart moves the index to the front so playback can start early.
    # -f mp4 is needed because the real output name ends in .part.
    cmd += ["-movflags", "+faststart", "-f", "mp4", str(dst)]
    return cmd


def _video_args(video: VideoStream, plan: Plan, opts: Options) -> list[str]:
    """Options for the movie's video, the first output video stream (:v:0),
    so they never apply to the cover art."""
    if copies_video(video, plan, opts):
        args = ["-c:v:0", "copy"]
        if video.codec == "hevc":
            # Apple players only play HEVC tagged as hvc1 (ffmpeg defaults to hev1).
            args += ["-tag:v:0", "hvc1"]
        return args

    args = []
    if not plan.burn_in and (video.width % 2 or video.height % 2):
        # 4:2:0 video needs even dimensions; drop the odd row/column.
        args += ["-filter:v:0", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    args += ["-c:v:0", "hevc_videotoolbox", "-q:v:0", str(VIDEOTOOLBOX_QUALITY), "-tag:v:0", "hvc1"]
    if video.bit_depth > 8:
        args += ["-profile:v:0", "main10", "-pix_fmt:v:0", "p010le"]
    else:
        args += ["-profile:v:0", "main", "-pix_fmt:v:0", "yuv420p"]
    return args


def _audio_args(plan: Plan) -> list[str]:
    a = plan.audio
    if copies_audio(plan):
        args = ["-c:a", "copy"]
    elif a.channels > 2:
        # AC-3 holds at most 5.1, so 7.1 is downmixed.
        args = ["-c:a", "ac3", "-b:a", SURROUND_BITRATE, "-ac", str(min(a.channels, 6))]
    else:
        args = ["-c:a", "aac", "-b:a", STEREO_BITRATE]
    return [*args, "-disposition:a:0", "default"]
