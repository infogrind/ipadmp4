from ipadmp4.select import pick_audio, pick_subtitle

from .conftest import aud, ext, sub


def _audio(*tracks):
    return [t.__class__(**{**t.__dict__, "index": i}) for i, t in enumerate(tracks, 1)]


def test_prefers_surround_over_stereo():
    tracks = _audio(aud("eng", "aac", 2, default=True), aud("eng", "dts", 6))
    assert pick_audio(tracks, "eng") == tracks[1]


def test_71_counts_like_51_and_copyable_codec_wins():
    tracks = _audio(aud("eng", "truehd", 8), aud("eng", "eac3", 6))
    assert pick_audio(tracks, "eng") == tracks[1]


def test_default_track_breaks_ties():
    tracks = _audio(aud("eng", "ac3", 6), aud("eng", "ac3", 6, default=True))
    assert pick_audio(tracks, "eng") == tracks[1]


def test_commentary_is_never_picked():
    tracks = _audio(aud("eng", "ac3", 2, commentary=True), aud("jpn", "ac3", 6))
    assert pick_audio(tracks, "eng") is None


def test_other_language():
    tracks = _audio(aud("eng", "ac3", 6), aud("jpn", "dts", 6))
    assert pick_audio(tracks, "jpn") == tracks[1]


def test_single_untagged_track_is_used():
    tracks = _audio(aud("und", "ac3", 6), aud("und", "aac", 2, commentary=True))
    assert pick_audio(tracks, "eng") == tracks[0]


def test_several_untagged_tracks_are_ambiguous():
    assert pick_audio(_audio(aud("und"), aud("und")), "eng") is None


def test_regular_subtitles_before_sdh_and_forced_never():
    tracks = [sub("eng", forced=True), sub("eng", sdh=True), sub("eng"), sub("ger")]
    assert pick_subtitle(tracks, "eng") == tracks[2]


def test_sdh_when_nothing_else():
    tracks = [sub("eng", forced=True), sub("eng", sdh=True, title="English SDH")]
    assert pick_subtitle(tracks, "eng") == tracks[1]


def test_text_sdh_beats_image_regular():
    tracks = [sub("eng", "hdmv_pgs_subtitle"), sub("eng", sdh=True)]
    assert pick_subtitle(tracks, "eng") == tracks[1]


def test_internal_before_external():
    tracks = [ext("Movie.srt"), sub("eng")]
    assert pick_subtitle(tracks, "eng") == tracks[1]


def test_external_when_only_option():
    tracks = [sub("eng", "hdmv_pgs_subtitle"), ext("Movie.en.srt")]
    assert pick_subtitle(tracks, "eng") == tracks[1]


def test_image_returned_when_only_option():
    tracks = [sub("eng", "hdmv_pgs_subtitle")]
    assert pick_subtitle(tracks, "eng") == tracks[0]


def test_no_match():
    assert pick_subtitle([sub("ger"), sub("eng", forced=True)], "eng") is None
