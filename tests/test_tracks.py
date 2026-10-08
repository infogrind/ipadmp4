import pytest

from ipadmp4.tracks import describe_audio, describe_subtitle, language_code, normalize_language

from .conftest import aud, ext, sub


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("eng", "eng"),
        ("en", "eng"),
        ("en-US", "eng"),
        ("English", "eng"),
        ("deu", "ger"),
        ("ger", "ger"),
        ("fra", "fre"),
        ("cze", "cze"),
        ("", "und"),
        (None, "und"),
        ("und", "und"),
        ("xx", "und"),
    ],
)
def test_normalize_language(value, expected):
    assert normalize_language(value) == expected


def test_language_code_only_knows_real_spellings():
    assert language_code("EN") == "eng"
    assert language_code("german") == "ger"
    assert language_code("sdh") is None
    assert language_code("x264") is None


def test_describe_audio():
    assert describe_audio(aud("eng", "ac3", 6, default=True)) == "eng  AC-3 5.1  (default)"
    track = aud("eng", "dts", 8, title="Surround", profile="DTS-HD MA")
    assert describe_audio(track) == 'eng  DTS-HD MA 7.1  "Surround"'
    assert describe_audio(aud("eng", "aac", 2, commentary=True)) == "eng  AAC stereo  (commentary)"


def test_describe_subtitle():
    assert describe_subtitle(sub("eng", sdh=True, title="English SDH")) == 'eng  SRT  SDH  "English SDH"'
    assert describe_subtitle(sub("eng", "hdmv_pgs_subtitle")) == "eng  PGS  (image: burn-in only)"
    assert describe_subtitle(ext("/x/Movie.en.srt")) == "eng  SRT  file Movie.en.srt"
