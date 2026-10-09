"""The user's settings file, following the XDG base directory layout.

Read from $XDG_CONFIG_HOME/ipadmp4/config.toml, i.e. by default
~/.config/ipadmp4/config.toml. A missing file means all defaults.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import Ipadmp4Error

APP_NAME = "ipadmp4"
CONFIG_NAME = "config.toml"


@dataclass(frozen=True)
class Config:
    # Where MP4s go when -o isn't given; None means next to the originals.
    output_dir: Path | None = None
    # Embed the file name as cover art (the TV app's thumbnail).
    cover_art: bool = True


KNOWN_SETTINGS = ("output_dir", "cover_art")


def config_path(env: Mapping[str, str] = os.environ) -> Path:
    # The XDG spec says to ignore a relative XDG_CONFIG_HOME.
    base = env.get("XDG_CONFIG_HOME", "")
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"
    return root / APP_NAME / CONFIG_NAME


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return Config()
    except tomllib.TOMLDecodeError as e:
        raise Ipadmp4Error(f"{path}: invalid TOML: {e}") from None
    except OSError as e:
        raise Ipadmp4Error(f"cannot read {path}: {e.strerror}") from None

    # Reject unknown keys, so a typo doesn't silently do nothing.
    unknown = sorted(set(data) - set(KNOWN_SETTINGS))
    if unknown:
        known = ", ".join(KNOWN_SETTINGS)
        raise Ipadmp4Error(f"{path}: unknown setting(s): {', '.join(unknown)} (known: {known})")

    cover_art = data.get("cover_art", True)
    if not isinstance(cover_art, bool):
        raise Ipadmp4Error(f"{path}: cover_art must be true or false")
    return Config(output_dir=_output_dir(path, data.get("output_dir")), cover_art=cover_art)


def _output_dir(path: Path, value: object) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise Ipadmp4Error(f"{path}: output_dir must be a non-empty string")
    resolved = Path(os.path.expandvars(value)).expanduser()
    if not resolved.is_absolute():
        raise Ipadmp4Error(f"{path}: output_dir must be an absolute path (or start with ~): {value}")
    return resolved
