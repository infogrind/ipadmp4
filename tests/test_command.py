from pathlib import Path

import pytest

from ipadmp4.command import Options, build_command, describe
from ipadmp4.plan import Plan

from .conftest import aud, ext, media, sub

SRC = Path("in.mkv")
DST = Path("out.mp4")


def _cmd(info, subtitle_n=None, *, audio_n=0, burn_in=False, **opts):
    subtitle = info.subtitles[subtitle_n] if subtitle_n is not None else None
    plan = Plan(audio=info.audio[audio_n], subtitle=subtitle, burn_in=burn_in)
    return build_command(SRC, DST, info, plan, Options(**opts))


def _arg(cmd, flag):
    """The value following `flag` in the command (first occurrence)."""
    return cmd[cmd.index(flag) + 1]


def _all(cmd, flag):
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == flag]


def test_typical_movie_is_copied():
    cmd = _cmd(media([aud("ger"), aud("eng", "ac3", 6)], [sub("ger"), sub("eng")]), 1, audio_n=1)
    assert cmd[:2] == ["ffmpeg", "-nostdin"]
    assert _all(cmd, "-i") == ["in.mkv"]
    assert _all(cmd, "-map") == ["0:0", "0:2", "0:4"]
    assert _arg(cmd, "-c:v:0") == "copy"
    assert _arg(cmd, "-c:a") == "copy"
    assert _arg(cmd, "-c:s") == "mov_text"
    assert _arg(cmd, "-metadata:s:s:0") == "language=eng"
    assert _arg(cmd, "-disposition:s:0") == "default"
    assert _arg(cmd, "-disposition:a:0") == "default"
    assert _arg(cmd, "-map_chapters") == "0"
    assert _arg(cmd, "-movflags") == "+faststart"
    assert cmd[-3:] == ["-f", "mp4", "out.mp4"]
    assert "-y" not in cmd


@pytest.mark.parametrize("codec", ["ac3", "eac3"])
def test_spatial_audio_codecs_are_copied(codec):
    assert _arg(_cmd(media([aud("eng", codec, 6)])), "-c:a") == "copy"


@pytest.mark.parametrize(("codec", "channels", "ac"), [("dts", 6, "6"), ("truehd", 8, "6"), ("aac", 6, "6")])
def test_other_surround_becomes_ac3_51(codec, channels, ac):
    cmd = _cmd(media([aud("eng", codec, channels)]))
    assert (_arg(cmd, "-c:a"), _arg(cmd, "-b:a"), _arg(cmd, "-ac")) == ("ac3", "640k", ac)


def test_stereo_aac_is_copied_and_other_stereo_becomes_aac():
    assert _arg(_cmd(media([aud("eng", "aac", 2)])), "-c:a") == "copy"
    cmd = _cmd(media([aud("eng", "flac", 2)]))
    assert (_arg(cmd, "-c:a"), _arg(cmd, "-b:a")) == ("aac", "192k")


def test_hevc_is_copied_with_apple_tag():
    cmd = _cmd(media(codec="hevc", pix_fmt="yuv420p10le"))
    assert _arg(cmd, "-c:v:0") == "copy"
    assert _arg(cmd, "-tag:v:0") == "hvc1"


@pytest.mark.parametrize(
    ("codec", "pix_fmt", "profile", "out_fmt"),
    [
        ("h264", "yuv420p10le", "main10", "p010le"),  # Hi10P: no hardware decoder on iOS
        ("h264", "yuv444p", "main", "yuv420p"),
        ("mpeg4", "yuv420p", "main", "yuv420p"),
        ("vc1", "yuv420p", "main", "yuv420p"),
    ],
)
def test_unplayable_video_is_encoded_to_hevc(codec, pix_fmt, profile, out_fmt):
    cmd = _cmd(media(codec=codec, pix_fmt=pix_fmt))
    assert _arg(cmd, "-c:v:0") == "hevc_videotoolbox"
    assert _arg(cmd, "-tag:v:0") == "hvc1"
    assert (_arg(cmd, "-profile:v:0"), _arg(cmd, "-pix_fmt:v:0")) == (profile, out_fmt)


def test_reencode_option():
    assert _arg(_cmd(media(), reencode=True), "-c:v:0") == "hevc_videotoolbox"


def test_odd_dimensions_get_scaled_to_even():
    cmd = _cmd(media(codec="mpeg4", width=719, height=405))
    assert _arg(cmd, "-filter:v:0") == "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def test_external_subtitle_is_a_second_input():
    info = media(subs=[ext("/m/Movie.de.srt", "ger", charset="CP1252")])
    cmd = _cmd(info, 0)
    assert _all(cmd, "-i") == ["in.mkv", "/m/Movie.de.srt"]
    assert _arg(cmd, "-sub_charenc") == "CP1252"
    assert cmd.index("-sub_charenc") < cmd.index("/m/Movie.de.srt")
    assert _all(cmd, "-map") == ["0:0", "0:1", "1:0"]
    assert _arg(cmd, "-metadata:s:s:0") == "language=ger"
    assert _arg(cmd, "-map_metadata") == "0"


def test_utf8_external_subtitle_has_no_charset_option():
    assert "-sub_charenc" not in _cmd(media(subs=[ext("/m/Movie.srt")]), 0)


def test_untagged_subtitle_is_labelled_english():
    assert _arg(_cmd(media(subs=[sub("und")]), 0), "-metadata:s:s:0") == "language=eng"


def test_burn_in_overlays_and_reencodes():
    info = media(subs=[sub("eng", "hdmv_pgs_subtitle")])
    cmd = _cmd(info, 0, burn_in=True)
    assert _arg(cmd, "-filter_complex") == "[0:0][0:2]overlay=eof_action=pass[v]"
    assert _all(cmd, "-map") == ["[v]", "0:1"]
    assert _arg(cmd, "-c:v:0") == "hevc_videotoolbox"
    assert "-c:s" not in cmd
    assert "-filter:v:0" not in cmd


def test_burn_in_with_odd_dimensions_scales_in_the_filter_graph():
    info = media(subs=[sub("eng", "dvd_subtitle")], codec="mpeg2video", width=719, height=480)
    cmd = _cmd(info, 0, burn_in=True)
    assert _arg(cmd, "-filter_complex").endswith(",scale=trunc(iw/2)*2:trunc(ih/2)*2[v]")
    assert "-filter:v:0" not in cmd


def test_image_subtitle_without_burn_in_is_refused():
    with pytest.raises(ValueError, match="burned in"):
        _cmd(media(subs=[sub("eng", "hdmv_pgs_subtitle")]), 0)


def test_quiet_unless_verbose():
    assert "-loglevel" in _cmd(media())
    assert "-loglevel" not in _cmd(media(), verbose=True)


def test_describe():
    info = media([aud("eng", "dts", 6)], [sub("eng")])
    plan = Plan(audio=info.audio[0], subtitle=info.subtitles[0])
    assert describe(info, plan, Options(cover_art=False)) == (
        "copy video h264, encode audio dts -> ac3 5.1, subtitles subrip -> text"
    )
    assert describe(info, plan, Options()).endswith(", cover art")


def test_title_is_the_file_name_without_extension():
    info = media()
    plan = Plan(audio=info.audio[0], subtitle=None)
    cmd = build_command(Path("/m/Heat (1995)/Heat.1995.1080p.mkv"), DST, info, plan, Options())
    assert _arg(cmd, "-metadata") == "title=Heat.1995.1080p"
    assert cmd.index("-map_metadata") < cmd.index("-metadata")  # overrides the copied title


def _with_cover(info, subtitle_n=None, **opts):
    plan = Plan(audio=info.audio[0], subtitle=info.subtitles[subtitle_n] if subtitle_n is not None else None)
    return build_command(SRC, DST, info, plan, Options(**opts), cover=Path("/t/cover.png"))


def test_cover_art_is_an_attached_picture():
    cmd = _with_cover(media(subs=[sub("eng")]), 0)
    assert _all(cmd, "-i") == ["in.mkv", "/t/cover.png"]
    assert _all(cmd, "-map") == ["0:0", "0:1", "0:2", "1:0"]
    assert (_arg(cmd, "-c:v:1"), _arg(cmd, "-disposition:v:1")) == ("copy", "attached_pic")
    assert _arg(cmd, "-c:v:0") == "copy"


def test_cover_art_comes_after_an_external_subtitle_file():
    cmd = _with_cover(media(subs=[ext("/m/Movie.srt")]), 0)
    assert _all(cmd, "-i") == ["in.mkv", "/m/Movie.srt", "/t/cover.png"]
    assert _all(cmd, "-map")[-2:] == ["1:0", "2:0"]


def test_reencode_options_do_not_touch_the_cover():
    cmd = _with_cover(media(codec="mpeg4", width=719, height=405))
    for flag in ("-c:v", "-tag:v", "-q:v", "-profile:v", "-pix_fmt", "-vf"):
        assert flag not in cmd  # only stream-specific :v:0 variants
    assert _arg(cmd, "-c:v:0") == "hevc_videotoolbox"
    assert _arg(cmd, "-c:v:1") == "copy"


def test_no_cover_by_default():
    cmd = _cmd(media())
    assert "-c:v:1" not in cmd
    assert _all(cmd, "-i") == ["in.mkv"]
