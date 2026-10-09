"""The CLI flow without ffmpeg: probing and converting are faked."""

import os

import pytest

from ipadmp4 import cli
from ipadmp4.errors import Ipadmp4Error

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
