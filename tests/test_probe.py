import json
import shutil

import pytest

from ipadmp4.errors import Ipadmp4Error
from ipadmp4.probe import external_subtitles, parse_ffprobe_json, probe


def _json(*streams):
    return json.dumps({"streams": [{"index": i, **s} for i, s in enumerate(streams)]})


def test_parses_movie_streams():
    info = parse_ffprobe_json(
        _json(
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p"},
            {
                "codec_type": "audio",
                "codec_name": "dts",
                "profile": "DTS-HD MA",
                "channels": 6,
                "tags": {"language": "eng", "title": "Surround"},
                "disposition": {"default": 1},
            },
            {
                "codec_type": "audio",
                "codec_name": "ac3",
                "channels": 2,
                "tags": {"language": "eng", "title": "Commentary"},
            },
            {"codec_type": "audio", "codec_name": "aac", "channels": 2, "disposition": {"visual_impaired": 1}},
            {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"LANGUAGE": "eng", "title": "English"}},
            {"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "eng", "title": "English SDH"}},
            {
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "tags": {"language": "eng"},
                "disposition": {"forced": 1},
            },
            {
                "codec_type": "subtitle",
                "codec_name": "hdmv_pgs_subtitle",
                "tags": {"language": "eng", "title": "Forced"},
            },
        )
    )
    assert info.video is not None and info.video.codec == "h264"
    surround, commentary, description = info.audio
    assert (surround.index, surround.language, surround.channels, surround.default) == (1, "eng", 6, True)
    assert not surround.commentary
    assert commentary.commentary and description.commentary
    assert description.language == "und"

    plain, sdh, forced, forced_by_title = info.subtitles
    assert (plain.index, plain.sdh, plain.forced, plain.image) == (4, False, False, False)
    assert sdh.sdh and not sdh.forced
    assert forced.forced and forced_by_title.forced and forced_by_title.image


def test_cover_art_is_not_the_video():
    info = parse_ffprobe_json(
        _json(
            {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
            {"codec_type": "video", "codec_name": "hevc", "width": 1280, "height": 720, "pix_fmt": "yuv420p10le"},
        )
    )
    assert info.video is not None
    assert (info.video.index, info.video.codec, info.video.bit_depth) == (1, "hevc", 10)


@pytest.mark.parametrize(
    ("name", "language", "sdh", "forced"),
    [
        ("Movie.srt", "eng", False, False),
        ("Movie.en.srt", "eng", False, False),
        ("Movie.English.SDH.srt", "eng", True, False),
        ("Movie.sdh.srt", "eng", True, False),
        ("Movie.en.forced.srt", "eng", False, True),
        ("Movie.de.srt", "ger", False, False),
        ("Movie.cze.srt", "cze", False, False),
        ("Movie.12.srt", "und", False, False),
    ],
)
def test_external_subtitle_names(tmp_path, name, language, sdh, forced):
    movie = tmp_path / "Movie.mkv"
    movie.touch()
    (tmp_path / name).write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    (found,) = external_subtitles(movie)
    assert (found.path, found.language, found.sdh, found.forced) == (tmp_path / name, language, sdh, forced)
    assert found.charset is None


def test_external_subtitles_ignore_other_movies(tmp_path):
    movie = tmp_path / "Movie.mkv"
    movie.touch()
    for name in ("Movie 2.srt", "Movie2.en.srt", "Other.srt", "Movie.en.sub", "Movie.mkv.txt"):
        (tmp_path / name).touch()
    assert external_subtitles(movie) == []


def test_non_utf8_subtitles_are_read_as_cp1252(tmp_path):
    movie = tmp_path / "Movie.mkv"
    movie.touch()
    (tmp_path / "Movie.srt").write_bytes("café".encode("cp1252"))
    (found,) = external_subtitles(movie)
    assert found.charset == "CP1252"


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="needs ffprobe")
def test_probe_error_is_one_short_line(tmp_path):
    bad = tmp_path / "bad.mkv"
    bad.write_bytes(b"not a video at all" * 100)
    with pytest.raises(Ipadmp4Error) as e:
        probe(bad)
    assert str(e.value) == "ffprobe could not read the file: Invalid data found when processing input"
