"""The CLI flow without ffmpeg: probing and converting are faked."""

import os
import subprocess
from pathlib import Path

import pytest

from ipadmp4 import cli
from ipadmp4.command import Options
from ipadmp4.errors import Ipadmp4Error
from ipadmp4.plan import Plan

from .conftest import ScriptedAsker, aud, media, sub


@pytest.fixture
def fake_tools(monkeypatch):
    """Every file probes as an English movie; converting writes a 2 MB file."""
    monkeypatch.setattr(cli.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    def probe(path):
        if path.name.startswith("bad"):
            raise Ipadmp4Error(f"ffprobe could not read {path}: Invalid data")
        return media([aud("eng")], [sub("eng")])

    def convert(task, opts):
        task.dst.parent.mkdir(parents=True, exist_ok=True)
        task.dst.write_bytes(b"x" * 2_000_000)
        return not task.src.name.startswith("broken")

    monkeypatch.setattr(cli, "probe", probe)
    monkeypatch.setattr(cli, "_convert", convert)


def _config(text):
    path = cli.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(text)


def _movies(tmp_path, *names):
    for name in names:
        (tmp_path / name).touch()
    return [str(tmp_path / n) for n in names]


def test_output_next_to_originals_without_config(tmp_path, fake_tools):
    assert cli.main(_movies(tmp_path, "a.mkv"), asker=ScriptedAsker()) == 0
    assert (tmp_path / "a.mp4").exists()


def test_config_output_dir(tmp_path, fake_tools, capsys):
    out = tmp_path / "ipad"
    _config(f'output_dir = "{out}"\n')
    assert cli.main(_movies(tmp_path, "a.mkv"), asker=ScriptedAsker()) == 0
    assert (out / "a.mp4").exists()
    assert not (tmp_path / "a.mp4").exists()
    assert f"Output folder: {out}" in capsys.readouterr().out


def test_option_overrides_config(tmp_path, fake_tools):
    _config(f'output_dir = "{tmp_path / "ipad"}"\n')
    assert cli.main([*_movies(tmp_path, "a.mkv"), "-o", str(tmp_path / "other")], asker=ScriptedAsker()) == 0
    assert (tmp_path / "other/a.mp4").exists()


def test_next_to_source_ignores_config(tmp_path, fake_tools):
    _config(f'output_dir = "{tmp_path / "ipad"}"\n')
    assert cli.main([*_movies(tmp_path, "a.mkv"), "--next-to-source"], asker=ScriptedAsker()) == 0
    assert (tmp_path / "a.mp4").exists()


def test_bad_config_stops_before_doing_anything(tmp_path, fake_tools, capsys):
    _config("output_dir = 'relative'\n")
    assert cli.main(_movies(tmp_path, "a.mkv"), asker=ScriptedAsker()) == 1
    assert "output_dir must be an absolute path" in capsys.readouterr().err
    assert not (tmp_path / "a.mp4").exists()


def test_summary_lists_every_file(tmp_path, fake_tools, capsys):
    movies = _movies(tmp_path, "a.mkv", "bad.mkv", "broken.mkv", "done.mkv")
    (tmp_path / "done.mp4").touch()

    assert cli.main([*movies, str(tmp_path / "missing.mkv")], asker=ScriptedAsker()) == 1

    out = capsys.readouterr().out
    summary = out[out.index("Summary:") :].splitlines()
    assert summary[1:3] == [
        f"  converted     {tmp_path / 'a.mkv'}",
        f"                -> {tmp_path / 'a.mp4'} (2.0 MB, 0s)",
    ]
    assert f"  skipped       {tmp_path / 'done.mkv'}: {tmp_path / 'done.mp4'} already exists" in summary[3]
    assert summary[4].startswith(f"  FAILED        {tmp_path / 'bad.mkv'}: ffprobe could not read")
    assert summary[5] == f"  FAILED        {tmp_path / 'broken.mkv'}: ffmpeg reported an error"
    assert summary[6] == f"  FAILED        {tmp_path / 'missing.mkv'}: no such file or directory"
    assert summary[7] == "Done: 1 converted, 1 skipped, 3 failed."


def test_summary_mentions_files_skipped_by_choice(tmp_path, fake_tools, capsys, monkeypatch):
    monkeypatch.setattr(cli, "probe", lambda path: media([aud("fre")]))
    assert cli.main(_movies(tmp_path, "a.mkv"), asker=ScriptedAsker("s")) == 0
    assert f"skipped       {tmp_path / 'a.mkv'}: skipped by choice" in capsys.readouterr().out


def test_dry_run_summary(tmp_path, fake_tools, capsys):
    assert cli.main([*_movies(tmp_path, "a.mkv"), "-n"], asker=ScriptedAsker()) == 0
    out = capsys.readouterr().out
    assert f"  would convert {tmp_path / 'a.mkv'}" in out
    assert "Done: 1 would convert, 0 skipped, 0 failed." in out
    assert not (tmp_path / "a.mp4").exists()


def test_help_shows_config_location(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert os.path.join("ipadmp4", "config.toml") in capsys.readouterr().out


@pytest.mark.parametrize(("seconds", "text"), [(0.4, "0s"), (59, "59s"), (61, "1m01s"), (3600 + 120, "1h02m")])
def test_duration(seconds, text):
    assert cli._duration(seconds) == text


@pytest.mark.parametrize(("n", "text"), [(500, "500 bytes"), (2_000_000, "2.0 MB"), (349_295_219, "349.3 MB")])
def test_size(n, text):
    assert cli._size(n) == text


def test_recursive_output_is_flat_in_output_dir(tmp_path, fake_tools):
    series = tmp_path / "Show"
    (series / "Season 1").mkdir(parents=True)
    (series / "Season 2").mkdir()
    (series / "Season 1/Show.S01E01.mkv").touch()
    (series / "Season 2/Show.S02E01.mkv").touch()
    out = tmp_path / "ipad"
    _config(f'output_dir = "{out}"\n')

    assert cli.main(["-r", str(series)], asker=ScriptedAsker()) == 0

    assert sorted(p.name for p in out.iterdir()) == ["Show.S01E01.mp4", "Show.S02E01.mp4"]


def test_recursive_without_output_dir_writes_next_to_each_source(tmp_path, fake_tools):
    (tmp_path / "Season 1").mkdir()
    (tmp_path / "Season 1/e1.mkv").touch()
    assert cli.main(["-r", str(tmp_path)], asker=ScriptedAsker()) == 0
    assert (tmp_path / "Season 1/e1.mp4").exists()


def test_same_name_in_two_folders_is_converted_once(tmp_path, fake_tools, capsys):
    for show in ("A", "B"):
        (tmp_path / show).mkdir()
        (tmp_path / show / "S01E01.mkv").touch()
    out = tmp_path / "ipad"

    assert cli.main(["-r", "-o", str(out), str(tmp_path / "A"), str(tmp_path / "B")], asker=ScriptedAsker()) == 0

    assert [p.name for p in out.iterdir()] == ["S01E01.mp4"]
    summary = capsys.readouterr().out.split("Summary:")[1]
    assert f"skipped       {tmp_path / 'B/S01E01.mkv'}: {out / 'S01E01.mp4'} is already produced from" in summary


@pytest.mark.parametrize(
    ("setting", "args", "expected"),
    [
        (None, [], True),
        ("cover_art = false", [], False),
        ("cover_art = false", ["--cover-art"], True),
        (None, ["--no-cover-art"], False),
    ],
)
def test_cover_art_setting_and_option(tmp_path, fake_tools, monkeypatch, setting, args, expected):
    if setting:
        _config(setting)
    seen = []

    def convert(task, opts):
        seen.append(opts.cover_art)
        task.dst.touch()
        return True

    monkeypatch.setattr(cli, "_convert", convert)
    assert cli.main([*_movies(tmp_path, "a.mkv"), *args], asker=ScriptedAsker()) == 0
    assert seen == [expected]


def _fake_ffmpeg(monkeypatch):
    """Record the ffmpeg command and 'succeed' by writing its output file."""
    commands = []

    def run(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"mp4")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(cli.subprocess, "run", run)
    return commands


def _task(tmp_path):
    info = media([aud("eng")])
    plan = Plan(audio=info.audio[0], subtitle=None)
    return cli.Task(src=tmp_path / "Heat.mkv", dst=tmp_path / "Heat.mp4", info=info, plan=plan)


def test_convert_embeds_and_cleans_up_cover(tmp_path, monkeypatch):
    commands = _fake_ffmpeg(monkeypatch)
    rendered = []

    def render(text, out):
        rendered.append(text)
        out.write_bytes(b"png")

    monkeypatch.setattr(cli, "render_title_card", render)
    assert cli._convert(_task(tmp_path), Options())
    assert rendered == ["Heat"]
    assert str(tmp_path / "Heat.mp4.cover.png") in commands[0]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Heat.mp4"]


def test_convert_without_cover_when_drawing_fails(tmp_path, monkeypatch, capsys):
    commands = _fake_ffmpeg(monkeypatch)

    def render(text, out):
        raise Ipadmp4Error("cannot draw cover art: osascript not found (macOS only)")

    monkeypatch.setattr(cli, "render_title_card", render)
    assert cli._convert(_task(tmp_path), Options())
    assert "-c:v:1" not in commands[0]
    assert "converting without cover art" in capsys.readouterr().err
    assert (tmp_path / "Heat.mp4").exists()
