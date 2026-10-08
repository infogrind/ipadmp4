import pytest

from ipadmp4.errors import Ipadmp4Error
from ipadmp4.plan import Plan, Session, plan_file

from .conftest import ScriptedAsker, aud, ext, media, sub

PGS = "hdmv_pgs_subtitle"


def _plan(info, *answers, session=None, remaining=0):
    asker = ScriptedAsker(*answers)
    session = session if session is not None else Session()
    result = plan_file("Movie.mkv", info, session, asker, remaining=remaining)
    assert asker.answers == [], f"unused answers: {asker.answers}"
    return result, asker, session


def test_automatic_needs_no_questions():
    info = media(audio=[aud("ger"), aud("eng", "dts", 6)], subs=[sub("eng", sdh=True), sub("eng")])
    plan, asker, _ = _plan(info, remaining=3)
    assert plan == Plan(audio=info.audio[1], subtitle=info.subtitles[1])
    assert asker.prompts == []


def test_no_english_audio_asks():
    info = media(audio=[aud("fre"), aud("ita")], subs=[sub("eng")])
    plan, asker, _ = _plan(info, "2")
    assert plan.audio == info.audio[1]
    assert plan.subtitle == info.subtitles[0]
    assert "no audio track in language 'eng'" in asker.text


def test_no_english_audio_can_skip_file():
    plan, _, _ = _plan(media(audio=[aud("fre")]), "s")
    assert plan is None


def test_invalid_answers_are_asked_again():
    info = media(audio=[aud("fre"), aud("ita")], subs=[sub("eng")])
    plan, asker, _ = _plan(info, "", "9", "x", "1")
    assert plan.audio == info.audio[0]
    assert len(asker.prompts) == 4


def test_no_english_subtitles_asks_with_none_as_default():
    info = media(subs=[sub("ger")])
    plan, asker, _ = _plan(info, "")
    assert plan.subtitle is None
    assert "no subtitles in language 'eng'" in asker.text


def test_no_english_subtitles_pick_another():
    info = media(subs=[sub("ger")])
    plan, _, _ = _plan(info, "1")
    assert plan.subtitle == info.subtitles[0]


def test_interactive_defaults_are_the_automatic_choice():
    info = media(audio=[aud("eng"), aud("jpn")], subs=[sub("eng", sdh=True), sub("eng")])
    plan, asker, _ = _plan(info, "", "", session=Session(interactive=True))
    assert plan == Plan(audio=info.audio[0], subtitle=info.subtitles[1])
    assert "[1]" in asker.prompts[0] and "[2]" in asker.prompts[1]


def test_interactive_pick():
    info = media(audio=[aud("eng"), aud("jpn")], subs=[sub("eng"), sub("jpn")])
    plan, _, _ = _plan(info, "2", "0", session=Session(interactive=True))
    assert plan == Plan(audio=info.audio[1], subtitle=None)


def test_interactive_lists_commentary_and_forced():
    info = media(audio=[aud("eng"), aud("eng", commentary=True)], subs=[sub("eng", forced=True)])
    _, asker, _ = _plan(info, "", "", session=Session(interactive=True))
    assert "(commentary)" in asker.text
    assert "forced" in asker.text


def test_same_choice_for_all_remaining_files():
    info = media(audio=[aud("eng"), aud("jpn")], subs=[sub("eng"), sub("ger")])
    session = Session(interactive=True)
    _, asker, _ = _plan(info, "2", "2", "y", session=session, remaining=2)
    assert session == Session(interactive=False, audio_language="jpn", subtitle_language="ger")
    assert "2 remaining file(s)" in asker.prompts[-1]

    # The next file is then planned without questions.
    nxt = media(audio=[aud("eng"), aud("jpn")], subs=[sub("ger"), sub("eng")])
    plan, asker, _ = _plan(nxt, session=session, remaining=1)
    assert plan == Plan(audio=nxt.audio[1], subtitle=nxt.subtitles[0])


def test_same_choice_can_be_no_subtitles():
    session = Session(interactive=True)
    _plan(media(subs=[sub("eng")]), "", "0", "y", session=session, remaining=1)
    assert session.subtitle_language is None
    plan, _, _ = _plan(media(subs=[sub("eng")]), session=session)
    assert plan.subtitle is None


def test_declining_same_choice_keeps_asking():
    session = Session(interactive=True)
    _plan(media(), "", "", "n", session=session, remaining=1)
    assert session.interactive


def test_no_same_choice_question_for_last_file():
    _, asker, _ = _plan(media(), "", "", session=Session(interactive=True), remaining=0)
    assert not any("remaining" in p for p in asker.prompts)


def test_image_only_subtitles_burn_in():
    info = media(subs=[sub("eng", PGS)])
    plan, asker, _ = _plan(info, "b")
    assert plan == Plan(audio=info.audio[0], subtitle=info.subtitles[0], burn_in=True)
    assert "only switch text subtitles" in asker.text


@pytest.mark.parametrize(("answer", "expected_sub"), [("n", None), ("s", "skip")])
def test_image_only_subtitles_none_or_skip(answer, expected_sub):
    plan, _, _ = _plan(media(subs=[sub("eng", PGS)]), answer)
    if expected_sub == "skip":
        assert plan is None
    else:
        assert plan.subtitle is None and not plan.burn_in


def test_image_only_subtitles_pick_other_text_track():
    info = media(subs=[sub("eng", PGS), sub("ger")])
    plan, _, _ = _plan(info, "p", "2")
    assert plan == Plan(audio=info.audio[0], subtitle=info.subtitles[1])


def test_image_answer_remembered_for_other_files():
    session = Session()
    _plan(media(subs=[sub("eng", PGS)]), "b", "y", session=session, remaining=1)
    assert session.image_action == "b"
    plan, asker, _ = _plan(media(subs=[sub("eng", PGS)]), session=session)
    assert plan.burn_in
    assert asker.prompts == []


def test_picking_image_track_interactively_needs_confirmation():
    info = media(subs=[sub("eng", PGS), sub("eng")])
    plan, _, _ = _plan(info, "", "1", "y", session=Session(interactive=True))
    assert plan.burn_in and plan.subtitle == info.subtitles[0]


def test_declining_burn_in_offers_alternatives():
    info = media(subs=[sub("eng", PGS), sub("eng")])
    plan, _, _ = _plan(info, "", "1", "n", "p", "2", session=Session(interactive=True))
    assert plan == Plan(audio=info.audio[0], subtitle=info.subtitles[1])


def test_external_subtitle_is_offered():
    info = media(subs=[ext("Movie.de.srt", "ger")])
    plan, asker, _ = _plan(info, "1")
    assert plan.subtitle == info.subtitles[0]
    assert "file Movie.de.srt" in asker.text


def test_no_audio_at_all_skips():
    plan, asker, _ = _plan(media(audio=[]))
    assert plan is None
    assert "no audio track" in asker.text


def test_closed_input_is_an_error():
    with pytest.raises(Ipadmp4Error, match="input ended"):
        plan_file("Movie.mkv", media(audio=[aud("fre")]), Session(), ScriptedAsker(), remaining=0)
