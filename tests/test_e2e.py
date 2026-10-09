"""End-to-end: real ffmpeg on tiny generated movies, checked with ffprobe."""

import json
import shutil
import subprocess

import pytest

from ipadmp4 import cli

from .conftest import ScriptedAsker

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg"
)

SRT = "1\n00:00:00,000 --> 00:00:00,900\nHello\n"
SURROUND = "pan=5.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0"


def _make_movie(path, srt, *, audio_languages):
    """A 1-second H.264 MKV: one 5.1 audio track per language (AC-3 for the
    first, DTS for the rest) and one English SRT subtitle track."""
    n = len(audio_languages)
    split = f"[1:a]asplit={n}" + "".join(f"[s{i}]" for i in range(n)) + ";"
    graph = split + ";".join(f"[s{i}]{SURROUND}[a{i}]" for i in range(n))
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1",
           "-f", "lavfi", "-i", "sine=duration=1", "-i", str(srt),
           "-filter_complex", graph, "-map", "0:v"]  # fmt: skip
    for i in range(n):
        cmd += ["-map", f"[a{i}]"]
    cmd += ["-map", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "dca", "-c:a:0", "ac3", "-strict", "-2"]
    cmd += ["-c:s", "srt", "-metadata:s:s:0", "language=eng"]
    for i, lang in enumerate(audio_languages):
        cmd += [f"-metadata:s:a:{i}", f"language={lang}"]
    subprocess.run([*cmd, str(path)], check=True)


def _title(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags=title", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.strip()


def _streams(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)["streams"]


def test_batch_asks_first_then_converts(tmp_path, monkeypatch):
    srt = tmp_path / "sub.srt"
    srt.write_text(SRT)
    english = tmp_path / "a.mkv"
    foreign = tmp_path / "b.mkv"
    _make_movie(english, srt, audio_languages=["eng", "jpn"])
    _make_movie(foreign, srt, audio_languages=["fre", "jpn"])
    srt.unlink()

    # Record when encoding starts relative to the questions.
    events = []
    real_convert = cli._convert
    monkeypatch.setattr(cli, "_convert", lambda task, opts: events.append("convert") or real_convert(task, opts))
    asker = ScriptedAsker("2")  # b.mkv has no English audio: pick the Japanese DTS track
    asker._ask = lambda prompt, ask=asker._ask: events.append("ask") or ask(prompt)

    assert cli.main([str(english), str(foreign)], asker=asker) == 0
    assert events == ["ask", "convert", "convert"]

    a = _streams(tmp_path / "a.mp4")
    assert [s["codec_name"] for s in a] == ["h264", "ac3", "mov_text", "png"]
    assert a[3]["disposition"]["attached_pic"] == 1  # cover art
    assert _title(tmp_path / "a.mp4") == "a"
    assert (a[1]["channels"], a[1]["tags"]["language"]) == (6, "eng")
    assert a[2]["tags"]["language"] == "eng"
    assert a[2]["disposition"]["default"] == 1

    b = _streams(tmp_path / "b.mp4")
    assert [s["codec_name"] for s in b] == ["h264", "ac3", "mov_text", "png"]  # DTS became AC-3
    assert (b[1]["channels"], b[1]["tags"]["language"]) == (6, "jpn")
    assert list(tmp_path.glob("*.part")) == []
    assert list(tmp_path.glob("*.cover.png")) == []


def test_external_srt_and_hevc_reencode(tmp_path):
    srt = tmp_path / "sub.srt"
    srt.write_text(SRT)
    movie = tmp_path / "Movie.mkv"
    _make_movie(movie, srt, audio_languages=["eng"])
    srt.unlink()
    (tmp_path / "Movie.de.srt").write_bytes("1\n00:00:00,000 --> 00:00:00,900\nCafé\n".encode("cp1252"))

    asker = ScriptedAsker("", "2")  # keep the audio, take the German file
    assert cli.main(["-i", "--reencode", "--no-cover-art", str(movie)], asker=asker) == 0

    out = tmp_path / "Movie.mp4"
    video, _, subtitle = _streams(out)
    assert (video["codec_name"], video["codec_tag_string"]) == ("hevc", "hvc1")
    assert subtitle["tags"]["language"] == "ger"
    text = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(out), "-map", "0:s", "-f", "srt", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Café" in text


def test_corrupt_file_fails_cleanly(tmp_path, capsys):
    bad = tmp_path / "bad.mkv"
    bad.write_bytes(b"not a video at all" * 100)

    assert cli.main([str(bad)], asker=ScriptedAsker()) == 1

    assert sorted(p.name for p in tmp_path.iterdir()) == ["bad.mkv"]
    assert "ffprobe could not read" in capsys.readouterr().err
