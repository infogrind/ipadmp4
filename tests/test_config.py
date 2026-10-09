from pathlib import Path

import pytest

from ipadmp4.config import Config, config_path, load_config
from ipadmp4.errors import Ipadmp4Error


def test_config_path_follows_xdg():
    assert config_path({"XDG_CONFIG_HOME": "/xdg"}) == Path("/xdg/ipadmp4/config.toml")


@pytest.mark.parametrize("env", [{}, {"XDG_CONFIG_HOME": ""}, {"XDG_CONFIG_HOME": "relative/dir"}])
def test_config_path_defaults_to_dot_config(env):
    assert config_path(env) == Path.home() / ".config/ipadmp4/config.toml"


def _write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_missing_file_means_defaults(tmp_path):
    assert load_config(tmp_path / "nope.toml") == Config()


def test_empty_file_means_defaults(tmp_path):
    assert load_config(_write(tmp_path, "")) == Config()


def test_output_dir_with_tilde(tmp_path):
    config = load_config(_write(tmp_path, 'output_dir = "~/Movies/iPad"\n'))
    assert config.output_dir == Path.home() / "Movies/iPad"


def test_output_dir_with_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIP", "/data/trip")
    assert load_config(_write(tmp_path, 'output_dir = "$TRIP/mp4"')).output_dir == Path("/data/trip/mp4")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('output_dir = "Movies"', "absolute path"),
        ('output_dir = ""', "non-empty string"),
        ("output_dir = 3", "non-empty string"),
        ('outputdir = "/x"', r"unknown setting\(s\): outputdir \(known: output_dir, cover_art\)"),
        ('cover_art = "no"', "cover_art must be true or false"),
        ("output_dir = ", "invalid TOML"),
    ],
)
def test_bad_config_is_a_clear_error(tmp_path, text, message):
    path = _write(tmp_path, text)
    with pytest.raises(Ipadmp4Error, match=message) as e:
        load_config(path)
    assert str(path) in str(e.value)


def test_cover_art_defaults_to_on_and_can_be_switched_off(tmp_path):
    assert load_config(_write(tmp_path, 'output_dir = "/x"')).cover_art is True
    assert load_config(_write(tmp_path, "cover_art = false")) == Config(cover_art=False)
